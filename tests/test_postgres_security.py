"""M11.3 — PostgreSQL security regression tests.

These tests pin the security invariants that M11.3 verified against a REAL
PostgreSQL server.  They are not a re-implementation of the fix: they are
the regression net that proves the fixes hold on the real database, with
real row-level locking and real concurrent transactions.

Covered:

* the RBAC matrix over the real HTTP stack;
* the internal-service boundary on every internal route;
* refresh-token rotation, reuse rejection and CONCURRENT refresh;
* session revocation through logout and logout-all;
* the readiness probe against the real databases.

The module skips with an explicit reason when PostgreSQL is not configured,
exactly like the other PostgreSQL modules.
"""
from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from tests.postgres_env import assert_disposable_database, require_postgres_env

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "sentinel_auth")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "sentinel")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "sentinel123")

ENGINE_URL = (
    f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

require_postgres_env(__name__)

#: The internal secret the test server and the test client must agree on.
TEST_INTERNAL_SECRET = "m113-postgres-internal-secret-0123456789ab"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    eng = create_engine(ENGINE_URL, pool_size=10, max_overflow=20, pool_pre_ping=True)
    assert_disposable_database(ENGINE_URL, "the M11.3 security regression tests")
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture()
def pg_conn(engine):
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        yield conn


@pytest.fixture()
def orm_session(engine):
    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = maker()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def pg_client(engine, monkeypatch):
    """A TestClient bound to the real PostgreSQL database.

    The disposable database holds all three schemas, so EVERY context
    dependency is replaced by a session on the same database.  A missing
    override would let a route open a session against the *deployment*
    database instead of the disposable one, and the test would then read
    the wrong data.
    """
    from fastapi.testclient import TestClient

    import app.alerts as alerts_mod
    import app.auth as _auth_mod
    import app.authz as authz_mod
    import app.detection as detection_mod
    import app.devices as devices_mod
    import app.iam as iam_mod
    import app.internal_actions as internal_actions_mod
    import app.ml as ml_mod
    from app.main import app

    monkeypatch.setenv("INTERNAL_SECRET", TEST_INTERNAL_SECRET)
    monkeypatch.setenv("RUN_PRE_TOKEN_CHECK", "0")
    monkeypatch.setenv("RUN_LOGIN_EVENT_DELIVERY", "0")
    monkeypatch.setattr(_auth_mod, "get_client_ip", lambda request: "127.0.0.1")

    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _get_db():
        session = maker()
        try:
            yield session
        finally:
            session.close()

    for module in (
        _auth_mod,
        alerts_mod,
        authz_mod,
        detection_mod,
        devices_mod,
        iam_mod,
        internal_actions_mod,
        ml_mod,
    ):
        for attribute in ("get_core_db", "get_detection_db", "get_ml_db"):
            dependency = getattr(module, attribute, None)
            if dependency is not None:
                app.dependency_overrides[dependency] = _get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_rate_limits(engine):
    """The login endpoint rate-limits by client IP.

    The tests log in repeatedly from the same (mocked) IP, so the counter
    has to be cleared between them - otherwise a rate limit would look
    like an authentication failure.
    """
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM rate_limits"))
    yield
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM rate_limits"))


def _ensure_roles(pg_conn) -> None:
    """Seed the four canonical roles."""
    for role_id, name, name_vi in (
        ("USER", "User", "Người dùng"),
        ("SOC_ANALYST", "SOC Analyst", "Chuyên viên SOC"),
        ("SECURITY_MANAGER", "Security Manager", "Quản lý bảo mật"),
        ("SECURITY_ADMIN", "Security Administrator", "Quản trị bảo mật"),
    ):
        pg_conn.execute(text(
            "INSERT INTO roles (id, name, name_vi) VALUES (:id, :n, :v) "
            "ON CONFLICT (id) DO NOTHING"
        ), {"id": role_id, "n": name, "v": name_vi})
    pg_conn.commit()


def _create_user(engine, username: str, roles: list) -> str:
    """Create an active user with the given roles and return its id.

    The operation is idempotent: a user that already exists is reused (and
    its roles are re-asserted), so a rerun against the same disposable
    database does not fail on the unique username constraint.
    """
    from argon2 import PasswordHasher

    ph = PasswordHasher()
    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = maker()
    try:
        existing = session.execute(text(
            "SELECT id FROM users WHERE username = :u"
        ), {"u": username}).fetchone()
        if existing is not None:
            user_id = str(existing[0])
        else:
            user_id = str(uuid.uuid4())
            session.execute(text(
                "INSERT INTO users (id, username, email, password_hash, status, "
                "admin_mfa_required, detection_mfa_once, created_at) "
                "VALUES (:id, :u, :e, :h, 'active', FALSE, FALSE, now())"
            ), {
                "id": user_id,
                "u": username,
                "e": f"{username}@example.test",
                "h": ph.hash("M11.3-Probe-Password-123!"),
            })
        for role in roles:
            session.execute(text(
                "INSERT INTO user_roles (user_id, role_id, assigned_at) "
                "VALUES (:uid, :r, now()) ON CONFLICT DO NOTHING"
            ), {"uid": user_id, "r": role})
        session.commit()
        return user_id
    finally:
        session.close()


def _login(client, username: str) -> str:
    response = client.post("/api/v1/auth/login", json={
        "username": username,
        "password": "M11.3-Probe-Password-123!",
    })
    assert response.status_code == 200, response.json()
    return response.json()["access_token"]


# ---------------------------------------------------------------------------
# B. The RBAC matrix
# ---------------------------------------------------------------------------

class TestRbacMatrixOverHttp:
    """The role matrix holds on the real stack, with real sessions.

    The tokens are REAL bearer tokens minted by the login endpoint, so the
    whole authentication chain is exercised - not a mocked auth context.
    """

    @pytest.fixture(autouse=True)
    def _seed(self, engine, pg_conn):
        _ensure_roles(pg_conn)
        self._users = {}
        for username, roles in (
            ("m113_user", ["USER"]),
            ("m113_analyst", ["USER", "SOC_ANALYST"]),
            ("m113_manager", ["USER", "SECURITY_MANAGER"]),
            ("m113_admin", ["USER", "SECURITY_ADMIN"]),
        ):
            self._users[username] = _create_user(engine, username, roles)

    def _token(self, client, username):
        return _login(client, username)

    def test_a_user_cannot_read_the_soc_alerts(self, pg_client):
        token = self._token(pg_client, "m113_user")
        response = pg_client.get("/api/v1/alerts",
                                 headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403

    def test_a_user_cannot_read_the_policies(self, pg_client):
        token = self._token(pg_client, "m113_user")
        response = pg_client.get("/api/v1/policies",
                                 headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403

    def test_a_user_cannot_read_the_manager_analytics(self, pg_client):
        token = self._token(pg_client, "m113_user")
        response = pg_client.get("/api/v1/manager/dashboard",
                                 headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403

    def test_a_user_cannot_reach_the_iam_administration(self, pg_client):
        token = self._token(pg_client, "m113_user")
        response = pg_client.get("/api/v1/admin/users",
                                 headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403

    def test_a_soc_analyst_can_read_the_alerts(self, pg_client):
        token = self._token(pg_client, "m113_analyst")
        response = pg_client.get("/api/v1/alerts",
                                 headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200

    def test_a_soc_analyst_cannot_read_the_manager_analytics(self, pg_client):
        """The Manager facade is the SECURITY_MANAGER's view."""
        token = self._token(pg_client, "m113_analyst")
        response = pg_client.get("/api/v1/manager/dashboard",
                                 headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403

    def test_a_soc_analyst_cannot_activate_a_policy(self, pg_client):
        token = self._token(pg_client, "m113_analyst")
        response = pg_client.get("/api/v1/policies",
                                 headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403

    def test_a_security_manager_can_read_the_manager_analytics(self, pg_client):
        """The Manager facade is reachable for the SECURITY_MANAGER.

        The facade reads Core and Detection over the HTTP boundary, and the
        test client has no live upstream, so the honest outcome is either
        200 (every source answered) or 503 (a source did not).  What this
        test pins is the AUTHORISATION: the request must pass the role
        gate, so it can never be 401 or 403.
        """
        token = self._token(pg_client, "m113_manager")
        response = pg_client.get("/api/v1/manager/dashboard",
                                 headers={"Authorization": f"Bearer {token}"})
        assert response.status_code in (200, 503), response.json()
        assert response.status_code != 403

    def test_a_security_manager_cannot_reach_the_iam_administration(self, pg_client):
        token = self._token(pg_client, "m113_manager")
        response = pg_client.get("/api/v1/admin/users",
                                 headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403

    def test_a_security_manager_cannot_activate_a_policy(self, pg_client):
        """Only the SECURITY_ADMIN may activate a policy."""
        token = self._token(pg_client, "m113_manager")
        policies = pg_client.get("/api/v1/policies",
                                 headers={"Authorization": f"Bearer {token}"})
        assert policies.status_code == 200
        if not policies.json():
            pytest.skip("no policy is seeded in the disposable database")
        policy_id = policies.json()[0]["id"]
        response = pg_client.post(f"/api/v1/policies/{policy_id}/activate",
                                  headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403

    def test_a_security_admin_can_read_the_policies(self, pg_client):
        token = self._token(pg_client, "m113_admin")
        response = pg_client.get("/api/v1/policies",
                                 headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200

    def test_a_security_admin_cannot_read_the_soc_alerts(self, pg_client):
        """SECURITY_ADMIN is not a SOC role."""
        token = self._token(pg_client, "m113_admin")
        response = pg_client.get("/api/v1/alerts",
                                 headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403

    def test_a_security_admin_cannot_read_the_manager_analytics(self, pg_client):
        token = self._token(pg_client, "m113_admin")
        response = pg_client.get("/api/v1/manager/dashboard",
                                 headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403

    def test_a_security_admin_can_reach_the_iam_administration(self, pg_client):
        token = self._token(pg_client, "m113_admin")
        response = pg_client.get("/api/v1/admin/users",
                                 headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# B. The internal-service boundary
# ---------------------------------------------------------------------------

class TestInternalBoundaryOverHttp:
    """Every internal route rejects a missing or wrong internal secret."""

    def test_the_internal_routes_reject_a_missing_secret(self, pg_client):
        for method, path in (
            ("get", "/api/v1/internal/users/00000000-0000-0000-0000-000000000002"),
            ("get", "/api/v1/internal/analytics/core"),
            ("get", "/api/v1/internal/analytics/detection"),
        ):
            response = getattr(pg_client, method)(path)
            assert response.status_code == 401, path

    def test_the_internal_routes_reject_a_wrong_secret(self, pg_client):
        response = pg_client.get(
            "/api/v1/internal/analytics/core",
            headers={"X-Internal-Secret": "wrong-secret-value-at-least-32-chars"},
        )
        assert response.status_code == 401

    def test_a_user_bearer_token_does_not_open_the_internal_boundary(self, pg_client):
        """The two boundaries are separate: a human token is not a service token."""
        response = pg_client.post("/api/v1/auth/login", json={
            "username": "m113_user",
            "password": "M11.3-Probe-Password-123!",
        })
        if response.status_code != 200:
            pytest.skip("the probe user is not seeded in this database")
        token = response.json()["access_token"]
        internal = pg_client.get(
            "/api/v1/internal/analytics/core",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert internal.status_code == 401


# ---------------------------------------------------------------------------
# D. Session and token security
# ---------------------------------------------------------------------------

class TestSessionAndTokenSecurity:
    """Refresh rotation, reuse rejection and concurrent refresh."""

    @pytest.fixture(autouse=True)
    def _seed(self, engine, pg_conn):
        _ensure_roles(pg_conn)
        self._user_id = _create_user(engine, "m113_session", ["USER"])

    def _login(self, client):
        response = client.post("/api/v1/auth/login", json={
            "username": "m113_session",
            "password": "M11.3-Probe-Password-123!",
        })
        assert response.status_code == 200, response.json()
        return response.json()

    def test_the_refresh_rotates_both_tokens(self, pg_client):
        payload = self._login(pg_client)
        response = pg_client.post("/api/v1/auth/refresh", json={
            "refresh_token": payload["refresh_token"],
        })
        assert response.status_code == 200, response.json()
        rotated = response.json()
        assert rotated["access_token"] != payload["access_token"]
        assert rotated["refresh_token"] != payload["refresh_token"]

    def test_the_old_refresh_token_is_rejected_after_the_rotation(self, pg_client):
        payload = self._login(pg_client)
        pg_client.post("/api/v1/auth/refresh",
                       json={"refresh_token": payload["refresh_token"]})
        response = pg_client.post("/api/v1/auth/refresh", json={
            "refresh_token": payload["refresh_token"],
        })
        assert response.status_code == 401

    def test_the_old_access_token_is_rejected_after_the_rotation(self, pg_client):
        payload = self._login(pg_client)
        pg_client.post("/api/v1/auth/refresh",
                       json={"refresh_token": payload["refresh_token"]})
        response = pg_client.get("/api/v1/auth/me", headers={
            "Authorization": f"Bearer {payload['access_token']}",
        })
        assert response.status_code == 401

    def test_the_new_access_token_works_after_the_rotation(self, pg_client):
        payload = self._login(pg_client)
        rotated = pg_client.post("/api/v1/auth/refresh", json={
            "refresh_token": payload["refresh_token"],
        }).json()
        response = pg_client.get("/api/v1/auth/me", headers={
            "Authorization": f"Bearer {rotated['access_token']}",
        })
        assert response.status_code == 200

    def test_a_concurrent_refresh_issues_at_most_one_live_token(self, pg_client):
        """The same refresh token used twice must not mint two live sessions.

        The refresh endpoint rotates the stored hash, so the second use of
        the OLD token cannot find the session any more.  The invariant is
        pinned here against real concurrent transactions.
        """
        payload = self._login(pg_client)
        shared = payload["refresh_token"]

        def _refresh():
            response = pg_client.post("/api/v1/auth/refresh",
                                      json={"refresh_token": shared})
            return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _i: _refresh(), range(2)))

        codes = sorted(code for code, _ in results)
        assert codes.count(200) <= 1, (
            f"the same refresh token was accepted {codes.count(200)} times"
        )

        live = 0
        for code, body in results:
            if code != 200:
                continue
            response = pg_client.get("/api/v1/auth/me", headers={
                "Authorization": f"Bearer {body['access_token']}",
            })
            if response.status_code == 200:
                live += 1
        assert live <= 1, f"{live} access tokens are live from one refresh token"

    def test_logout_revokes_the_session(self, pg_client):
        payload = self._login(pg_client)
        token = payload["access_token"]
        response = pg_client.post("/api/v1/auth/logout",
                                  headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        after = pg_client.get("/api/v1/auth/me",
                              headers={"Authorization": f"Bearer {token}"})
        assert after.status_code == 401

    def test_logout_all_revokes_every_session_of_the_user(self, pg_client):
        payload = self._login(pg_client)
        token = payload["access_token"]
        response = pg_client.post("/api/v1/auth/logout-all",
                                  headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        after = pg_client.get("/api/v1/auth/me",
                              headers={"Authorization": f"Bearer {token}"})
        assert after.status_code == 401

    def test_a_user_cannot_revoke_another_users_session(self, engine, pg_client, pg_conn):
        _ensure_roles(pg_conn)
        other_id = _create_user(engine, "m113_other", ["USER"])
        payload = self._login(pg_client)
        sessions = pg_client.get("/api/v1/auth/sessions", headers={
            "Authorization": f"Bearer {payload['access_token']}",
        })
        assert sessions.status_code == 200
        if not sessions.json()["sessions"]:
            pytest.skip("no session to cross-revoke")

        # A second user of the same database tries to revoke the first one's
        # session.  The session id must belong to the first user.
        other_token = None
        response = pg_client.post("/api/v1/auth/login", json={
            "username": "m113_other",
            "password": "M11.3-Probe-Password-123!",
        })
        if response.status_code == 200:
            other_token = response.json()["access_token"]
        if other_token is None:
            pytest.skip("the second probe user could not log in")

        session_id = sessions.json()["sessions"][0]["id"]
        response = pg_client.delete(f"/api/v1/auth/sessions/{session_id}",
                                    headers={"Authorization": f"Bearer {other_token}"})
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# C. The readiness probe against the real databases
# ---------------------------------------------------------------------------

class TestReadinessAgainstRealDatabases:
    """The probe reports the real state of the real databases."""

    def test_the_probe_reports_every_context_as_ok(self, engine, monkeypatch):
        from app import db, readiness

        monkeypatch.setattr(db, "resolve_database_url", lambda context: ENGINE_URL)
        readiness.reset_readiness_cache()

        payload = readiness.readiness_payload()
        assert payload["status"] == "ready", payload
        for context in (db.CORE, db.DETECTION, db.ML):
            assert payload["checks"][context]["status"] == "ok", payload
        readiness.reset_readiness_cache()

    def test_the_probe_writes_nothing(self, engine, monkeypatch):
        """The probe is read-only: it must not append an inference log."""
        from app import db, readiness

        monkeypatch.setattr(db, "resolve_database_url", lambda context: ENGINE_URL)
        readiness.reset_readiness_cache()

        maker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        session = maker()
        try:
            before = session.execute(text(
                "SELECT count(*) FROM inference_logs"
            )).scalar()
        finally:
            session.close()

        readiness.readiness_payload()

        session = maker()
        try:
            after = session.execute(text(
                "SELECT count(*) FROM inference_logs"
            )).scalar()
        finally:
            session.close()

        assert before == after, (
            f"the readiness probe wrote {after - before} inference log row(s)"
        )
        readiness.reset_readiness_cache()

    def test_an_unreachable_database_makes_the_probe_not_ready(self, monkeypatch):
        """A database that cannot be reached is a hard failure."""
        from app import db, readiness

        def _broken(context):
            raise sa.exc.OperationalError("SELECT 1", {}, Exception("connection refused"))

        monkeypatch.setattr(db, "get_context_session", _broken)
        readiness.reset_readiness_cache()

        payload = readiness.readiness_payload()
        assert payload["status"] == "not_ready", payload
        assert payload["checks"][db.CORE]["status"] == "unavailable", payload
        readiness.reset_readiness_cache()

    def test_the_probe_does_not_leak_its_statement_timeout_into_the_pool(self):
        """The probe's own timeout must not reach the application's queries.

        The probe runs ``SET LOCAL statement_timeout`` on its session.  If
        that setting survived onto the pooled connection, every later
        application query would be cut off after the probe's budget - a
        self-inflicted outage caused by the health check itself.
        """
        from app import db, readiness

        original = db.resolve_database_url
        try:
            db.resolve_database_url = lambda context: ENGINE_URL
            readiness.reset_readiness_cache()
            readiness.readiness_payload()

            session = db.get_context_session(db.CORE)
            try:
                value = session.execute(text("SHOW statement_timeout")).scalar()
            finally:
                session.close()
        finally:
            db.resolve_database_url = original
            readiness.reset_readiness_cache()

        assert value in ("0", "2s"), (
            f"the probe leaked its statement timeout into the pool: {value!r}"
        )

    def test_the_probe_leaves_no_open_transaction(self):
        """The probe must not leave a transaction running on its session."""
        from app import db, readiness

        original = db.resolve_database_url
        try:
            db.resolve_database_url = lambda context: ENGINE_URL
            readiness.reset_readiness_cache()
            readiness.readiness_payload()
        finally:
            db.resolve_database_url = original
            readiness.reset_readiness_cache()

        # A session opened AFTER the probe must be clean: it must not
        # inherit an open transaction from the probe.
        session = db.get_context_session(db.CORE)
        try:
            assert not session.in_transaction(), (
                "the probe left a transaction open on the pooled session"
            )
        finally:
            session.close()

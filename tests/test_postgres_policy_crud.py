"""F-1 — PostgreSQL integration tests for the Policy Create/Edit lifecycle.

These tests exercise the F-1 endpoints against a REAL PostgreSQL server:

    * ``POST   /api/v1/policies``             (create)
    * ``GET    /api/v1/policies/{policy_id}`` (detail)
    * ``PUT    /api/v1/policies/{policy_id}`` (edit)

Covered:

    * create: valid, invalid rules/config, duplicate version, server-owned
      fields, and the "always inactive" rule;
    * detail: the full payload, the authorisation matrix, 404, the
      concurrency token it hands out, and that a read never writes;
    * edit: valid, invalid, partial, active-policy protection, previously
      activated policy protection, and optimistic concurrency;
    * the FULL authorisation matrix (SECURITY_ADMIN, SECURITY_MANAGER,
      SOC_ANALYST, USER, unauthenticated);
    * the full lifecycle create -> edit -> activate -> detection evaluation;
    * that historical risk assessments are NOT rewritten by a policy edit;
    * that a create/edit never writes to the Core or the ML database
      (bounded-context isolation);
    * that a failed write leaves no partial row behind (rollback).

The module skips with an explicit reason when PostgreSQL is not configured,
exactly like the other PostgreSQL modules.
"""
from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.main import app
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
TEST_INTERNAL_SECRET = "f1-policy-internal-secret-0123456789abcdef"

#: A policy body that the canonical validators accept.
VALID_RULES = [
    {
        "name": "unusual_hour",
        "field": "hour_of_day",
        "operator": "not_between",
        "value": [7, 22],
        "weight": 0.30,
        "score": 0.80,
        "enabled": True,
        "description": "Login outside 07:00-22:59 UTC",
    },
    {
        "name": "multiple_failures",
        "field": "fail_count_24h",
        "operator": ">=",
        "value": 3,
        "weight": 0.40,
        "score": 0.90,
        "enabled": True,
    },
]

VALID_CONFIG = {
    "weights": {"rule": 0.4, "ml": 0.6},
    "thresholds": {"low": 0.25, "medium": 0.5, "high": 0.75},
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    eng = create_engine(ENGINE_URL, pool_size=10, max_overflow=20, pool_pre_ping=True)
    assert_disposable_database(ENGINE_URL, "the F-1 policy CRUD tests")
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

    Every context dependency is replaced by a session on the disposable
    database, so no route can reach the deployment database by accident.
    """
    import app.alerts as alerts_mod
    import app.auth as _auth_mod
    import app.authz as authz_mod
    import app.detection as detection_mod
    import app.devices as devices_mod
    import app.iam as iam_mod
    import app.internal_actions as internal_actions_mod
    import app.ml as ml_mod

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
    """Create an active user with the given roles and return its id."""
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
                "h": ph.hash("F1-Probe-Password-123!"),
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
        "password": "F1-Probe-Password-123!",
    })
    assert response.status_code == 200, response.json()
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _version(prefix: str = "v") -> str:
    """A fresh, unique policy version.

    The canonical pattern is ``^v\\d+(\\.\\d+)*$`` (``v1.0``, ``v2.0``),
    so the random part has to be numeric.
    """
    return f"{prefix}{uuid.uuid4().int % 10 ** 12:012d}"


# ---------------------------------------------------------------------------
# Shared seeding
# ---------------------------------------------------------------------------

class _PolicyTestBase:
    """Common seeding for the F-1 test classes."""

    @pytest.fixture(autouse=True)
    def _seed(self, engine, pg_conn):
        _ensure_roles(pg_conn)
        for username, roles in (
            ("f1_user", ["USER"]),
            ("f1_analyst", ["USER", "SOC_ANALYST"]),
            ("f1_manager", ["USER", "SECURITY_MANAGER"]),
            ("f1_admin", ["USER", "SECURITY_ADMIN"]),
        ):
            _create_user(engine, username, roles)

    def _token(self, client, username: str) -> str:
        return _login(client, username)


# ---------------------------------------------------------------------------
# A. Create
# ---------------------------------------------------------------------------

class TestPolicyCreate(_PolicyTestBase):
    """``POST /api/v1/policies``."""

    def _create(self, client, token, **overrides):
        body = {
            "version": _version(),
            "name": "F-1 test policy",
            "description": "created by the F-1 test suite",
            "rules": VALID_RULES,
            "config": VALID_CONFIG,
        }
        body.update(overrides)
        return client.post("/api/v1/policies", json=body, headers=_auth(token))

    def test_a_valid_policy_is_created_and_is_inactive(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        response = self._create(pg_client, token)
        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["version"].startswith("v")
        assert payload["is_active"] is False
        assert payload["activated_at"] is None
        assert payload["name"] == "F-1 test policy"
        assert len(payload["rules"]) == 2
        assert payload["config"]["weights"] == {"rule": 0.4, "ml": 0.6}

    def test_a_created_policy_is_visible_in_the_listing(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        created = self._create(pg_client, token).json()
        listing = pg_client.get("/api/v1/policies", headers=_auth(token))
        assert listing.status_code == 200
        versions = {row["version"] for row in listing.json()}
        assert created["version"] in versions

    def test_the_creator_is_recorded_as_created_by(self, pg_client, engine):
        token = self._token(pg_client, "f1_admin")
        created = self._create(pg_client, token).json()
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT created_by FROM policies WHERE id = :id"),
                {"id": created["id"]},
            ).fetchone()
        assert row is not None
        assert row[0] is not None
        assert str(row[0]) == created["created_by"]

    def test_the_created_policy_is_inactive_in_the_database(self, pg_client, engine):
        token = self._token(pg_client, "f1_admin")
        created = self._create(pg_client, token).json()
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT is_active FROM policies WHERE id = :id"),
                {"id": created["id"]},
            ).fetchone()
        assert row[0] is False

    def test_a_duplicate_version_is_a_conflict(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        version = _version()
        assert self._create(pg_client, token, version=version).status_code == 201
        second = self._create(pg_client, token, version=version)
        assert second.status_code == 409
        assert "already exists" in second.json()["detail"]["message"]

    def test_an_unknown_feature_is_rejected(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        rules = [dict(VALID_RULES[0], field="not_a_feature")]
        response = self._create(pg_client, token, rules=rules)
        assert response.status_code == 400
        problems = response.json()["detail"]["problems"]
        assert any("unknown feature" in problem for problem in problems)

    def test_an_unsupported_operator_is_rejected(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        rules = [dict(VALID_RULES[0], operator="~=")]
        response = self._create(pg_client, token, rules=rules)
        assert response.status_code == 400
        problems = response.json()["detail"]["problems"]
        assert any("unsupported operator" in problem for problem in problems)

    def test_an_out_of_range_weight_is_rejected(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        rules = [dict(VALID_RULES[0], weight=1.5)]
        response = self._create(pg_client, token, rules=rules)
        assert response.status_code == 400
        problems = response.json()["detail"]["problems"]
        assert any("outside [0, 1]" in problem for problem in problems)

    def test_a_rule_missing_a_mandatory_field_is_rejected(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        broken = {k: v for k, v in VALID_RULES[0].items() if k != "score"}
        response = self._create(pg_client, token, rules=[broken])
        assert response.status_code == 400
        problems = response.json()["detail"]["problems"]
        assert any("missing field" in problem for problem in problems)

    def test_duplicate_rule_names_are_rejected(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        rules = [VALID_RULES[0], dict(VALID_RULES[1], name=VALID_RULES[0]["name"])]
        response = self._create(pg_client, token, rules=rules)
        assert response.status_code == 400
        problems = response.json()["detail"]["problems"]
        assert any("duplicate rule name" in problem for problem in problems)

    def test_weights_that_do_not_sum_to_one_are_rejected(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        config = {"weights": {"rule": 0.5, "ml": 0.9}, "thresholds": VALID_CONFIG["thresholds"]}
        response = self._create(pg_client, token, config=config)
        assert response.status_code == 400
        problems = response.json()["detail"]["problems"]
        assert any("must equal 1.0" in problem for problem in problems)

    def test_thresholds_out_of_order_are_rejected(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        config = {
            "weights": VALID_CONFIG["weights"],
            "thresholds": {"low": 0.9, "medium": 0.5, "high": 0.75},
        }
        response = self._create(pg_client, token, config=config)
        assert response.status_code == 400
        problems = response.json()["detail"]["problems"]
        assert any("low <= medium <= high" in problem for problem in problems)

    def test_an_empty_rule_list_is_rejected(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        response = self._create(pg_client, token, rules=[])
        assert response.status_code in (400, 422)

    def test_a_client_cannot_set_is_active(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        response = self._create(pg_client, token, is_active=True)
        assert response.status_code == 400
        problems = response.json()["detail"]["problems"]
        assert any("is_active" in problem for problem in problems)

    def test_a_client_cannot_set_created_by(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        response = self._create(pg_client, token, created_by=str(uuid.uuid4()))
        assert response.status_code == 400
        problems = response.json()["detail"]["problems"]
        assert any("created_by" in problem for problem in problems)

    def test_a_client_cannot_set_a_timestamp(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        response = self._create(pg_client, token, created_at="2020-01-01T00:00:00Z")
        assert response.status_code == 400
        problems = response.json()["detail"]["problems"]
        assert any("created_at" in problem for problem in problems)

    def test_a_rejected_create_leaves_no_row_behind(self, pg_client, engine):
        """A failed write must not leave a partial policy in the table."""
        token = self._token(pg_client, "f1_admin")
        version = _version()
        before = self._count_policies(engine, version)
        assert before == 0
        response = self._create(pg_client, token, version=version, rules=[
            dict(VALID_RULES[0], field="not_a_feature"),
        ])
        assert response.status_code == 400
        assert self._count_policies(engine, version) == 0

    @staticmethod
    def _count_policies(engine, version: str) -> int:
        with engine.connect() as conn:
            return conn.execute(
                text("SELECT count(*) FROM policies WHERE version = :v"),
                {"v": version},
            ).scalar_one()

    def test_a_version_must_match_the_canonical_pattern(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        response = self._create(pg_client, token, version="not-a-version")
        assert response.status_code in (400, 422)


# ---------------------------------------------------------------------------
# B. Edit
# ---------------------------------------------------------------------------

class TestPolicyEdit(_PolicyTestBase):
    """``PUT /api/v1/policies/{policy_id}``."""

    def _create(self, client, token, **overrides):
        body = {
            "version": _version(),
            "name": "draft",
            "rules": VALID_RULES,
            "config": VALID_CONFIG,
        }
        body.update(overrides)
        response = client.post("/api/v1/policies", json=body, headers=_auth(token))
        assert response.status_code == 201, response.text
        return response.json()

    def _edit(self, client, token, policy, **body):
        payload = {"expected_updated_at": policy["updated_at"]}
        payload.update(body)
        return client.put(
            f"/api/v1/policies/{policy['id']}",
            json=payload,
            headers=_auth(token),
        )

    def test_a_draft_policy_can_be_edited(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        policy = self._create(pg_client, token)
        response = self._edit(pg_client, token, policy, name="renamed")
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "renamed"
        assert response.json()["version"] == policy["version"]

    def test_the_edit_is_persisted(self, pg_client, engine):
        token = self._token(pg_client, "f1_admin")
        policy = self._create(pg_client, token)
        self._edit(pg_client, token, policy, name="persisted")
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT name FROM policies WHERE id = :id"),
                {"id": policy["id"]},
            ).fetchone()
        assert row[0] == "persisted"

    def test_an_omitted_field_keeps_its_value(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        policy = self._create(pg_client, token)
        response = self._edit(pg_client, token, policy, name="only-the-name")
        assert response.status_code == 200
        assert response.json()["name"] == "only-the-name"
        assert response.json()["config"]["weights"] == {"rule": 0.4, "ml": 0.6}
        assert len(response.json()["rules"]) == 2

    def test_the_rules_can_be_replaced(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        policy = self._create(pg_client, token)
        new_rules = [dict(VALID_RULES[0], score=0.95)]
        response = self._edit(pg_client, token, policy, rules=new_rules)
        assert response.status_code == 200
        assert len(response.json()["rules"]) == 1
        assert response.json()["rules"][0]["score"] == 0.95

    def test_an_invalid_rule_is_rejected(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        policy = self._create(pg_client, token)
        response = self._edit(pg_client, token, policy, rules=[
            dict(VALID_RULES[0], field="not_a_feature"),
        ])
        assert response.status_code == 400
        problems = response.json()["detail"]["problems"]
        assert any("unknown feature" in problem for problem in problems)

    def test_an_invalid_config_is_rejected(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        policy = self._create(pg_client, token)
        response = self._edit(pg_client, token, policy, config={
            "weights": {"rule": 0.9, "ml": 0.9},
        })
        assert response.status_code == 400

    def test_a_rejected_edit_does_not_change_the_policy(self, pg_client, engine):
        token = self._token(pg_client, "f1_admin")
        policy = self._create(pg_client, token)
        self._edit(pg_client, token, policy, rules=[
            dict(VALID_RULES[0], field="not_a_feature"),
        ])
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT rules FROM policies WHERE id = :id"),
                {"id": policy["id"]},
            ).fetchone()
        assert row[0] == VALID_RULES

    def test_the_version_cannot_be_changed_by_an_edit(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        policy = self._create(pg_client, token)
        response = self._edit(pg_client, token, policy, version=_version())
        assert response.status_code in (400, 422)

    def test_an_unknown_policy_is_a_404(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        response = pg_client.put(
            f"/api/v1/policies/{uuid.uuid4()}",
            json={"expected_updated_at": "2026-01-01T00:00:00+00:00"},
            headers=_auth(token),
        )
        assert response.status_code == 404

    def test_a_stale_concurrency_token_is_a_conflict(self, pg_client):
        """A blind write must not silently discard a concurrent change."""
        token = self._token(pg_client, "f1_admin")
        policy = self._create(pg_client, token)
        first = self._edit(pg_client, token, policy, name="first writer")
        assert first.status_code == 200
        # Re-use the STALE token from the original read.
        second = self._edit(pg_client, token, policy, name="second writer")
        assert second.status_code == 409
        assert "modified by someone else" in second.json()["detail"]["message"]

    def test_a_matching_concurrency_token_is_accepted(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        policy = self._create(pg_client, token)
        response = self._edit(pg_client, token, policy, name="fresh token")
        assert response.status_code == 200

    def test_an_active_policy_cannot_be_edited(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        policy = self._create(pg_client, token)
        activation = pg_client.post(
            f"/api/v1/policies/{policy['id']}/activate", headers=_auth(token))
        assert activation.status_code == 200
        response = self._edit(pg_client, token, policy, name="nope")
        assert response.status_code == 409
        assert "immutable" in response.json()["detail"]["message"]

    def test_a_previously_activated_policy_cannot_be_edited(self, pg_client):
        """Once a policy has been in service, its rules are frozen.

        The risk assessments it produced reference it, so changing its
        rules would rewrite the meaning of history.
        """
        token = self._token(pg_client, "f1_admin")
        policy = self._create(pg_client, token)
        assert pg_client.post(
            f"/api/v1/policies/{policy['id']}/activate", headers=_auth(token)
        ).status_code == 200
        # A second policy takes over the active slot.
        successor = self._create(pg_client, token)
        assert pg_client.post(
            f"/api/v1/policies/{successor['id']}/activate", headers=_auth(token)
        ).status_code == 200
        # The first policy is inactive again, but it has been active.
        response = self._edit(pg_client, token, policy, name="nope")
        assert response.status_code == 409
        assert "immutable" in response.json()["detail"]["message"]

    def test_a_client_cannot_set_is_active_on_an_edit(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        policy = self._create(pg_client, token)
        response = self._edit(pg_client, token, policy, is_active=True)
        assert response.status_code == 400
        problems = response.json()["detail"]["problems"]
        assert any("is_active" in problem for problem in problems)


# ---------------------------------------------------------------------------
# C. Authorisation matrix
# ---------------------------------------------------------------------------

class TestPolicyAuthorisationMatrix(_PolicyTestBase):
    """The full role matrix over the real HTTP stack."""

    def _create_body(self):
        return {
            "version": _version(),
            "name": "rbac",
            "rules": VALID_RULES,
            "config": VALID_CONFIG,
        }

    def test_an_unauthenticated_create_is_401(self, pg_client):
        response = pg_client.post("/api/v1/policies", json=self._create_body())
        assert response.status_code == 401

    def test_an_unauthenticated_edit_is_401(self, pg_client):
        response = pg_client.put(
            f"/api/v1/policies/{uuid.uuid4()}",
            json={"expected_updated_at": "2026-01-01T00:00:00+00:00"},
        )
        assert response.status_code == 401

    def test_a_user_cannot_create(self, pg_client):
        token = self._token(pg_client, "f1_user")
        response = pg_client.post("/api/v1/policies", json=self._create_body(),
                                   headers=_auth(token))
        assert response.status_code == 403

    def test_a_user_cannot_edit(self, pg_client):
        token = self._token(pg_client, "f1_user")
        response = pg_client.put(
            f"/api/v1/policies/{uuid.uuid4()}",
            json={"expected_updated_at": "2026-01-01T00:00:00+00:00"},
            headers=_auth(token),
        )
        assert response.status_code == 403

    def test_a_soc_analyst_cannot_create(self, pg_client):
        token = self._token(pg_client, "f1_analyst")
        response = pg_client.post("/api/v1/policies", json=self._create_body(),
                                   headers=_auth(token))
        assert response.status_code == 403

    def test_a_soc_analyst_cannot_edit(self, pg_client):
        token = self._token(pg_client, "f1_analyst")
        response = pg_client.put(
            f"/api/v1/policies/{uuid.uuid4()}",
            json={"expected_updated_at": "2026-01-01T00:00:00+00:00"},
            headers=_auth(token),
        )
        assert response.status_code == 403

    def test_a_security_manager_cannot_create(self, pg_client):
        """The Manager role is view-only."""
        token = self._token(pg_client, "f1_manager")
        response = pg_client.post("/api/v1/policies", json=self._create_body(),
                                   headers=_auth(token))
        assert response.status_code == 403

    def test_a_security_manager_cannot_edit(self, pg_client):
        token = self._token(pg_client, "f1_manager")
        response = pg_client.put(
            f"/api/v1/policies/{uuid.uuid4()}",
            json={"expected_updated_at": "2026-01-01T00:00:00+00:00"},
            headers=_auth(token),
        )
        assert response.status_code == 403

    def test_a_security_manager_can_still_view(self, pg_client):
        token = self._token(pg_client, "f1_manager")
        response = pg_client.get("/api/v1/policies", headers=_auth(token))
        assert response.status_code == 200

    def test_a_security_admin_can_create(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        response = pg_client.post("/api/v1/policies", json=self._create_body(),
                                   headers=_auth(token))
        assert response.status_code == 201

    def test_a_security_admin_can_edit(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        created = pg_client.post("/api/v1/policies", json=self._create_body(),
                                  headers=_auth(token)).json()
        response = pg_client.put(
            f"/api/v1/policies/{created['id']}",
            json={"expected_updated_at": created["updated_at"], "name": "edited"},
            headers=_auth(token),
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# D. The full lifecycle
# ---------------------------------------------------------------------------

class TestPolicyLifecycle(_PolicyTestBase):
    """create -> edit -> activate -> detection evaluation."""

    def test_create_edit_activate_evaluate(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        version = _version()
        created = pg_client.post("/api/v1/policies", json={
            "version": version,
            "name": "lifecycle",
            "rules": VALID_RULES,
            "config": VALID_CONFIG,
        }, headers=_auth(token)).json()

        edited = pg_client.put(
            f"/api/v1/policies/{created['id']}",
            json={
                "expected_updated_at": created["updated_at"],
                "rules": [{
                    "name": "always_fires",
                    "field": "fail_count_24h",
                    "operator": ">=",
                    "value": 0,
                    "weight": 1.0,
                    "score": 1.0,
                    "enabled": True,
                }],
            },
            headers=_auth(token),
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["is_active"] is False

        activated = pg_client.post(
            f"/api/v1/policies/{created['id']}/activate", headers=_auth(token))
        assert activated.status_code == 200, activated.text
        assert activated.json()["version"] == version

    def test_the_activated_policy_is_the_one_the_engine_uses(self, pg_client, engine):
        """The detection engine must pick up the activated policy."""
        token = self._token(pg_client, "f1_admin")
        created = pg_client.post("/api/v1/policies", json={
            "version": _version(),
            "name": "engine",
            "rules": VALID_RULES,
            "config": VALID_CONFIG,
        }, headers=_auth(token)).json()
        pg_client.post(f"/api/v1/policies/{created['id']}/activate", headers=_auth(token))

        health = pg_client.get("/api/v1/internal/health")
        assert health.status_code == 200
        assert health.json()["active_policy"] == created["version"]

    def test_a_new_policy_does_not_disturb_the_previous_one(self, pg_client, engine):
        """Activating a successor leaves the old policy row intact."""
        token = self._token(pg_client, "f1_admin")
        first = pg_client.post("/api/v1/policies", json={
            "version": _version(),
            "name": "first",
            "rules": VALID_RULES,
            "config": VALID_CONFIG,
        }, headers=_auth(token)).json()
        pg_client.post(f"/api/v1/policies/{first['id']}/activate", headers=_auth(token))

        second = pg_client.post("/api/v1/policies", json={
            "version": _version(),
            "name": "second",
            "rules": VALID_RULES,
            "config": VALID_CONFIG,
        }, headers=_auth(token)).json()
        pg_client.post(f"/api/v1/policies/{second['id']}/activate", headers=_auth(token))

        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT version, is_active FROM policies WHERE id IN (:a, :b)"
            ), {"a": first["id"], "b": second["id"]}).fetchall()
        by_version = {row[0]: row[1] for row in rows}
        assert by_version[first["version"]] is False
        assert by_version[second["version"]] is True

    def test_only_one_policy_is_active_at_a_time(self, pg_client, engine):
        """The database-level single-active invariant still holds."""
        token = self._token(pg_client, "f1_admin")
        for _ in range(3):
            created = pg_client.post("/api/v1/policies", json={
                "version": _version(),
                "name": "single",
                "rules": VALID_RULES,
                "config": VALID_CONFIG,
            }, headers=_auth(token)).json()
            pg_client.post(f"/api/v1/policies/{created['id']}/activate", headers=_auth(token))

        with engine.connect() as conn:
            active = conn.execute(
                text("SELECT count(*) FROM policies WHERE is_active")
            ).scalar_one()
        assert active == 1


# ---------------------------------------------------------------------------
# E. Historical assessments are immutable
# ---------------------------------------------------------------------------

class TestHistoricalAssessmentsAreNotRewritten(_PolicyTestBase):
    """A policy edit must never change an assessment that already exists."""

    def test_an_existing_assessment_is_untouched_by_a_later_policy_write(self, pg_client, engine):
        token = self._token(pg_client, "f1_admin")
        policy = pg_client.post("/api/v1/policies", json={
            "version": _version(),
            "name": "history",
            "rules": VALID_RULES,
            "config": VALID_CONFIG,
        }, headers=_auth(token)).json()
        pg_client.post(f"/api/v1/policies/{policy['id']}/activate", headers=_auth(token))

        # A login attempt scored against the active policy.
        attempt_id = str(uuid.uuid4())
        event_id = str(uuid.uuid4())
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO login_attempts (id, event_id, username_attempted, outcome, "
                "created_at) VALUES (:id, :e, 'history-user', 'success', now())"
            ), {"id": attempt_id, "e": event_id})
            conn.execute(text(
                "INSERT INTO risk_assessments (id, login_attempt_id, policy_id, rule_score, "
                "combined_score, ml_status, risk_level, decision, rule_hits, created_at) "
                "VALUES (:id, :a, :p, 0.5, 0.5, 'unavailable', 'medium', 'allow', "
                "'[{\"rule_name\": \"unusual_hour\"}]'::jsonb, now())"
            ), {"id": str(uuid.uuid4()), "a": attempt_id, "p": policy["id"]})

        with engine.connect() as conn:
            before = conn.execute(text(
                "SELECT rule_score, combined_score, risk_level, decision, rule_hits, policy_id "
                "FROM risk_assessments WHERE login_attempt_id = :a"
            ), {"a": attempt_id}).fetchone()

        # A NEW policy is created and activated; the old assessment must
        # not be rewritten.
        successor = pg_client.post("/api/v1/policies", json={
            "version": _version(),
            "name": "successor",
            "rules": VALID_RULES,
            "config": VALID_CONFIG,
        }, headers=_auth(token)).json()
        pg_client.post(f"/api/v1/policies/{successor['id']}/activate", headers=_auth(token))

        with engine.connect() as conn:
            after = conn.execute(text(
                "SELECT rule_score, combined_score, risk_level, decision, rule_hits, policy_id "
                "FROM risk_assessments WHERE login_attempt_id = :a"
            ), {"a": attempt_id}).fetchone()

        assert after == before
        assert str(after[5]) == policy["id"]

    def test_the_login_attempt_history_is_untouched(self, pg_client, engine):
        token = self._token(pg_client, "f1_admin")
        attempt_id = str(uuid.uuid4())
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO login_attempts (id, event_id, username_attempted, outcome, "
                "created_at) VALUES (:id, :e, 'history-user', 'failure', now())"
            ), {"id": attempt_id, "e": str(uuid.uuid4())})

        created = pg_client.post("/api/v1/policies", json={
            "version": _version(),
            "name": "history",
            "rules": VALID_RULES,
            "config": VALID_CONFIG,
        }, headers=_auth(token)).json()
        pg_client.put(
            f"/api/v1/policies/{created['id']}",
            json={"expected_updated_at": created["updated_at"], "name": "renamed"},
            headers=_auth(token),
        )

        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, outcome, username_attempted FROM login_attempts WHERE id = :a"
            ), {"a": attempt_id}).fetchall()
        assert len(rows) == 1
        assert rows[0][1] == "failure"


# ---------------------------------------------------------------------------
# F. Bounded-context isolation
# ---------------------------------------------------------------------------

class TestBoundedContextIsolation(_PolicyTestBase):
    """A policy write must not touch the Core or the ML database."""

    def test_a_create_does_not_write_to_the_core_tables(self, pg_client, engine):
        token = self._token(pg_client, "f1_admin")
        before = self._counts(engine, ("users", "sessions", "audit_logs"))
        pg_client.post("/api/v1/policies", json={
            "version": _version(),
            "name": "isolation",
            "rules": VALID_RULES,
            "config": VALID_CONFIG,
        }, headers=_auth(token))
        after = self._counts(engine, ("users", "sessions", "audit_logs"))
        assert after == before

    def test_an_edit_does_not_write_to_the_core_tables(self, pg_client, engine):
        token = self._token(pg_client, "f1_admin")
        created = pg_client.post("/api/v1/policies", json={
            "version": _version(),
            "name": "isolation",
            "rules": VALID_RULES,
            "config": VALID_CONFIG,
        }, headers=_auth(token)).json()
        before = self._counts(engine, ("users", "sessions", "audit_logs"))
        pg_client.put(
            f"/api/v1/policies/{created['id']}",
            json={"expected_updated_at": created["updated_at"], "name": "renamed"},
            headers=_auth(token),
        )
        after = self._counts(engine, ("users", "sessions", "audit_logs"))
        assert after == before

    def test_a_create_does_not_write_to_the_ml_tables(self, pg_client, engine):
        token = self._token(pg_client, "f1_admin")
        before = self._counts(engine, ("model_versions", "inference_logs"))
        pg_client.post("/api/v1/policies", json={
            "version": _version(),
            "name": "isolation",
            "rules": VALID_RULES,
            "config": VALID_CONFIG,
        }, headers=_auth(token))
        after = self._counts(engine, ("model_versions", "inference_logs"))
        assert after == before

    def test_the_policy_row_lives_in_the_detection_context(self, pg_client, engine):
        token = self._token(pg_client, "f1_admin")
        created = pg_client.post("/api/v1/policies", json={
            "version": _version(),
            "name": "isolation",
            "rules": VALID_RULES,
            "config": VALID_CONFIG,
        }, headers=_auth(token)).json()
        with engine.connect() as conn:
            found = conn.execute(
                text("SELECT count(*) FROM policies WHERE id = :id"),
                {"id": created["id"]},
            ).scalar_one()
        assert found == 1

    @staticmethod
    def _counts(engine, tables) -> dict:
        counts = {}
        with engine.connect() as conn:
            for table in tables:
                counts[table] = conn.execute(
                    text(f"SELECT count(*) FROM {table}")
                ).scalar_one()
        return counts


# ---------------------------------------------------------------------------
# G. Concurrency
# ---------------------------------------------------------------------------

class TestConcurrentPolicyWrites(_PolicyTestBase):
    """Two concurrent writers must not both win."""

    def test_two_concurrent_edits_of_the_same_draft_yield_one_winner(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        created = pg_client.post("/api/v1/policies", json={
            "version": _version(),
            "name": "race",
            "rules": VALID_RULES,
            "config": VALID_CONFIG,
        }, headers=_auth(token)).json()

        def _edit(name):
            response = pg_client.put(
                f"/api/v1/policies/{created['id']}",
                json={"expected_updated_at": created["updated_at"], "name": name},
                headers=_auth(token),
            )
            return response.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = sorted(pool.map(_edit, ("writer-a", "writer-b")))

        assert codes.count(200) == 1, f"both writers succeeded: {codes}"
        assert codes.count(409) == 1, f"the loser was not told about the conflict: {codes}"

    def test_two_concurrent_creates_of_the_same_version_yield_one_winner(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        version = _version()

        def _create():
            response = pg_client.post("/api/v1/policies", json={
                "version": version,
                "name": "race",
                "rules": VALID_RULES,
                "config": VALID_CONFIG,
            }, headers=_auth(token))
            return response.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = sorted(pool.map(lambda _i: _create(), range(2)))

        assert codes.count(201) == 1, f"both creates succeeded: {codes}"
        assert codes.count(409) == 1, f"the loser was not told about the conflict: {codes}"


# ---------------------------------------------------------------------------
# H. The listing and activation contracts are unchanged
# ---------------------------------------------------------------------------

class TestExistingContractsArePreserved(_PolicyTestBase):
    """F-1 must not change the listing or activation behaviour."""

    def test_the_listing_still_returns_the_same_shape(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        response = pg_client.get("/api/v1/policies", headers=_auth(token))
        assert response.status_code == 200
        assert isinstance(response.json(), list)
        for row in response.json():
            assert set(row) == {
                "id", "version", "name", "description", "rule_count",
                "is_active", "created_at", "activated_at",
            }

    def test_the_activation_response_is_unchanged(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        created = pg_client.post("/api/v1/policies", json={
            "version": _version(),
            "name": "activation",
            "rules": VALID_RULES,
            "config": VALID_CONFIG,
        }, headers=_auth(token)).json()
        response = pg_client.post(
            f"/api/v1/policies/{created['id']}/activate", headers=_auth(token))
        assert response.status_code == 200
        assert set(response.json()) == {"status", "version"}
        assert response.json()["status"] == "activated"

    def test_the_activation_of_an_invalid_policy_is_still_a_400(self, pg_client, engine):
        """The activation endpoint keeps its own validation contract."""
        token = self._token(pg_client, "f1_admin")
        policy_id = str(uuid.uuid4())
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO policies (id, version, name, rules, config, is_active, created_at) "
                "VALUES (:id, :v, 'broken', '[{\"name\": \"x\"}]'::jsonb, '{}'::jsonb, FALSE, now())"
            ), {"id": policy_id, "v": _version()})
        response = pg_client.post(
            f"/api/v1/policies/{policy_id}/activate", headers=_auth(token))
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# I. The policy detail endpoint
# ---------------------------------------------------------------------------

class TestPolicyDetail(_PolicyTestBase):
    """``GET /api/v1/policies/{policy_id}``.

    The detail endpoint exists so a client can read the current state of a
    policy and obtain the ``updated_at`` token the edit endpoint requires.
    It is a read-only endpoint: it does not extend the policy lifecycle and
    it never writes.
    """

    def _create(self, client, token, **overrides):
        body = {
            "version": _version(),
            "name": "F-1 detail policy",
            "description": "created by the F-1 detail tests",
            "rules": VALID_RULES,
            "config": VALID_CONFIG,
        }
        body.update(overrides)
        return client.post("/api/v1/policies", json=body, headers=_auth(token))

    # -- 1. the admin reads the full detail --------------------------------

    def test_an_admin_reads_the_full_policy_detail(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        created = self._create(pg_client, token).json()

        response = pg_client.get(
            f"/api/v1/policies/{created['id']}", headers=_auth(token))
        assert response.status_code == 200, response.text
        payload = response.json()

        assert set(payload) == {
            "id", "version", "name", "description", "rules", "config",
            "is_active", "created_by", "created_at", "updated_at",
            "activated_at", "deactivated_at",
        }
        assert payload["id"] == created["id"]
        assert payload["version"] == created["version"]
        assert payload["name"] == "F-1 detail policy"
        assert payload["description"] == "created by the F-1 detail tests"
        assert payload["rules"] == VALID_RULES
        assert payload["config"] == VALID_CONFIG
        assert payload["is_active"] is False
        assert payload["created_by"] == created["created_by"]
        assert payload["created_at"] == created["created_at"]
        assert payload["updated_at"] == created["updated_at"]
        assert payload["activated_at"] is None
        assert payload["deactivated_at"] is None

    # -- 2. the manager may read but not edit ------------------------------

    def test_a_manager_can_read_the_detail_but_cannot_edit(self, pg_client):
        admin = self._token(pg_client, "f1_admin")
        created = self._create(pg_client, admin).json()
        manager = self._token(pg_client, "f1_manager")

        read = pg_client.get(
            f"/api/v1/policies/{created['id']}", headers=_auth(manager))
        assert read.status_code == 200
        assert read.json()["version"] == created["version"]

        edit = pg_client.put(
            f"/api/v1/policies/{created['id']}",
            json={"expected_updated_at": created["updated_at"], "name": "nope"},
            headers=_auth(manager),
        )
        assert edit.status_code == 403

    # -- 3. USER / SOC_ANALYST have no access ------------------------------

    def test_a_user_cannot_read_the_detail(self, pg_client):
        admin = self._token(pg_client, "f1_admin")
        created = self._create(pg_client, admin).json()
        token = self._token(pg_client, "f1_user")
        response = pg_client.get(
            f"/api/v1/policies/{created['id']}", headers=_auth(token))
        assert response.status_code == 403

    def test_a_soc_analyst_cannot_read_the_detail(self, pg_client):
        admin = self._token(pg_client, "f1_admin")
        created = self._create(pg_client, admin).json()
        token = self._token(pg_client, "f1_analyst")
        response = pg_client.get(
            f"/api/v1/policies/{created['id']}", headers=_auth(token))
        assert response.status_code == 403

    def test_an_unauthenticated_read_is_401(self, pg_client):
        created = self._create(
            pg_client, self._token(pg_client, "f1_admin")).json()
        response = pg_client.get(f"/api/v1/policies/{created['id']}")
        assert response.status_code == 401

    # -- 4. an unknown policy is a 404 -------------------------------------

    def test_an_unknown_policy_id_is_a_404(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        response = pg_client.get(
            f"/api/v1/policies/{uuid.uuid4()}", headers=_auth(token))
        assert response.status_code == 404

    # -- 5. create -> GET detail -> edit with the returned token -----------

    def test_the_detail_supplies_the_token_the_edit_needs(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        created = self._create(pg_client, token).json()

        detail = pg_client.get(
            f"/api/v1/policies/{created['id']}", headers=_auth(token)).json()

        edited = pg_client.put(
            f"/api/v1/policies/{created['id']}",
            json={
                "expected_updated_at": detail["updated_at"],
                "name": "edited from the detail",
            },
            headers=_auth(token),
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["name"] == "edited from the detail"

    # -- 6. a stale token is a 409 -----------------------------------------

    def test_a_stale_token_from_the_detail_is_a_conflict(self, pg_client):
        token = self._token(pg_client, "f1_admin")
        created = self._create(pg_client, token).json()

        stale = pg_client.get(
            f"/api/v1/policies/{created['id']}", headers=_auth(token)).json()

        # Somebody else writes first.
        first = pg_client.put(
            f"/api/v1/policies/{created['id']}",
            json={"expected_updated_at": stale["updated_at"], "name": "first"},
            headers=_auth(token),
        )
        assert first.status_code == 200

        # The client still holds the OLD token: the write must be refused.
        second = pg_client.put(
            f"/api/v1/policies/{created['id']}",
            json={"expected_updated_at": stale["updated_at"], "name": "second"},
            headers=_auth(token),
        )
        assert second.status_code == 409
        assert "modified by someone else" in second.json()["detail"]["message"]

    # -- 7. the timestamp survives the round trip --------------------------

    def test_the_timestamp_keeps_its_full_precision(self, pg_client):
        """The detail's ``updated_at`` must round-trip without losing precision.

        A truncated token would be rejected by the edit endpoint for a
        reason the client cannot see, so the value the detail returns has
        to survive the JSON round trip unchanged.
        """
        token = self._token(pg_client, "f1_admin")
        created = self._create(pg_client, token).json()

        raw = pg_client.get(
            f"/api/v1/policies/{created['id']}", headers=_auth(token)).text
        payload = json.loads(raw)
        stamp = payload["updated_at"]

        # Microseconds are present in the wire format, not truncated.
        assert "." in stamp, f"the timestamp lost its fractional part: {stamp!r}"
        assert len(stamp.split(".")[1].rstrip("Z")) >= 6, (
            f"the timestamp lost its microseconds: {stamp!r}")

        # The parsed instant equals the one the create endpoint returned.
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        original = datetime.fromisoformat(
            created["updated_at"].replace("Z", "+00:00"))
        assert parsed == original
        assert parsed.tzinfo is not None

        # And the value is usable as the concurrency token verbatim.
        edited = pg_client.put(
            f"/api/v1/policies/{created['id']}",
            json={"expected_updated_at": stamp, "name": "precision"},
            headers=_auth(token),
        )
        assert edited.status_code == 200, edited.text

    # -- 8. reading a previously active policy changes nothing ------------

    def test_reading_a_previously_active_policy_changes_nothing(self, pg_client, engine):
        """A read must not rewrite the policy, its history or the database."""
        token = self._token(pg_client, "f1_admin")
        created = self._create(pg_client, token).json()

        attempt_id = str(uuid.uuid4())
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO login_attempts (id, event_id, username_attempted, outcome, "
                "created_at) VALUES (:id, :e, 'detail-user', 'success', now())"
            ), {"id": attempt_id, "e": str(uuid.uuid4())})
            conn.execute(text(
                "INSERT INTO risk_assessments (id, login_attempt_id, policy_id, rule_score, "
                "combined_score, ml_status, risk_level, decision, rule_hits, created_at) "
                "VALUES (:id, :a, :p, 0.5, 0.5, 'unavailable', 'medium', 'allow', "
                "'[{\"rule_name\": \"unusual_hour\"}]'::jsonb, now())"
            ), {"id": str(uuid.uuid4()), "a": attempt_id, "p": created["id"]})

        pg_client.post(
            f"/api/v1/policies/{created['id']}/activate", headers=_auth(token))

        def _snapshot():
            with engine.connect() as conn:
                policy_row = conn.execute(text(
                    "SELECT version, rules, config, is_active, activated_at, deactivated_at, "
                    "updated_at FROM policies WHERE id = :id"
                ), {"id": created["id"]}).fetchone()
                history = conn.execute(text(
                    "SELECT rule_score, combined_score, risk_level, decision, policy_id "
                    "FROM risk_assessments WHERE login_attempt_id = :a"
                ), {"a": attempt_id}).fetchone()
                attempts = conn.execute(text(
                    "SELECT id, outcome, username_attempted FROM login_attempts WHERE id = :a"
                ), {"a": attempt_id}).fetchone()
            return policy_row, history, attempts

        before = _snapshot()

        response = pg_client.get(
            f"/api/v1/policies/{created['id']}", headers=_auth(token))
        assert response.status_code == 200
        payload = response.json()
        # The policy HAS been active, so the detail must say so.
        assert payload["is_active"] is True
        assert payload["activated_at"] is not None

        after = _snapshot()
        assert after[0] == before[0], "the policy row was rewritten by a read"
        assert after[1] == before[1], "a historical assessment was rewritten"
        assert after[2] == before[2], "the login attempt history was rewritten"

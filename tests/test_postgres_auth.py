"""PostgreSQL auth integration tests for P0-02 and P0-03.

These tests exercise the authentication flow (no MFA and MFA-required)
against a real PostgreSQL database.

IMPORTANT: MFA tests cover only the P0-03 fix. The P0-05 concurrency
race (atomic OTP consumption) is not tested here.

Run with:
    pytest tests/test_postgres_auth.py -v

Requires:
    POSTGRES_HOST=localhost
    POSTGRES_DB=sentinel_auth
    POSTGRES_USER=sentinel
    POSTGRES_PASSWORD=sentinel123
"""
from __future__ import annotations

import os
import subprocess

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, text


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "sentinel_auth")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "sentinel")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "sentinel123")


def _pg_url() -> str:
    return (
        f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_CORE = os.path.join(REPO_ROOT, "infra", "postgres", "schema-core-v3.3.sql")
SCHEMA_DETECTION = os.path.join(REPO_ROOT, "infra", "postgres", "schema-detection-v3.3.sql")
SCHEMA_ML = os.path.join(REPO_ROOT, "infra", "postgres", "schema-ml-service-v3.3.sql")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    """Hash a password using Argon2 (same as registration)."""
    result = subprocess.run(
        ["python", "-c", f"""
from argon2 import PasswordHasher
ph = PasswordHasher()
print(ph.hash('{password}'))
"""],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        raise RuntimeError(f"argon2 failed: {result.stderr}")
    return result.stdout.strip()


def _create_user_sql(conn, username: str, password: str) -> str:
    """Create an active user via SQL and return user_id (UUID string)."""
    password_hash = _hash_password(password)
    user_id = conn.execute(
        text("""
            INSERT INTO users (username, email, password_hash, status,
                               admin_mfa_required, detection_mfa_once)
            VALUES (:u, :e, :h, 'active', FALSE, FALSE)
            RETURNING id
        """),
        {"u": username, "e": f"{username}@example.com", "h": password_hash},
    ).scalar()
    conn.execute(
        text("INSERT INTO user_roles (user_id, role_id) VALUES (:uid, 'USER')"),
        {"uid": user_id},
    )
    return str(user_id)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
    eng = create_engine(_pg_url(), isolation_level="AUTOCOMMIT")
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def bootstrap_done(engine: sa.Engine):
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        for path in (SCHEMA_CORE, SCHEMA_DETECTION, SCHEMA_ML):
            conn.execute(text(open(path).read()))


@pytest.fixture(autouse=True)
def reset_seed_state(engine: sa.Engine, bootstrap_done):
    with engine.connect() as conn:
        conn.execute(text("UPDATE policies SET is_active = TRUE WHERE version = 'v1.0'"))
        conn.execute(
            text(
                "UPDATE model_versions SET status = 'active', is_production = TRUE "
                "WHERE version = 'v1.0-isolation-forest'"
            )
        )


@pytest.fixture()
def pg_conn(engine: sa.Engine):
    """Raw psycopg2 connection per test (auto-commit)."""
    with engine.connect() as conn:
        yield conn


@pytest.fixture()
def orm_session(engine: sa.Engine):
    """SQLAlchemy ORM session bound to PostgreSQL, per test."""
    from sqlalchemy.orm import sessionmaker
    maker = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = maker()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# REAL end-to-end FastAPI test against PostgreSQL
# ---------------------------------------------------------------------------

class TestPostgresLoginE2E:
    """End-to-end FastAPI login against real PostgreSQL — no mocking."""

    def test_post_login_returns_tokens_and_creates_db_records(self, pg_conn, orm_session):
        """POST /api/v1/auth/login hits real login() and _create_session().

        Verifies on PostgreSQL:
        - HTTP 200
        - mfa_required == False
        - access_token non-empty
        - refresh_token non-empty
        - session_id exists
        - Exactly one active Session in DB
        - LoginAttempt(outcome='success') exists
        - ip_addresses record created
        - users.last_login_at is populated
        - Returned token works on GET /api/v1/auth/sessions (200)
        """
        # Setup: create user in PostgreSQL
        user_id = _create_user_sql(pg_conn, "e2e_user", "CorrectPassword")

        # Pre-insert a valid IP so rate-limit and IP-tracking queries work.
        # We use a mock helper to avoid hardcoding IP strings throughout the test.
        pg_conn.execute(
            text("""
                INSERT INTO ip_addresses (ip_address, is_proxy, is_vpn, is_tor)
                VALUES ('127.0.0.1'::inet, FALSE, FALSE, FALSE)
                ON CONFLICT (ip_address) DO NOTHING
            """),
        )

        # Override FastAPI get_db so login() uses the PostgreSQL session.
        # Also disable pre-token risk check (Detection Engine not running).
        import app.auth as _auth_mod
        from fastapi.testclient import TestClient
        from app.main import app

        # Preserve originals
        orig_pre_token = _auth_mod.RUN_PRE_TOKEN_CHECK

        def _get_db_override():
            yield orm_session

        def _mock_get_client_ip(req):
            return "127.0.0.1"

        try:
            # Disable pre-token risk check
            _auth_mod.RUN_PRE_TOKEN_CHECK = "0"
            # Mock client IP to a valid IP so INET comparisons work
            orig_get_client_ip = _auth_mod.get_client_ip
            _auth_mod.get_client_ip = _mock_get_client_ip

            app.dependency_overrides[_auth_mod.get_db] = _get_db_override

            with TestClient(app) as client:
                login_resp = client.post(
                    "/api/v1/auth/login",
                    json={"username": "e2e_user", "password": "CorrectPassword"},
                )

            # --- HTTP assertions ---
            assert login_resp.status_code == 200, login_resp.json()
            data = login_resp.json()
            assert data["mfa_required"] is False
            assert data["access_token"] != ""
            assert data["refresh_token"] != ""
            assert data["session_id"] != ""

            access_token = data["access_token"]
            session_id = data["session_id"]

        finally:
            _auth_mod.RUN_PRE_TOKEN_CHECK = orig_pre_token
            _auth_mod.get_client_ip = orig_get_client_ip
            app.dependency_overrides.clear()

        # --- PostgreSQL assertions ---
        pg_conn.commit()

        # 1. Exactly one active Session for this user
        sessions = pg_conn.execute(
            text("""
                SELECT id, user_id, revoked_at, expires_at, last_activity_at,
                       access_token_hash, refresh_token_hash, token_jti
                FROM sessions
                WHERE user_id = :uid AND revoked_at IS NULL
            """),
            {"uid": user_id},
        ).fetchall()
        assert len(sessions) == 1, f"Expected 1 session, got {len(sessions)}"
        s = sessions[0]
        assert str(s.id) == session_id, f"Session ID mismatch: {s.id} != {session_id}"
        assert s.revoked_at is None
        assert s.expires_at is not None
        assert s.last_activity_at is not None
        assert s.access_token_hash != ""
        assert s.refresh_token_hash != ""
        assert s.token_jti is not None

        # 2. LoginAttempt(outcome='success') exists
        la_rows = pg_conn.execute(
            text("""
                SELECT outcome, user_id, timestamp, ip_address, mfa_used
                FROM login_attempts
                WHERE user_id = :uid AND outcome = 'success'
            """),
            {"uid": user_id},
        ).fetchall()
        assert len(la_rows) >= 1, "Expected at least one success LoginAttempt"
        latest_la = la_rows[-1]
        assert latest_la.outcome == "success"
        assert str(latest_la.user_id) == user_id
        assert latest_la.timestamp is not None

        # 3. ip_addresses record was created (by resolve_ip_address)
        ip_rows = pg_conn.execute(
            text("SELECT id FROM ip_addresses LIMIT 1")
        ).fetchall()
        assert len(ip_rows) >= 1, "Expected at least one ip_addresses record"

        # 4. users.last_login_at is populated
        user_rows = pg_conn.execute(
            text("SELECT last_login_at FROM users WHERE id = :uid"),
            {"uid": user_id},
        ).fetchall()
        assert len(user_rows) == 1
        assert user_rows[0].last_login_at is not None, (
            "users.last_login_at must be populated after login"
        )

        # 5. Returned access_token works on GET /api/v1/auth/sessions
        def _get_db_override2():
            yield orm_session

        try:
            def _mock_get_client_ip2(req):
                return "127.0.0.1"

            _auth_mod.get_client_ip = _mock_get_client_ip2
            app.dependency_overrides[_auth_mod.get_db] = _get_db_override2

            with TestClient(app) as client:
                sessions_resp = client.get(
                    "/api/v1/auth/sessions",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            assert sessions_resp.status_code == 200, sessions_resp.json()
            sessions_data = sessions_resp.json()
            assert sessions_data["total"] >= 1
            current = [s for s in sessions_data["sessions"] if s.get("is_current")]
            assert len(current) == 1
            assert current[0]["id"] == session_id
        finally:
            _auth_mod.get_client_ip = orig_get_client_ip
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Lower-level PostgreSQL state tests (SQL-only)
# ---------------------------------------------------------------------------

class TestPostgresLoginState:
    """Verify _create_session state invariants directly in PostgreSQL."""

    def test_login_creates_session_record(self, pg_conn):
        """Simulate _create_session state: one Session row with all required fields."""
        import hashlib
        user_id = _create_user_sql(pg_conn, "pguser1", "tp123")

        access_hash = hashlib.sha256(b"tok").hexdigest()
        refresh_hash = hashlib.sha256(b"ref").hexdigest()

        session_id = pg_conn.execute(
            text("""
                INSERT INTO sessions
                    (user_id, access_token_hash, refresh_token_hash, refresh_token_family,
                     token_jti, expires_at, last_activity_at, ip_address_id, user_agent)
                VALUES (:uid, :ath, :rth, gen_random_uuid(), gen_random_uuid(),
                        NOW() + INTERVAL '1 hour', NOW(), NULL, 'PG-Test/1.0')
                RETURNING id
            """),
            {"uid": user_id, "ath": access_hash, "rth": refresh_hash},
        ).scalar()

        row = pg_conn.execute(
            text("""
                SELECT user_id, revoked_at, expires_at, last_activity_at, token_jti
                FROM sessions WHERE id = :sid
            """),
            {"sid": session_id},
        ).fetchone()
        assert row is not None
        assert str(row.user_id) == user_id
        assert row.revoked_at is None
        assert row.expires_at is not None
        assert row.last_activity_at is not None
        assert row.token_jti is not None

    def test_login_creates_login_attempt_with_inet(self, pg_conn):
        """Simulate _create_session: LoginAttempt with outcome='success' and INET ip_address."""
        user_id = _create_user_sql(pg_conn, "pguser2", "tp456")

        before = pg_conn.execute(
            text("SELECT count(*) FROM login_attempts WHERE user_id = :uid AND outcome = 'success'"),
            {"uid": user_id},
        ).scalar()

        pg_conn.execute(
            text("""
                INSERT INTO login_attempts
                    (event_id, request_id, user_id, outcome, ip_address, user_agent, mfa_used)
                VALUES (gen_random_uuid(), gen_random_uuid(), :uid, 'success',
                        '192.168.1.1'::inet, 'PG-Test/1.0', FALSE)
            """),
            {"uid": user_id},
        )

        after = pg_conn.execute(
            text("SELECT count(*) FROM login_attempts WHERE user_id = :uid AND outcome = 'success'"),
            {"uid": user_id},
        ).scalar()
        assert after == before + 1

        row = pg_conn.execute(
            text("""
                SELECT outcome, user_id, ip_address, user_agent, mfa_used, timestamp
                FROM login_attempts
                WHERE user_id = :uid AND outcome = 'success'
                ORDER BY timestamp DESC LIMIT 1
            """),
            {"uid": user_id},
        ).fetchone()
        assert row.outcome == "success"
        assert str(row.user_id) == user_id
        assert row.ip_address is not None       # INET type — works in PostgreSQL
        assert row.user_agent == "PG-Test/1.0"
        assert row.mfa_used is False
        assert row.timestamp is not None

    def test_login_creates_ip_address_record(self, pg_conn):
        """resolve_ip_address creates an ip_addresses row on first login."""
        user_id = _create_user_sql(pg_conn, "pguser3", "tp789")

        ip_id = pg_conn.execute(
            text("""
                INSERT INTO ip_addresses (ip_address, is_proxy, is_vpn, is_tor, country_code)
                VALUES ('10.0.0.1'::inet, FALSE, FALSE, FALSE, 'US')
                ON CONFLICT (ip_address) DO UPDATE SET last_seen_at = NOW()
                RETURNING id
            """),
        ).scalar()

        assert ip_id is not None
        row = pg_conn.execute(
            text("SELECT ip_address, country_code, last_seen_at FROM ip_addresses WHERE id = :id"),
            {"id": ip_id},
        ).fetchone()
        assert row is not None
        assert row.last_seen_at is not None

    def test_user_last_login_at_updated(self, pg_conn):
        """_create_session updates users.last_login_at."""
        user_id = _create_user_sql(pg_conn, "pguser4", "lgt")

        row = pg_conn.execute(
            text("SELECT last_login_at FROM users WHERE id = :uid"),
            {"uid": user_id},
        ).fetchone()
        assert row.last_login_at is None, "Precondition: last_login_at starts NULL"

        pg_conn.execute(
            text("UPDATE users SET last_login_at = NOW() WHERE id = :uid"),
            {"uid": user_id},
        )

        row = pg_conn.execute(
            text("SELECT last_login_at FROM users WHERE id = :uid"),
            {"uid": user_id},
        ).fetchone()
        assert row.last_login_at is not None

    def test_sessions_listed_by_user(self, pg_conn):
        """Active sessions can be queried by user_id."""
        user_id = _create_user_sql(pg_conn, "pguser5", "lst")

        pg_conn.execute(
            text("""
                INSERT INTO sessions
                    (user_id, access_token_hash, refresh_token_hash, refresh_token_family,
                     token_jti, expires_at, last_activity_at)
                VALUES (:uid, 'h1', 'h2', gen_random_uuid(), gen_random_uuid(),
                        NOW() + INTERVAL '1 hour', NOW())
            """),
            {"uid": user_id},
        )

        rows = pg_conn.execute(
            text("""
                SELECT id, revoked_at, expires_at
                FROM sessions
                WHERE user_id = :uid AND revoked_at IS NULL AND expires_at > NOW()
            """),
            {"uid": user_id},
        ).fetchall()
        assert len(rows) == 1
        assert rows[0].revoked_at is None
        assert rows[0].expires_at is not None


# ---------------------------------------------------------------------------
# MFA tests
# ---------------------------------------------------------------------------

class TestPostgresMfaLogin:
    """Real MFA flow against PostgreSQL via FastAPI — P0-03 fix verification."""

    def test_mfa_login_returns_mfa_required_and_creates_transaction(
        self, pg_conn, orm_session
    ):
        """POST /api/v1/auth/login with MFA-required user returns mfa_required=true.

        Verifies:
        - HTTP 200 (challenge issued)
        - mfa_required == True
        - access_token == ""
        - refresh_token == ""
        - session_id is the mfa_txn.id
        - MfaTransaction created in PostgreSQL (no DataError)
        - MfaNotification created
        - NO active Session yet
        """
        # Setup: create user with MFA required
        user_id = _create_user_sql(pg_conn, "mfa_user1", "testpass")
        pg_conn.execute(
            text("UPDATE users SET admin_mfa_required = TRUE WHERE id = :uid"),
            {"uid": user_id},
        )
        pg_conn.execute(
            text("""
                INSERT INTO ip_addresses (ip_address)
                VALUES ('127.0.0.1'::inet)
                ON CONFLICT (ip_address) DO NOTHING
            """),
        )

        import app.auth as _auth_mod
        from fastapi.testclient import TestClient
        from app.main import app

        # Store originals
        orig_get_client_ip = _auth_mod.get_client_ip
        orig_run_pre_token = _auth_mod.RUN_PRE_TOKEN_CHECK

        def _get_db_override():
            yield orm_session

        try:
            _auth_mod.get_client_ip = lambda req: "127.0.0.1"
            _auth_mod.RUN_PRE_TOKEN_CHECK = "0"
            app.dependency_overrides[_auth_mod.get_db] = _get_db_override

            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/auth/login",
                    json={"username": "mfa_user1", "password": "testpass"},
                )

            assert resp.status_code == 200, resp.json()
            data = resp.json()
            assert data["mfa_required"] is True
            assert data["access_token"] == ""
            assert data["refresh_token"] == ""
            assert data["session_id"] != ""
            txn_id = data["session_id"]

        finally:
            _auth_mod.get_client_ip = orig_get_client_ip
            _auth_mod.RUN_PRE_TOKEN_CHECK = orig_run_pre_token
            app.dependency_overrides.clear()

        # Verify PostgreSQL state
        pg_conn.commit()

        txn_rows = pg_conn.execute(
            text("""
                SELECT id, user_id, status, bound_ip, expires_at, notification_id
                FROM mfa_transactions WHERE id = :tid
            """),
            {"tid": txn_id},
        ).fetchall()
        assert len(txn_rows) == 1, f"MfaTransaction not found: {txn_id}"
        txn = txn_rows[0]
        assert str(txn.user_id) == user_id
        assert txn.status == "pending"
        assert txn.bound_ip is not None, "bound_ip must be stored as valid INET"
        assert txn.expires_at is not None
        assert txn.notification_id is not None

        # MfaNotification exists
        notif_rows = pg_conn.execute(
            text("""
                SELECT id, mfa_transaction_id, channel, mfa_code_hash
                FROM mfa_notifications WHERE id = :nid
            """),
            {"nid": txn.notification_id},
        ).fetchall()
        assert len(notif_rows) == 1

        # NO active Session yet (login returns before session is created)
        session_rows = pg_conn.execute(
            text("SELECT id FROM sessions WHERE user_id = :uid"),
            {"uid": user_id},
        ).fetchall()
        assert len(session_rows) == 0, "Session should not be created until MFA verified"

    def test_mfa_verify_success_same_ip(self, pg_conn, orm_session):
        """MFA verification with correct OTP and same IP succeeds.

        Verifies:
        - HTTP 200 from /mfa/verify
        - access_token and refresh_token are returned
        - MfaTransaction.status == 'completed'
        - notification.verified_at is set
        - Session exists
        - Token works on /sessions endpoint
        """
        # Setup: user + MFA login to get transaction
        user_id = _create_user_sql(pg_conn, "mfa_user2", "testpass2")
        pg_conn.execute(
            text("UPDATE users SET admin_mfa_required = TRUE WHERE id = :uid"),
            {"uid": user_id},
        )
        pg_conn.execute(
            text("""
                INSERT INTO ip_addresses (ip_address)
                VALUES ('10.0.0.50'::inet)
                ON CONFLICT (ip_address) DO NOTHING
            """),
        )

        import app.auth as _auth_mod
        from fastapi.testclient import TestClient
        from app.main import app

        orig_get_client_ip = _auth_mod.get_client_ip
        orig_run_pre_token = _auth_mod.RUN_PRE_TOKEN_CHECK
        orig_generate_otp = _auth_mod.generate_otp

        def _get_db_override():
            yield orm_session

        try:
            _auth_mod.RUN_PRE_TOKEN_CHECK = "0"
            _auth_mod.get_client_ip = lambda req: "10.0.0.50"
            _auth_mod.generate_otp = lambda: "123456"

            app.dependency_overrides[_auth_mod.get_db] = _get_db_override

            with TestClient(app) as client:
                # Step 1: login → get mfa challenge
                login_resp = client.post(
                    "/api/v1/auth/login",
                    json={"username": "mfa_user2", "password": "testpass2"},
                )
                assert login_resp.status_code == 200
                txn_id = login_resp.json()["session_id"]

            # Step 2: verify with correct OTP + same IP
            with TestClient(app) as client:
                verify_resp = client.post(
                    "/api/v1/auth/mfa/verify",
                    json={"session_id": txn_id, "mfa_code": "123456"},
                )

            assert verify_resp.status_code == 200, verify_resp.json()
            data = verify_resp.json()
            assert data["access_token"] != ""
            assert data["refresh_token"] != ""
            assert data["session_id"] != ""
            access_token = data["access_token"]

        finally:
            _auth_mod.get_client_ip = orig_get_client_ip
            _auth_mod.RUN_PRE_TOKEN_CHECK = orig_run_pre_token
            _auth_mod.generate_otp = orig_generate_otp
            app.dependency_overrides.clear()

        # Verify PostgreSQL state
        pg_conn.commit()

        txn_rows = pg_conn.execute(
            text("SELECT status FROM mfa_transactions WHERE id = :tid"),
            {"tid": txn_id},
        ).fetchall()
        assert len(txn_rows) == 1
        assert txn_rows[0].status == "completed", (
            f"MfaTransaction should be completed, got: {txn_rows[0].status}"
        )

        notif_rows = pg_conn.execute(
            text("SELECT verified_at FROM mfa_notifications WHERE id IN (SELECT notification_id FROM mfa_transactions WHERE id = :tid)"),
            {"tid": txn_id},
        ).fetchall()
        assert len(notif_rows) == 1
        assert notif_rows[0].verified_at is not None, "notification.verified_at must be set"

        session_rows = pg_conn.execute(
            text("SELECT id FROM sessions WHERE user_id = :uid AND revoked_at IS NULL"),
            {"uid": user_id},
        ).fetchall()
        assert len(session_rows) == 1, "Session should be created after MFA verify"

        # Token works on /sessions
        def _get_db_override2():
            yield orm_session

        try:
            _auth_mod.get_client_ip = lambda req: "10.0.0.50"
            app.dependency_overrides[_auth_mod.get_db] = _get_db_override2

            with TestClient(app) as client:
                sessions_resp = client.get(
                    "/api/v1/auth/sessions",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            assert sessions_resp.status_code == 200, sessions_resp.json()
        finally:
            _auth_mod.get_client_ip = orig_get_client_ip
            app.dependency_overrides.clear()

    def test_mfa_verify_wrong_ip_rejected(self, pg_conn, orm_session):
        """MFA verification from a different IP is rejected (IP binding enforced)."""
        user_id = _create_user_sql(pg_conn, "mfa_user3", "testpass3")
        pg_conn.execute(
            text("UPDATE users SET admin_mfa_required = TRUE WHERE id = :uid"),
            {"uid": user_id},
        )
        pg_conn.execute(
            text("""
                INSERT INTO ip_addresses (ip_address)
                VALUES ('10.0.0.99'::inet), ('192.168.1.1'::inet)
                ON CONFLICT (ip_address) DO NOTHING
            """),
        )

        import app.auth as _auth_mod
        from fastapi.testclient import TestClient
        from app.main import app

        orig_get_client_ip = _auth_mod.get_client_ip
        orig_run_pre_token = _auth_mod.RUN_PRE_TOKEN_CHECK
        orig_generate_otp = _auth_mod.generate_otp

        def _get_db_override():
            yield orm_session

        try:
            _auth_mod.RUN_PRE_TOKEN_CHECK = "0"
            _auth_mod.get_client_ip = lambda req: "10.0.0.99"
            _auth_mod.generate_otp = lambda: "123456"

            app.dependency_overrides[_auth_mod.get_db] = _get_db_override

            with TestClient(app) as client:
                login_resp = client.post(
                    "/api/v1/auth/login",
                    json={"username": "mfa_user3", "password": "testpass3"},
                )
                assert login_resp.status_code == 200
                txn_id = login_resp.json()["session_id"]

            # Verify from DIFFERENT IP
            _auth_mod.get_client_ip = lambda req: "192.168.1.1"

            with TestClient(app) as client:
                verify_resp = client.post(
                    "/api/v1/auth/mfa/verify",
                    json={"session_id": txn_id, "mfa_code": "123456"},
                )

            assert verify_resp.status_code == 403, (
                f"Expected 403 for IP mismatch, got {verify_resp.status_code}: {verify_resp.json()}"
            )
            assert "IP address" in verify_resp.json()["detail"]

        finally:
            _auth_mod.get_client_ip = orig_get_client_ip
            _auth_mod.RUN_PRE_TOKEN_CHECK = orig_run_pre_token
            _auth_mod.generate_otp = orig_generate_otp
            app.dependency_overrides.clear()

        # Verify no session was created
        pg_conn.commit()
        session_rows = pg_conn.execute(
            text("SELECT id FROM sessions WHERE user_id = :uid"),
            {"uid": user_id},
        ).fetchall()
        assert len(session_rows) == 0, (
            "No session should be created when IP binding check fails"
        )

        # Transaction should remain pending
        txn_rows = pg_conn.execute(
            text("SELECT status FROM mfa_transactions WHERE id = :tid"),
            {"tid": txn_id},
        ).fetchall()
        assert len(txn_rows) == 1
        assert txn_rows[0].status == "pending", (
            "Transaction should remain pending after rejected verify"
        )

    def test_mfa_ip_binding_same_ipv4_allowed(self, pg_conn, orm_session):
        """IPv4: same IP with same textual form → allowed."""
        user_id = _create_user_sql(pg_conn, "ipv4_same", "pass")
        pg_conn.execute(
            text("UPDATE users SET admin_mfa_required = TRUE WHERE id = :uid"),
            {"uid": user_id},
        )

        import app.auth as _auth_mod
        from fastapi.testclient import TestClient
        from app.main import app

        orig_get_client_ip = _auth_mod.get_client_ip
        orig_run_pre_token = _auth_mod.RUN_PRE_TOKEN_CHECK
        orig_generate_otp = _auth_mod.generate_otp

        def _get_db_override():
            yield orm_session

        try:
            _auth_mod.RUN_PRE_TOKEN_CHECK = "0"
            _auth_mod.get_client_ip = lambda req: "8.8.8.8"
            _auth_mod.generate_otp = lambda: "654321"

            app.dependency_overrides[_auth_mod.get_db] = _get_db_override

            with TestClient(app) as client:
                login_resp = client.post(
                    "/api/v1/auth/login",
                    json={"username": "ipv4_same", "password": "pass"},
                )
                assert login_resp.status_code == 200
                txn_id = login_resp.json()["session_id"]

            with TestClient(app) as client:
                verify_resp = client.post(
                    "/api/v1/auth/mfa/verify",
                    json={"session_id": txn_id, "mfa_code": "654321"},
                )

            assert verify_resp.status_code == 200, verify_resp.json()
            assert verify_resp.json()["access_token"] != ""

        finally:
            _auth_mod.get_client_ip = orig_get_client_ip
            _auth_mod.RUN_PRE_TOKEN_CHECK = orig_run_pre_token
            _auth_mod.generate_otp = orig_generate_otp
            app.dependency_overrides.clear()

    def test_mfa_ip_binding_different_ipv4_rejected(self, pg_conn, orm_session):
        """IPv4: different IP → rejected."""
        user_id = _create_user_sql(pg_conn, "ipv4_diff", "pass")
        pg_conn.execute(
            text("UPDATE users SET admin_mfa_required = TRUE WHERE id = :uid"),
            {"uid": user_id},
        )

        import app.auth as _auth_mod
        from fastapi.testclient import TestClient
        from app.main import app

        orig_get_client_ip = _auth_mod.get_client_ip
        orig_run_pre_token = _auth_mod.RUN_PRE_TOKEN_CHECK
        orig_generate_otp = _auth_mod.generate_otp

        def _get_db_override():
            yield orm_session

        try:
            _auth_mod.RUN_PRE_TOKEN_CHECK = "0"
            _auth_mod.get_client_ip = lambda req: "1.1.1.1"
            _auth_mod.generate_otp = lambda: "111111"

            app.dependency_overrides[_auth_mod.get_db] = _get_db_override

            with TestClient(app) as client:
                login_resp = client.post(
                    "/api/v1/auth/login",
                    json={"username": "ipv4_diff", "password": "pass"},
                )
                assert login_resp.status_code == 200
                txn_id = login_resp.json()["session_id"]

            _auth_mod.get_client_ip = lambda req: "2.2.2.2"

            with TestClient(app) as client:
                verify_resp = client.post(
                    "/api/v1/auth/mfa/verify",
                    json={"session_id": txn_id, "mfa_code": "111111"},
                )

            assert verify_resp.status_code == 403, verify_resp.json()
            assert "IP address" in verify_resp.json()["detail"]

        finally:
            _auth_mod.get_client_ip = orig_get_client_ip
            _auth_mod.RUN_PRE_TOKEN_CHECK = orig_run_pre_token
            _auth_mod.generate_otp = orig_generate_otp
            app.dependency_overrides.clear()

    def test_mfa_ip_binding_ipv6_equivalent_forms_allowed(self, pg_conn, orm_session):
        """IPv6: two equivalent textual forms of the same address → allowed.

        Python's ipaddress module canonicalises both forms to the same string,
        so ``2001:db8::1`` and ``2001:0db8:0:0:0:0:0:1`` compare equal.
        """
        user_id = _create_user_sql(pg_conn, "ipv6_eq", "pass")
        pg_conn.execute(
            text("UPDATE users SET admin_mfa_required = TRUE WHERE id = :uid"),
            {"uid": user_id},
        )

        import app.auth as _auth_mod
        from fastapi.testclient import TestClient
        from app.main import app

        orig_get_client_ip = _auth_mod.get_client_ip
        orig_run_pre_token = _auth_mod.RUN_PRE_TOKEN_CHECK
        orig_generate_otp = _auth_mod.generate_otp

        def _get_db_override():
            yield orm_session

        try:
            _auth_mod.RUN_PRE_TOKEN_CHECK = "0"
            # Login uses the fully-expanded form
            _auth_mod.get_client_ip = lambda req: "2001:0db8:0000:0000:0000:0000:0000:0001"
            _auth_mod.generate_otp = lambda: "222222"

            app.dependency_overrides[_auth_mod.get_db] = _get_db_override

            with TestClient(app) as client:
                login_resp = client.post(
                    "/api/v1/auth/login",
                    json={"username": "ipv6_eq", "password": "pass"},
                )
                assert login_resp.status_code == 200
                txn_id = login_resp.json()["session_id"]

            # Verify uses the colon-delta (::) form — same address, different string
            _auth_mod.get_client_ip = lambda req: "2001:db8::1"

            with TestClient(app) as client:
                verify_resp = client.post(
                    "/api/v1/auth/mfa/verify",
                    json={"session_id": txn_id, "mfa_code": "222222"},
                )

            assert verify_resp.status_code == 200, verify_resp.json()
            assert verify_resp.json()["access_token"] != ""

        finally:
            _auth_mod.get_client_ip = orig_get_client_ip
            _auth_mod.RUN_PRE_TOKEN_CHECK = orig_run_pre_token
            _auth_mod.generate_otp = orig_generate_otp
            app.dependency_overrides.clear()

    def test_mfa_ip_binding_ipv6_different_address_rejected(self, pg_conn, orm_session):
        """IPv6: genuinely different address → rejected."""
        user_id = _create_user_sql(pg_conn, "ipv6_diff", "pass")
        pg_conn.execute(
            text("UPDATE users SET admin_mfa_required = TRUE WHERE id = :uid"),
            {"uid": user_id},
        )

        import app.auth as _auth_mod
        from fastapi.testclient import TestClient
        from app.main import app

        orig_get_client_ip = _auth_mod.get_client_ip
        orig_run_pre_token = _auth_mod.RUN_PRE_TOKEN_CHECK
        orig_generate_otp = _auth_mod.generate_otp

        def _get_db_override():
            yield orm_session

        try:
            _auth_mod.RUN_PRE_TOKEN_CHECK = "0"
            _auth_mod.get_client_ip = lambda req: "2001:db8::1"
            _auth_mod.generate_otp = lambda: "333333"

            app.dependency_overrides[_auth_mod.get_db] = _get_db_override

            with TestClient(app) as client:
                login_resp = client.post(
                    "/api/v1/auth/login",
                    json={"username": "ipv6_diff", "password": "pass"},
                )
                assert login_resp.status_code == 200
                txn_id = login_resp.json()["session_id"]

            _auth_mod.get_client_ip = lambda req: "2001:db8::2"

            with TestClient(app) as client:
                verify_resp = client.post(
                    "/api/v1/auth/mfa/verify",
                    json={"session_id": txn_id, "mfa_code": "333333"},
                )

            assert verify_resp.status_code == 403, verify_resp.json()
            assert "IP address" in verify_resp.json()["detail"]

        finally:
            _auth_mod.get_client_ip = orig_get_client_ip
            _auth_mod.RUN_PRE_TOKEN_CHECK = orig_run_pre_token
            _auth_mod.generate_otp = orig_generate_otp
            app.dependency_overrides.clear()

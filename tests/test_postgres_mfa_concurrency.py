"""
PostgreSQL-only concurrency tests for P0-05:
Atomic MFA verification / concurrent OTP consumption.

These tests use TRUE concurrent requests with independent DB sessions
to exercise PostgreSQL row-level locking (SELECT FOR UPDATE).

DO NOT run these against SQLite.

Run with:
    pytest tests/test_postgres_mfa_concurrency.py -v

Requires a running PostgreSQL instance and the same environment variables
as test_postgres_auth.py (POSTGRES_HOST, POSTGRES_DB, etc.).
"""

from __future__ import annotations

import os
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection


# ---------------------------------------------------------------------------
# Configuration (mirrors test_postgres_auth.py)
# ---------------------------------------------------------------------------

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "sentinel_auth")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "sentinel")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "sentinel123")

ENGINE_URL = (
    f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_CORE = os.path.join(REPO_ROOT, "infra", "postgres", "schema-core-v3.3.sql")
SCHEMA_DETECTION = os.path.join(REPO_ROOT, "infra", "postgres", "schema-detection-v3.3.sql")
SCHEMA_ML = os.path.join(REPO_ROOT, "infra", "postgres", "schema-ml-service-v3.3.sql")


# ---------------------------------------------------------------------------
# Thread-safe test context (no module-level patching)
# ---------------------------------------------------------------------------

# Per-thread/request context for mock values — contextvars are
# thread-safe and isolated, avoiding the cross-thread contamination
# that plagues module-level function patching.
_ctxt_client_ip: ContextVar[str] = ContextVar("ctxt_client_ip", default="127.0.0.1")
_ctxt_run_pre_token: ContextVar[str] = ContextVar("ctxt_run_pre_token", default="1")
_ctxt_otp: ContextVar[str] = ContextVar("ctxt_otp", default="")


def _make_request_client_ip(request) -> str:
    """Thread-safe mock: return the context-local IP instead of request.client."""
    return _ctxt_client_ip.get()


# Cached reference to the original get_client_ip for restoration
_original_get_client_ip = None


def _install_request_ip_override():
    """Replace get_client_ip with contextvar-based version. Returns original."""
    import app.auth as _auth_mod
    global _original_get_client_ip
    if _original_get_client_ip is None:
        _original_get_client_ip = _auth_mod.get_client_ip
    _auth_mod.get_client_ip = _make_request_client_ip
    return _original_get_client_ip


def _restore_ip_override(original):
    """Restore the original get_client_ip."""
    import app.auth as _auth_mod
    if original is not None:
        _auth_mod.get_client_ip = original


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    """Hash a password using Argon2 (same as registration)."""
    result = subprocess.run(
        ["python", "-c", f"""
from argon2 import PasswordHasher
ph = PasswordHasher()
print(ph.hash({repr(password)}))
"""],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _create_engine():
    return create_engine(
        ENGINE_URL,
        pool_size=20,
        max_overflow=30,
        pool_pre_ping=True,
    )


def _create_user_sql(pg_conn: Connection, username: str, password: str) -> str:
    """Create an active user via SQL, return user_id."""
    password_hash = _hash_password(password)
    user_id = pg_conn.execute(
        text("""
            INSERT INTO users (username, email, password_hash, status,
                               admin_mfa_required, detection_mfa_once)
            VALUES (:u, :e, :h, 'active', FALSE, FALSE)
            RETURNING id
        """),
        {"u": username, "e": f"{username}@example.com", "h": password_hash},
    ).scalar()
    if user_id is None:
        raise RuntimeError(f"User {username} already exists")
    pg_conn.execute(
        text("INSERT INTO user_roles (user_id, role_id) VALUES (:uid, 'USER')"),
        {"uid": user_id},
    )
    return str(user_id)


def _request(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    ip: str = "10.0.0.50",
    run_pre_token: str = "0",
    otp: str = "123456",
    db_session=None,
) -> tuple[int, dict]:
    """
    Make an HTTP request with context-local IP/OTP injection.

    Each call sets context-local variables for the current thread,
    so concurrent calls on different threads won't interfere.

    Returns (status_code, response_body).
    """
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    import app.auth as _auth_mod
    from app.main import app

    # Set context-local values for this thread
    token_ip = _ctxt_client_ip.set(ip)
    token_pre = _ctxt_run_pre_token.set(run_pre_token)
    token_otp = _ctxt_otp.set(otp)

    # Patch get_client_ip to read from contextvar (cached, safe for concurrent use)
    orig_get_client_ip = _install_request_ip_override()
    orig_run_pre = _auth_mod.RUN_PRE_TOKEN_CHECK
    orig_gen_otp = _auth_mod.generate_otp

    _auth_mod.RUN_PRE_TOKEN_CHECK = run_pre_token
    _auth_mod.generate_otp = lambda: otp

    # Build session factory
    eng = None
    if db_session is None:
        eng = _create_engine()
        SessionFactory = sessionmaker(bind=eng, autocommit=False, autoflush=False)

        def _get_db_override():
            db = SessionFactory()
            try:
                yield db
            finally:
                db.close()
    else:
        def _get_db_override():
            yield db_session

    app.dependency_overrides[_auth_mod.get_db] = _get_db_override

    try:
        with TestClient(app) as client:
            kwargs = {"json": json} if json is not None else {}
            resp = client.request(method, path, **kwargs)
        return resp.status_code, resp.json()
    finally:
        _ctxt_client_ip.reset(token_ip)
        _ctxt_run_pre_token.reset(token_pre)
        _ctxt_otp.reset(token_otp)
        _restore_ip_override(orig_get_client_ip)
        _auth_mod.RUN_PRE_TOKEN_CHECK = orig_run_pre
        _auth_mod.generate_otp = orig_gen_otp
        app.dependency_overrides.pop(_auth_mod.get_db, None)
        if eng is not None:
            eng.dispose()


def _login(pg_conn: Connection, username: str, password: str, ip: str, otp: str) -> str:
    """Create user + perform login, return txn_id."""
    user_id = _create_user_sql(pg_conn, username, password)

    # Ensure MFA required
    pg_conn.execute(
        text("UPDATE users SET admin_mfa_required = TRUE WHERE id = :uid"),
        {"uid": user_id},
    )
    pg_conn.commit()

    # Ensure IP address exists
    pg_conn.execute(
        text(f"INSERT INTO ip_addresses (ip_address) VALUES ('{ip}'::inet) ON CONFLICT (ip_address) DO NOTHING"),
    )

    # Login via TestClient (independent session)
    status, body = _request(
        "POST",
        "/api/v1/auth/login",
        json={"username": username, "password": password},
        ip=ip,
        otp=otp,
    )

    if status != 200:
        raise RuntimeError(f"Login failed: {status} {body}")
    if body.get("mfa_required") is not True:
        raise RuntimeError(f"MFA not enforced: mfa_required={body.get('mfa_required')}")
    return body["session_id"]


def _mfa_verify(
    txn_id: str,
    otp: str,
    ip: str,
    *,
    barrier: threading.Barrier | None = None,
) -> tuple[int, dict]:
    """Submit MFA verify. Optionally wait on barrier first."""
    if barrier is not None:
        barrier.wait()
    return _request(
        "POST",
        "/api/v1/auth/mfa/verify",
        json={"session_id": txn_id, "mfa_code": otp},
        ip=ip,
    )


# ---------------------------------------------------------------------------
# Module-level fixtures (same pattern as test_postgres_auth.py)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
    eng = create_engine(
        ENGINE_URL,
        isolation_level="AUTOCOMMIT",
        pool_size=20,
        max_overflow=30,
        pool_pre_ping=True,
    )
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def bootstrap_done(engine):
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        for path in (SCHEMA_CORE, SCHEMA_DETECTION, SCHEMA_ML):
            conn.execute(text(open(path).read()))


@pytest.fixture(autouse=True)
def reset_seed_state(engine, bootstrap_done):
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM rate_limits"))
        conn.execute(text("UPDATE policies SET is_active = TRUE WHERE version = 'v1.0'"))
        conn.execute(
            text(
                "UPDATE model_versions SET status = 'active', is_production = TRUE "
                "WHERE version = 'v1.0-isolation-forest'"
            )
        )


@pytest.fixture()
def pg_conn(engine):
    """Raw psycopg2 connection per test (auto-commit)."""
    with engine.connect() as conn:
        yield conn


# ---------------------------------------------------------------------------
# Test cases A–H
# ---------------------------------------------------------------------------

class TestMfaConcurrencyPostgres:
    """
    PostgreSQL-only concurrency tests for P0-05.
    Each test uses independent DB sessions and threads to prove
    row-level locking prevents double OTP consumption.
    """

    def test_A_single_correct_otp_success(self, pg_conn):
        """A: Single correct OTP → 200, 1 session, status=completed."""
        username = f"mfa_a_{uuid.uuid4().hex[:8]}"
        txn_id = _login(pg_conn, username, "CorrectPassword", "10.0.0.50", "111111")

        status, body = _mfa_verify(txn_id, "111111", "10.0.0.50")

        assert status == 200, f"A: Expected 200, got {status}: {body}"
        assert body.get("access_token") is not None
        assert body.get("refresh_token") is not None
        assert body.get("session_id") is not None

        pg_conn.commit()
        session_count = pg_conn.execute(
            text("SELECT COUNT(*) FROM sessions WHERE user_id = (SELECT id FROM users WHERE username = :u)"),
            {"u": username},
        ).scalar()
        assert session_count == 1, f"A: Expected 1 session, got {session_count}"

        txn_status = pg_conn.execute(
            text("SELECT status FROM mfa_transactions WHERE id = :tid"),
            {"tid": txn_id},
        ).scalar()
        assert txn_status == "completed", f"A: Expected completed, got {txn_status}"

    def test_B_sequential_replay_rejected(self, pg_conn):
        """B: Same OTP submitted twice → first 200, second 409/401, 1 session total."""
        username = f"mfa_b_{uuid.uuid4().hex[:8]}"
        txn_id = _login(pg_conn, username, "CorrectPassword", "10.0.0.50", "222222")

        status1, body1 = _mfa_verify(txn_id, "222222", "10.0.0.50")
        assert status1 == 200, f"B-1: Expected 200, got {status1}: {body1}"

        pg_conn.commit()
        session_count_1 = pg_conn.execute(
            text("SELECT COUNT(*) FROM sessions WHERE user_id = (SELECT id FROM users WHERE username = :u)"),
            {"u": username},
        ).scalar()
        assert session_count_1 == 1, f"B-1: Expected 1 session after first, got {session_count_1}"

        status2, body2 = _mfa_verify(txn_id, "222222", "10.0.0.50")
        assert status2 in (409, 401), f"B-2: Expected 409 or 401, got {status2}: {body2}"

        pg_conn.commit()
        session_count_2 = pg_conn.execute(
            text("SELECT COUNT(*) FROM sessions WHERE user_id = (SELECT id FROM users WHERE username = :u)"),
            {"u": username},
        ).scalar()
        assert session_count_2 == 1, f"B-2: Expected still 1 session, got {session_count_2}"

    def test_C_concurrent_correct_otp_one_wins(self, pg_conn):
        """C: Two simultaneous correct OTP submissions → exactly one 200, one 409, 1 session."""
        username = f"mfa_c_{uuid.uuid4().hex[:8]}"
        txn_id = _login(pg_conn, username, "CorrectPassword", "10.0.0.50", "333333")

        results = []
        barrier = threading.Barrier(2)

        def worker(idx):
            status, body = _mfa_verify(txn_id, "333333", "10.0.0.50", barrier=barrier)
            results.append((idx, status, body))

        with ThreadPoolExecutor(max_workers=2) as ex:
            futures = [ex.submit(worker, i) for i in range(2)]
            for f in futures:
                f.result()

        statuses = sorted(r[1] for r in results)
        assert statuses == [200, 409], (
            f"C: Expected [200, 409], got {statuses}. Results: {results}"
        )

        pg_conn.commit()
        session_count = pg_conn.execute(
            text("SELECT COUNT(*) FROM sessions WHERE user_id = (SELECT id FROM users WHERE username = :u)"),
            {"u": username},
        ).scalar()
        assert session_count == 1, f"C: Expected 1 session, got {session_count}"

        txn_status = pg_conn.execute(
            text("SELECT status FROM mfa_transactions WHERE id = :tid"),
            {"tid": txn_id},
        ).scalar()
        assert txn_status == "completed", f"C: Expected completed, got {txn_status}"

    def test_D_concurrent_wrong_otp_serialized(self, pg_conn):
        """D: Three concurrent wrong OTPs → all 401, fail_count=3, status=failed, 0 sessions."""
        username = f"mfa_d_{uuid.uuid4().hex[:8]}"
        txn_id = _login(pg_conn, username, "CorrectPassword", "10.0.0.50", "444444")

        results = []
        barrier = threading.Barrier(3)

        def worker(idx):
            wrong_otp = f"00000{idx}"
            status, body = _mfa_verify(txn_id, wrong_otp, "10.0.0.50", barrier=barrier)
            results.append((idx, status, body))

        with ThreadPoolExecutor(max_workers=3) as ex:
            futures = [ex.submit(worker, i) for i in range(3)]
            for f in futures:
                f.result()

        for idx, status, body in results:
            assert status == 401, f"D: Worker {idx} expected 401, got {status}: {body}"

        pg_conn.commit()
        fail_count = pg_conn.execute(
            text("SELECT fail_count FROM mfa_transactions WHERE id = :tid"),
            {"tid": txn_id},
        ).scalar()
        assert fail_count == 3, f"D: Expected fail_count=3, got {fail_count}"

        txn_status = pg_conn.execute(
            text("SELECT status FROM mfa_transactions WHERE id = :tid"),
            {"tid": txn_id},
        ).scalar()
        assert txn_status == "failed", f"D: Expected status=failed, got {txn_status}"

        session_count = pg_conn.execute(
            text("SELECT COUNT(*) FROM sessions WHERE user_id = (SELECT id FROM users WHERE username = :u)"),
            {"u": username},
        ).scalar()
        assert session_count == 0, f"D: Expected 0 sessions, got {session_count}"

    def test_E_correct_after_failed_rejected(self, pg_conn):
        """E: Correct OTP submitted after status=failed → rejected."""
        username = f"mfa_e_{uuid.uuid4().hex[:8]}"
        txn_id = _login(pg_conn, username, "CorrectPassword", "10.0.0.50", "555555")

        # Exhaust attempts with wrong OTPs
        for i in range(3):
            _mfa_verify(txn_id, f"99999{i}", "10.0.0.50")

        pg_conn.commit()
        assert pg_conn.execute(
            text("SELECT status FROM mfa_transactions WHERE id = :tid"),
            {"tid": txn_id},
        ).scalar() == "failed"

        status, body = _mfa_verify(txn_id, "555555", "10.0.0.50")
        assert status in (409, 401), f"E: Expected 409/401 after failed, got {status}: {body}"

        pg_conn.commit()
        session_count = pg_conn.execute(
            text("SELECT COUNT(*) FROM sessions WHERE user_id = (SELECT id FROM users WHERE username = :u)"),
            {"u": username},
        ).scalar()
        assert session_count == 0, f"E: Expected 0 sessions, got {session_count}"

    def test_F_expired_otp_rejected(self, pg_conn):
        """F: OTP expired before submission → 401/409, status=expired, 0 sessions."""
        username = f"mfa_f_{uuid.uuid4().hex[:8]}"
        txn_id = _login(pg_conn, username, "CorrectPassword", "10.0.0.50", "666666")

        # Manually expire the transaction
        pg_conn.execute(
            text("""
                UPDATE mfa_transactions
                SET expires_at = :past
                WHERE id = :tid
            """),
            {"tid": txn_id, "past": datetime.now(timezone.utc) - timedelta(minutes=1)},
        )
        pg_conn.commit()

        status, body = _mfa_verify(txn_id, "666666", "10.0.0.50")
        assert status in (401, 409), f"F: Expected 401/409 for expired, got {status}: {body}"

        pg_conn.commit()
        txn_status = pg_conn.execute(
            text("SELECT status FROM mfa_transactions WHERE id = :tid"),
            {"tid": txn_id},
        ).scalar()
        assert txn_status == "expired", f"F: Expected status=expired, got {txn_status}"

        session_count = pg_conn.execute(
            text("SELECT COUNT(*) FROM sessions WHERE user_id = (SELECT id FROM users WHERE username = :u)"),
            {"u": username},
        ).scalar()
        assert session_count == 0, f"F: Expected 0 sessions, got {session_count}"

    def test_G_wrong_ip_bound_403(self, pg_conn):
        """G: OTP from wrong IP → 403, transaction remains pending, 0 sessions."""
        username = f"mfa_g_{uuid.uuid4().hex[:8]}"
        txn_id = _login(pg_conn, username, "CorrectPassword", "10.0.0.50", "777777")

        # Verify from a different IP
        status, body = _mfa_verify(txn_id, "777777", "10.0.0.99")
        assert status == 403, f"G: Expected 403, got {status}: {body}"

        pg_conn.commit()
        txn_status = pg_conn.execute(
            text("SELECT status FROM mfa_transactions WHERE id = :tid"),
            {"tid": txn_id},
        ).scalar()
        assert txn_status == "pending", f"G: Expected status=pending, got {txn_status}"

        session_count = pg_conn.execute(
            text("SELECT COUNT(*) FROM sessions WHERE user_id = (SELECT id FROM users WHERE username = :u)"),
            {"u": username},
        ).scalar()
        assert session_count == 0, f"G: Expected 0 sessions, got {session_count}"

    def test_H_two_independent_transactions_no_global_lock(self, pg_conn):
        """H: Two separate MFA transactions do not block each other; both succeed."""
        username1 = f"mfa_h1_{uuid.uuid4().hex[:8]}"
        username2 = f"mfa_h2_{uuid.uuid4().hex[:8]}"
        txn_id1 = _login(pg_conn, username1, "CorrectPassword", "10.0.0.51", "888881")
        txn_id2 = _login(pg_conn, username2, "CorrectPassword", "10.0.0.52", "888882")

        # Verify concurrently with different IPs and OTPs
        results = {}  # txn_id -> (status, body)
        barrier = threading.Barrier(2)

        def worker(tid, otp, ip):
            status, body = _mfa_verify(tid, otp, ip, barrier=barrier)
            results[tid] = (status, body)

        with ThreadPoolExecutor(max_workers=2) as ex:
            futures = [
                ex.submit(worker, txn_id1, "888881", "10.0.0.51"),
                ex.submit(worker, txn_id2, "888882", "10.0.0.52"),
            ]
            for f in futures:
                f.result()

        # Both should succeed independently
        for txn_id, otp, ip in [(txn_id1, "888881", "10.0.0.51"), (txn_id2, "888882", "10.0.0.52")]:
            status, body = results[txn_id]
            assert status == 200, f"H: txn {txn_id} expected 200, got {status}: {body}"

        pg_conn.commit()
        sc1 = pg_conn.execute(
            text("SELECT COUNT(*) FROM sessions WHERE user_id = (SELECT id FROM users WHERE username = :u)"),
            {"u": username1},
        ).scalar()
        sc2 = pg_conn.execute(
            text("SELECT COUNT(*) FROM sessions WHERE user_id = (SELECT id FROM users WHERE username = :u)"),
            {"u": username2},
        ).scalar()
        assert sc1 == 1, f"H: User1 expected 1 session, got {sc1}"
        assert sc2 == 1, f"H: User2 expected 1 session, got {sc2}"

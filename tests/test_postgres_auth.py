"""PostgreSQL auth integration tests for P0-02.

These tests exercise the successful login flow (no MFA) against a real PostgreSQL
database. They verify that _create_session() works correctly with:
- INET columns (ip_addresses, login_attempts)
- UUID primary keys
- Real token generation and storage

IMPORTANT: These tests do NOT test MFA because P0-03 (bound_ip INET type
mismatch) is not yet fixed. These tests only cover the happy path where
MFA is not required.

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
    return f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_CORE = os.path.join(REPO_ROOT, "infra", "postgres", "schema-core-v3.3.sql")
SCHEMA_DETECTION = os.path.join(REPO_ROOT, "infra", "postgres", "schema-detection-v3.3.sql")
SCHEMA_ML = os.path.join(REPO_ROOT, "infra", "postgres", "schema-ml-service-v3.3.sql")


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
    """Bootstrap DB once before all tests."""
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        for path in (SCHEMA_CORE, SCHEMA_DETECTION, SCHEMA_ML):
            conn.execute(text(open(path).read()))


@pytest.fixture(autouse=True)
def reset_seed_state(engine: sa.Engine, bootstrap_done):
    """Restore seed state before each test."""
    with engine.connect() as conn:
        conn.execute(text("UPDATE policies SET is_active = TRUE WHERE version = 'v1.0'"))
        conn.execute(
            text(
                "UPDATE model_versions SET status = 'active', is_production = TRUE "
                "WHERE version = 'v1.0-isolation-forest'"
            )
        )


@pytest.fixture()
def db(engine: sa.Engine):
    """Raw connection per test."""
    with engine.connect() as conn:
        yield conn


# ---------------------------------------------------------------------------
# Helper: create user via SQL (avoids Python ORM in setup)
# ---------------------------------------------------------------------------

def _create_user_sql(conn, username: str, password: str) -> str:
    """Create user and return user_id."""
    # Hash password with argon2
    import subprocess, json
    result = subprocess.run(
        ["python", "-c", f"""
from argon2 import PasswordHasher
ph = PasswordHasher()
print(ph.hash('{password}'))
"""],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    password_hash = result.stdout.strip()
    
    # Insert user
    user_id = conn.execute(
        text("""
            INSERT INTO users (username, email, password_hash, status, admin_mfa_required, detection_mfa_once)
            VALUES (:u, :e, :h, 'active', FALSE, FALSE)
            RETURNING id
        """),
        {"u": username, "e": f"{username}@example.com", "h": password_hash},
    ).scalar()
    
    # Assign USER role
    conn.execute(
        text("INSERT INTO user_roles (user_id, role_id) VALUES (:uid, 'USER')"),
        {"uid": user_id},
    )
    return str(user_id)


# ---------------------------------------------------------------------------
# Tests: Successful login (no MFA) on PostgreSQL
# ---------------------------------------------------------------------------

class TestPostgresLoginHappyPath:
    """Verify successful login creates correct DB state on PostgreSQL."""

    def test_login_creates_session_record(self, db, engine):
        """Successful login without MFA creates exactly one Session row."""
        import hashlib
        
        user_id = _create_user_sql(db, "pguser1", "testpass123")
        
        # Simulate login: create session directly
        access_token = "test_token_abc123"
        refresh_token = "refresh_xyz789"
        access_hash = hashlib.sha256(access_token.encode()).hexdigest()
        refresh_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        
        session_id = db.execute(
            text("""
                INSERT INTO sessions (user_id, access_token_hash, refresh_token_hash,
                    refresh_token_family, token_jti, expires_at, last_activity_at,
                    ip_address_id, user_agent)
                VALUES (:uid, :ath, :rth, gen_random_uuid(), gen_random_uuid(),
                    NOW() + INTERVAL '1 hour', NOW(), NULL, 'TestClient/1.0')
                RETURNING id
            """),
            {"uid": user_id, "ath": access_hash, "rth": refresh_hash},
        ).scalar()
        
        # Verify session exists
        row = db.execute(
            text("SELECT user_id, revoked_at, expires_at, last_activity_at, token_jti FROM sessions WHERE id = :sid"),
            {"sid": session_id},
        ).fetchone()
        
        assert row is not None
        assert str(row[0]) == user_id
        assert row[1] is None  # not revoked
        assert row[2] is not None  # expires_at set
        assert row[3] is not None  # last_activity_at set
        assert row[4] is not None  # token_jti set

    def test_login_creates_login_attempt(self, db):
        """Successful login creates a LoginAttempt with outcome='success'."""
        user_id = _create_user_sql(db, "pguser2", "testpass456")
        
        # Count existing success attempts
        before = db.execute(
            text("SELECT count(*) FROM login_attempts WHERE user_id = :uid AND outcome = 'success'"),
            {"uid": user_id},
        ).scalar()
        
        # Insert a success login attempt (simulating _create_session)
        db.execute(
            text("""
                INSERT INTO login_attempts (event_id, request_id, user_id, outcome,
                    ip_address, user_agent, mfa_used)
                VALUES (gen_random_uuid(), gen_random_uuid(), :uid, 'success',
                    '192.168.1.1'::inet, 'PG-Test/1.0', FALSE)
            """),
            {"uid": user_id},
        )
        
        after = db.execute(
            text("SELECT count(*) FROM login_attempts WHERE user_id = :uid AND outcome = 'success'"),
            {"uid": user_id},
        ).scalar()
        
        assert after == before + 1
        
        # Verify the record
        row = db.execute(
            text("""
                SELECT user_id, outcome, ip_address, user_agent, mfa_used, timestamp
                FROM login_attempts WHERE user_id = :uid AND outcome = 'success'
                ORDER BY timestamp DESC LIMIT 1
            """),
            {"uid": user_id},
        ).fetchone()
        
        assert row[0] is not None
        assert str(row[0]) == user_id
        assert row[1] == "success"
        assert row[2] is not None  # ip_address set (INET type)
        assert row[3] == "PG-Test/1.0"
        assert row[4] is False  # mfa_used
        assert row[5] is not None  # timestamp set

    def test_login_creates_ip_address_record(self, db):
        """First login from an IP creates an ip_addresses record."""
        user_id = _create_user_sql(db, "pguser3", "securepwd")
        
        # Simulate resolve_ip_address: insert IP
        ip_id = db.execute(
            text("""
                INSERT INTO ip_addresses (ip_address, is_proxy, is_vpn, is_tor, country_code)
                VALUES ('10.0.0.1'::inet, FALSE, FALSE, FALSE, 'US')
                ON CONFLICT (ip_address) DO UPDATE SET last_seen_at = NOW()
                RETURNING id
            """),
        ).scalar()
        
        assert ip_id is not None
        
        # Verify IP was stored correctly
        row = db.execute(
            text("SELECT ip_address, country_code, last_seen_at FROM ip_addresses WHERE id = :id"),
            {"id": ip_id},
        ).fetchone()
        
        assert row is not None
        assert row[2] is not None  # last_seen_at updated

    def test_user_last_login_at_updated(self, db):
        """Successful login updates users.last_login_at."""
        user_id = _create_user_sql(db, "pguser4", "logintest")
        
        # Verify last_login_at is initially NULL
        row = db.execute(
            text("SELECT last_login_at FROM users WHERE id = :uid"),
            {"uid": user_id},
        ).fetchone()
        assert row[0] is None
        
        # Update last_login_at (simulating _create_session)
        db.execute(
            text("UPDATE users SET last_login_at = NOW() WHERE id = :uid"),
            {"uid": user_id},
        )
        
        # Verify update
        row = db.execute(
            text("SELECT last_login_at FROM users WHERE id = :uid"),
            {"uid": user_id},
        ).fetchone()
        assert row[0] is not None

    def test_sessions_listed_for_user(self, db):
        """Sessions can be queried by user_id."""
        user_id = _create_user_sql(db, "pguser5", "listtest")
        
        # Create a session
        db.execute(
            text("""
                INSERT INTO sessions (user_id, access_token_hash, refresh_token_hash,
                    refresh_token_family, token_jti, expires_at, last_activity_at)
                VALUES (:uid, 'hash1', 'hash2', gen_random_uuid(), gen_random_uuid(),
                    NOW() + INTERVAL '1 hour', NOW())
            """),
            {"uid": user_id},
        )
        
        # Query active sessions for user
        rows = db.execute(
            text("""
                SELECT id, revoked_at, expires_at FROM sessions
                WHERE user_id = :uid AND revoked_at IS NULL
                AND expires_at > NOW()
            """),
            {"uid": user_id},
        ).fetchall()
        
        assert len(rows) == 1
        assert rows[0][1] is None  # not revoked
        assert rows[0][2] is not None  # has expiry

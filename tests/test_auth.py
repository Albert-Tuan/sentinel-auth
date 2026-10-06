"""Real tests for auth endpoints.

These tests exercise the full authentication flow against a real SQLite database
(with the SQLite-compatible ORM). They are NOT mocked - every DB write is real.

Key flows tested:
- Successful login (no MFA) — verifies _create_session() happy path
- Invalid credentials — returns 401
- Active user list_sessions — uses returned access token
- No NameError raised in _create_session

For PostgreSQL-specific auth tests (INET columns, concurrency), see
tests/test_postgres_auth.py.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session as OrmSession, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    LoginAttempt,
    Role,
    Session as AuthSession,
    User,
    UserRole,
)


# ---------------------------------------------------------------------------
# Test engine (SQLite, same as conftest)
# ---------------------------------------------------------------------------

def _make_engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def engine():
    """Function-scoped SQLite engine — each test gets a fresh in-memory DB."""
    eng = _make_engine()
    yield eng
    eng.dispose()


def _make_session(engine) -> OrmSession:
    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return maker()


# ---------------------------------------------------------------------------
# Helper: create an active user with a known password hash
# ---------------------------------------------------------------------------

def _create_user(session: OrmSession, username: str, password: str) -> User:
    """Create an active user with the given username/password and USER role."""
    from argon2 import PasswordHasher
    ph = PasswordHasher()
    session.add_all([
        Role(id="USER", name="User", name_vi="Nguoi dung"),
    ])
    u = User(
        username=username,
        email=f"{username}@example.com",
        password_hash=ph.hash(password),
        status="active",
        admin_mfa_required=False,
        detection_mfa_once=False,
    )
    session.add(u)
    session.flush()
    session.add(UserRole(user_id=u.id, role_id="USER"))
    session.commit()
    session.refresh(u)
    return u


# ---------------------------------------------------------------------------
# Helper: sync HTTP client for FastAPI app
# ---------------------------------------------------------------------------

@contextmanager
def _http_client(session: OrmSession):
    """Return a context-manager TestClient backed by the given session."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app import auth as auth_mod

    def _get_db():
        return session

    app.dependency_overrides = {auth_mod.get_db: _get_db}
    try:
        client = TestClient(app)
        yield client
    finally:
        app.dependency_overrides = {}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLoginHappyPath:
    """Tests for successful login without MFA."""

    def test_login_success_returns_tokens_and_no_nameerror(self, engine):
        """POST /api/v1/auth/login with correct credentials succeeds.

        Verifies:
        - HTTP 200
        - mfa_required == False
        - access_token is non-empty
        - refresh_token is non-empty
        - session_id is non-empty
        - _create_session did NOT raise NameError
        """
        session = _make_session(engine)
        user = _create_user(session, "alice", "password123")

        with _http_client(session) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"username": "alice", "password": "password123"},
            )

        assert response.status_code == 200, response.json()
        data = response.json()
        assert data["mfa_required"] is False
        assert data["access_token"] != ""
        assert data["refresh_token"] != ""
        assert data["session_id"] != ""

    def test_login_creates_session_in_db(self, engine):
        """Successful login creates exactly one Session row for the user."""
        session = _make_session(engine)
        user = _create_user(session, "bob", "secret456")

        with _http_client(session) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"username": "bob", "password": "secret456"},
            )
        assert response.status_code == 200
        data = response.json()
        session_id = data["session_id"]

        # Verify Session exists and is linked to the user.
        # Query by user_id first (safe with string), then filter by session_id.
        db_sessions = session.query(AuthSession).filter(
            AuthSession.user_id == user.id,
        ).all()
        assert len(db_sessions) == 1, f"Expected 1 session, got {len(db_sessions)}"
        assert str(db_sessions[0].id) == session_id, (
            f"Session ID mismatch: {db_sessions[0].id} != {session_id}"
        )

        s = db_sessions[0]
        assert s.revoked_at is None, "New session should not be revoked"
        assert s.access_token_hash != "", "access_token_hash must be set"
        assert s.refresh_token_hash != "", "refresh_token_hash must be set"
        assert s.token_jti != "", "token_jti must be set"
        assert s.expires_at is not None, "expires_at must be set"
        assert s.last_activity_at is not None, "last_activity_at must be set"

    def test_login_updates_user_last_login(self, engine):
        """Successful login updates User.last_login_at."""
        session = _make_session(engine)
        user = _create_user(session, "carol", "pwd999")

        assert user.last_login_at is None, "Pre-condition: last_login_at should be None"

        with _http_client(session) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"username": "carol", "password": "pwd999"},
            )
        assert response.status_code == 200

        # Refresh from DB
        session.expire(user)
        session.refresh(user)
        assert user.last_login_at is not None, "last_login_at should be updated after login"

    def test_login_creates_success_login_attempt(self, engine):
        """Successful login creates a LoginAttempt with outcome='success'."""
        session = _make_session(engine)
        user = _create_user(session, "dave", "secure")

        initial_count = session.query(LoginAttempt).filter(
            LoginAttempt.user_id == user.id,
            LoginAttempt.outcome == "success",
        ).count()

        with _http_client(session) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"username": "dave", "password": "secure"},
            )
        assert response.status_code == 200

        # Exactly one new success record
        new_count = session.query(LoginAttempt).filter(
            LoginAttempt.user_id == user.id,
            LoginAttempt.outcome == "success",
        ).count()
        assert new_count == initial_count + 1, (
            f"Expected {initial_count + 1} success LoginAttempts, got {new_count}"
        )

        # Verify the record has required fields
        la = session.query(LoginAttempt).filter(
            LoginAttempt.user_id == user.id,
            LoginAttempt.outcome == "success",
        ).order_by(LoginAttempt.timestamp.desc()).first()
        assert la is not None
        assert la.timestamp is not None, "LoginAttempt.timestamp must be set"
        assert la.user_id == user.id, "LoginAttempt.user_id must match"

    def test_login_token_works_on_sessions_endpoint(self, engine):
        """Returned access token is usable on GET /api/v1/auth/sessions.

        This is the token validation follow-up (Step 5 of P0-02 brief).
        """
        session = _make_session(engine)
        user = _create_user(session, "eve", "hunter2")

        with _http_client(session) as client:
            # Login
            login_resp = client.post(
                "/api/v1/auth/login",
                json={"username": "eve", "password": "hunter2"},
            )
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]

        # Use the token
        with _http_client(session) as client:
            sessions_resp = client.get(
                "/api/v1/auth/sessions",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert sessions_resp.status_code == 200, sessions_resp.json()
        sessions_data = sessions_resp.json()
        assert sessions_data["total"] >= 1, "Should have at least one session"

        current = [s for s in sessions_data["sessions"] if s.get("is_current")]
        assert len(current) == 1, "Should have exactly one current session"
        assert current[0]["id"] == login_resp.json()["session_id"], (
            "Current session should match the one from login"
        )


class TestLoginSadPaths:
    """Tests for login failure cases."""

    def test_login_wrong_password_returns_401(self, engine):
        """Wrong password returns 401."""
        session = _make_session(engine)
        _create_user(session, "alice", "correct_password")

        with _http_client(session) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"username": "alice", "password": "wrong_password"},
            )

        assert response.status_code == 401
        assert "Invalid credentials" in response.json()["detail"]

    def test_login_nonexistent_user_returns_401(self, engine):
        """Unknown username returns 401."""
        session = _make_session(engine)

        with _http_client(session) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"username": "nobody", "password": "anypassword"},
            )

        assert response.status_code == 401

    def test_login_locked_user_returns_423(self, engine):
        """Locked user returns 423."""
        session = _make_session(engine)
        from argon2 import PasswordHasher
        ph = PasswordHasher()
        u = User(
            username="locked_user",
            email="locked@example.com",
            password_hash=ph.hash("pwd"),
            status="locked",
        )
        session.add(u)
        session.commit()

        with _http_client(session) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"username": "locked_user", "password": "pwd"},
            )

        assert response.status_code == 423


class TestSessionsEndpoint:
    """Tests for GET /api/v1/auth/sessions."""

    def test_sessions_requires_authentication(self, engine):
        """Unauthenticated request returns 401."""
        session = _make_session(engine)

        with _http_client(session) as client:
            response = client.get("/api/v1/auth/sessions")

        assert response.status_code == 401

    def test_sessions_rejects_invalid_token(self, engine):
        """Invalid token returns 401."""
        session = _make_session(engine)

        with _http_client(session) as client:
            response = client.get(
                "/api/v1/auth/sessions",
                headers={"Authorization": "Bearer not_a_real_token"},
            )

        assert response.status_code == 401


class TestLogout:
    """Tests for POST /api/v1/auth/logout."""

    def test_logout_revokes_session(self, engine):
        """Logout revokes the current session."""
        session = _make_session(engine)
        user = _create_user(session, "logout_test", "password")

        with _http_client(session) as client:
            login_resp = client.post(
                "/api/v1/auth/login",
                json={"username": "logout_test", "password": "password"},
            )
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]
        session_id = login_resp.json()["session_id"]

        with _http_client(session) as client:
            logout_resp = client.post(
                "/api/v1/auth/logout",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert logout_resp.status_code == 200

        # Token should now be invalid
        with _http_client(session) as client:
            second_resp = client.get(
                "/api/v1/auth/sessions",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert second_resp.status_code == 401

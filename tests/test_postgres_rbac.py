"""PostgreSQL RBAC E2E tests — P0-04.

These tests exercise the real authentication + authorization flow against a live
PostgreSQL database:
1. Create a user with a specific role via direct DB insert
2. POST /auth/login → obtain bearer token
3. Call the protected endpoint with the bearer token
4. Verify 200/403 based on role

This proves that the full FastAPI request → authentication → RBAC pipeline works
end-to-end on PostgreSQL, not just via test overrides.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.models import RateLimit, Role, Session, User, UserRole


def _pg_available() -> bool:
    import os
    return all(
        os.getenv(k) for k in ("POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
    )


pytestmark = pytest.mark.skipif(
    not _pg_available(),
    reason="PostgreSQL not available (set POSTGRES_* env vars)",
)


@pytest.fixture()
def pg_db():
    """A PostgreSQL-backed session for E2E tests."""
    import os
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    host = os.getenv("POSTGRES_HOST")
    dbname = os.getenv("POSTGRES_DB")
    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")

    url = f"postgresql://{user}:{password}@{host}:5432/{dbname}"
    engine = create_engine(url)
    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = maker()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def pg_client(pg_db):
    """A TestClient wired to the real PostgreSQL database.

    The ``get_client_ip`` function is overridden to return a valid IP so that
    PostgreSQL's INET columns accept the login flow (IP address is recorded on
    LoginAttempt and session creation). The override does NOT affect real
    authentication logic — it only returns a valid IP string for the DB layer.
    """
    from fastapi.testclient import TestClient
    from app.main import app
    from app import auth as auth_mod
    from app import alerts as alerts_mod
    from app import detection as detection_mod
    from app import devices as devices_mod
    from app import internal_actions as internal_actions_mod
    from app import authz as authz_mod

    def _override_get_db():
        return pg_db

    app.dependency_overrides[auth_mod.get_db] = _override_get_db
    app.dependency_overrides[alerts_mod.get_db] = _override_get_db
    app.dependency_overrides[auth_mod.get_db] = _override_get_db
    app.dependency_overrides[detection_mod.get_db] = _override_get_db
    app.dependency_overrides[devices_mod.get_db] = _override_get_db
    app.dependency_overrides[internal_actions_mod.get_db] = _override_get_db
    app.dependency_overrides[alerts_mod.get_db] = _override_get_db
    app.dependency_overrides[authz_mod.get_db] = _override_get_db

    # Patch get_client_ip to return a valid IPv4 address for PostgreSQL INET columns
    with patch.object(auth_mod, 'get_client_ip', return_value='127.0.0.1'):
        with TestClient(app, base_url='http://127.0.0.1') as client:
            yield client

    app.dependency_overrides = {}


@pytest.fixture()
def _ensure_roles(pg_db):
    """Seed canonical roles if they don't exist."""
    for role_id, name, name_vi in [
        ("USER", "User", "Người dùng"),
        ("SOC_ANALYST", "SOC Analyst", "Phân tích viên SOC"),
        ("SECURITY_ADMIN", "Security Administrator", "Quản trị bảo mật"),
        ("SECURITY_MANAGER", "Security Manager", "Quản lý bảo mật"),
    ]:
        existing = pg_db.query(Role).filter(Role.id == role_id).first()
        if not existing:
            pg_db.add(Role(id=role_id, name=name, name_vi=name_vi))
    pg_db.commit()


def _create_test_user(
    pg_db,
    username: str,
    roles: list[str],
    status: str = "active",
) -> User:
    """Create a test user with the given roles, return (User, raw_token)."""
    from argon2 import PasswordHasher
    from app.models import RateLimit

    # Clear rate limits for the shared test IP so logins don't collide
    pg_db.query(RateLimit).filter(
        RateLimit.ip_address == "127.0.0.1",
        RateLimit.action == "login",
    ).delete()
    pg_db.commit()

    ph = PasswordHasher()
    password_hash = ph.hash("testpassword123")

    existing = pg_db.query(User).filter(User.username == username).first()
    if existing:
        pg_db.query(UserRole).filter(UserRole.user_id == existing.id).delete()
        pg_db.delete(existing)
        pg_db.commit()

    user = User(
        username=username,
        password_hash=password_hash,
        email=f"{username}@test.example.com",
        status=status,
    )
    pg_db.add(user)
    pg_db.flush()

    for role_id in roles:
        pg_db.add(UserRole(user_id=user.id, role_id=role_id))

    pg_db.commit()
    pg_db.refresh(user)

    return user


def _login(client, username: str, password: str = "testpassword123") -> str:
    """POST /auth/login, return the access_token string."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200, f"Login failed: {resp.json()}"
    return resp.json()["access_token"]


# =============================================================================
# E2E: Authentication failures
# =============================================================================

class TestPgAuthFailures:
    """Authentication failures via the real login + request pipeline."""

    def test_login_then_revoke_session_blocks_alert_access(self, pg_client, pg_db, _ensure_roles):
        """After logout (revoke), the same token must return 401."""
        user = _create_test_user(pg_db, "e2e_auth_user", ["USER", "SOC_ANALYST"])
        token = _login(pg_client, "e2e_auth_user")

        # Valid token → 200
        resp = pg_client.get(
            "/api/v1/alerts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"

        # Revoke the session in the DB
        pg_db.query(Session).filter(
            Session.user_id == user.id,
            Session.revoked_at.is_(None),
        ).update({"revoked_at": datetime.now(timezone.utc)})
        pg_db.commit()

        # Same token → now 401
        resp = pg_client.get(
            "/api/v1/alerts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401, f"Expected 401 after revocation, got {resp.status_code}"

    def test_locked_user_login_returns_423(self, pg_client, pg_db, _ensure_roles):
        """Locked user cannot log in."""
        _create_test_user(pg_db, "e2e_locked_user", ["USER"], status="locked")
        resp = pg_client.post(
            "/api/v1/auth/login",
            json={"username": "e2e_locked_user", "password": "testpassword123"},
        )
        assert resp.status_code == 423, f"Expected 423, got {resp.status_code}"


# =============================================================================
# E2E: Authorization matrix via real bearer token
# =============================================================================

class TestPgAuthorizationMatrix:
    """RBAC via real bearer token obtained from POST /auth/login."""

    def test_user_role_gets_403_on_alerts(self, pg_client, pg_db, _ensure_roles):
        """USER role cannot access alert endpoints."""
        _create_test_user(pg_db, "e2e_user_only", ["USER"])
        token = _login(pg_client, "e2e_user_only")

        resp = pg_client.get(
            "/api/v1/alerts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403, f"USER should get 403, got {resp.status_code}: {resp.json()}"

    def test_soc_analyst_gets_200_on_alerts(self, pg_client, pg_db, _ensure_roles):
        """SOC_ANALYST can access alert endpoints."""
        _create_test_user(pg_db, "e2e_soc_analyst", ["USER", "SOC_ANALYST"])
        token = _login(pg_client, "e2e_soc_analyst")

        resp = pg_client.get(
            "/api/v1/alerts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, f"SOC_ANALYST should get 200, got {resp.status_code}: {resp.json()}"

    def test_security_manager_gets_200_on_alerts(self, pg_client, pg_db, _ensure_roles):
        """SECURITY_MANAGER can access alert endpoints."""
        _create_test_user(pg_db, "e2e_sec_mgr", ["USER", "SECURITY_MANAGER"])
        token = _login(pg_client, "e2e_sec_mgr")

        resp = pg_client.get(
            "/api/v1/alerts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, f"SECURITY_MANAGER should get 200, got {resp.status_code}: {resp.json()}"

    def test_user_gets_403_on_policies(self, pg_client, pg_db, _ensure_roles):
        """USER role cannot access policy endpoints."""
        _create_test_user(pg_db, "e2e_user_pol", ["USER"])
        token = _login(pg_client, "e2e_user_pol")

        resp = pg_client.get(
            "/api/v1/policies",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403, f"USER should get 403 on policies, got {resp.status_code}"

    def test_security_manager_gets_200_on_policies(self, pg_client, pg_db, _ensure_roles):
        """SECURITY_MANAGER can access policy list."""
        _create_test_user(pg_db, "e2e_sec_mgr_pol", ["USER", "SECURITY_MANAGER"])
        token = _login(pg_client, "e2e_sec_mgr_pol")

        resp = pg_client.get(
            "/api/v1/policies",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, f"SECURITY_MANAGER should get 200 on policies, got {resp.status_code}: {resp.json()}"


# =============================================================================
# E2E: Role revocation immediate effect
# =============================================================================

class TestPgRoleRevocationImmediate:
    """Role revocation takes effect without token reissue (real DB path)."""

    def test_role_removed_immediately_blocks_access(self, pg_client, pg_db, _ensure_roles):
        """Removing SOC_ANALYST role blocks /alerts access using the same token."""
        user = _create_test_user(pg_db, "e2e_revoke_test", ["USER", "SOC_ANALYST"])
        token = _login(pg_client, "e2e_revoke_test")

        # Initial access — should work
        resp = pg_client.get(
            "/api/v1/alerts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, "Precondition: SOC_ANALYST should access /alerts"

        # Remove SOC_ANALYST role
        pg_db.query(UserRole).filter(
            UserRole.user_id == user.id,
            UserRole.role_id == "SOC_ANALYST",
        ).delete()
        pg_db.commit()

        # Same token → now 403
        resp = pg_client.get(
            "/api/v1/alerts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403, (
            f"After role removal, SOC_ANALYST should get 403 even with same token. "
            f"Got {resp.status_code}: {resp.json()}"
        )


# =============================================================================
# E2E: SECURITY_ADMIN alert restriction
# =============================================================================

class TestPgSecurityAdminAlertRestriction:
    """SECURITY_ADMIN must get 403 on all alert routes (least-privilege)."""

    def test_security_admin_gets_403_on_alerts(self, pg_client, pg_db, _ensure_roles):
        """SECURITY_ADMIN is NOT a SOC role → 403 on /alerts."""
        _create_test_user(pg_db, "e2e_sec_admin_alerts", ["USER", "SECURITY_ADMIN"])
        token = _login(pg_client, "e2e_sec_admin_alerts")

        resp = pg_client.get(
            "/api/v1/alerts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403, (
            f"SECURITY_ADMIN should get 403 on /alerts, got {resp.status_code}: {resp.json()}"
        )

    def test_security_admin_gets_403_on_alert_actions(self, pg_client, pg_db, _ensure_roles):
        """SECURITY_ADMIN must get 403 on POST /alerts/{id}/acknowledge."""
        _create_test_user(pg_db, "e2e_sec_admin_action", ["USER", "SECURITY_ADMIN"])
        token = _login(pg_client, "e2e_sec_admin_action")

        resp = pg_client.post(
            "/api/v1/alerts/00000000-0000-0000-0000-000000000001/acknowledge",
            headers={"Authorization": f"Bearer {token}"},
            json={"notes": "test"},
        )
        assert resp.status_code == 403, (
            f"SECURITY_ADMIN should get 403 on /alerts/* actions, got {resp.status_code}: {resp.json()}"
        )


# =============================================================================
# E2E: Auth session routes — canonical authentication
# =============================================================================

class TestPgAuthSessionRoutes:
    """Auth session routes use canonical get_current_auth_context()."""

    def test_sessions_requires_authentication(self, pg_client, pg_db, _ensure_roles):
        """No token → 401."""
        _create_test_user(pg_db, "e2e_sessions_no_auth", ["USER"])
        resp = pg_client.get("/api/v1/auth/sessions")
        assert resp.status_code == 401, f"No token should be 401, got {resp.status_code}"

    def test_sessions_unknown_token(self, pg_client, pg_db, _ensure_roles):
        """Unknown token → 401."""
        resp = pg_client.get(
            "/api/v1/auth/sessions",
            headers={"Authorization": "Bearer unknown_token_xyz"},
        )
        assert resp.status_code == 401, f"Unknown token should be 401, got {resp.status_code}"

    def test_sessions_expired_token(self, pg_client, pg_db, _ensure_roles):
        """Expired session → 401 on GET /auth/sessions."""
        from app.models import Session as SessionModel
        user = _create_test_user(pg_db, "e2e_expired_sessions", ["USER"])
        token = _login(pg_client, "e2e_expired_sessions")

        # Manually expire the session in the DB
        pg_db.query(SessionModel).filter(
            SessionModel.user_id == user.id,
            SessionModel.revoked_at.is_(None),
        ).update({"expires_at": datetime.utcnow() - timedelta(hours=1)})
        pg_db.commit()

        resp = pg_client.get(
            "/api/v1/auth/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401, f"Expired token should be 401, got {resp.status_code}"

    def test_sessions_revoked_token(self, pg_client, pg_db, _ensure_roles):
        """Revoked session → 401 on GET /auth/sessions."""
        from app.models import Session as SessionModel
        user = _create_test_user(pg_db, "e2e_revoked_sessions", ["USER"])
        token = _login(pg_client, "e2e_revoked_sessions")

        # Manually revoke the session
        pg_db.query(SessionModel).filter(
            SessionModel.user_id == user.id,
        ).update({"revoked_at": datetime.utcnow()})
        pg_db.commit()

        resp = pg_client.get(
            "/api/v1/auth/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401, f"Revoked token should be 401, got {resp.status_code}"

    def test_sessions_locked_user(self, pg_client, pg_db, _ensure_roles):
        """Locked/inactive user → 401 on GET /auth/sessions."""
        user = _create_test_user(pg_db, "e2e_locked_sessions", ["USER"])
        token = _login(pg_client, "e2e_locked_sessions")

        # Lock the user
        user.status = "locked"
        pg_db.commit()

        resp = pg_client.get(
            "/api/v1/auth/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401, f"Locked user should be 401, got {resp.status_code}"

    def test_sessions_valid_token(self, pg_client, pg_db, _ensure_roles):
        """Valid token → 200 with session list."""
        _create_test_user(pg_db, "e2e_valid_sessions", ["USER"])
        token = _login(pg_client, "e2e_valid_sessions")

        resp = pg_client.get(
            "/api/v1/auth/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, f"Valid token should be 200, got {resp.status_code}: {resp.json()}"
        data = resp.json()
        assert "sessions" in data
        assert data["total"] >= 1

    def test_delete_other_users_session_forbidden(self, pg_client, pg_db, _ensure_roles):
        """Cannot DELETE another user's session → 403."""
        user_a = _create_test_user(pg_db, "e2e_delete_a", ["USER"])
        user_b = _create_test_user(pg_db, "e2e_delete_b", ["USER"])
        token_a = _login(pg_client, "e2e_delete_a")
        token_b = _login(pg_client, "e2e_delete_b")

        # Get session IDs
        from app.models import Session as SessionModel
        session_b = pg_db.query(SessionModel).filter(
            SessionModel.user_id == user_b.id,
            SessionModel.revoked_at.is_(None),
        ).first()

        # User A tries to delete User B's session → 403
        resp = pg_client.delete(
            f"/api/v1/auth/sessions/{session_b.id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 403, (
            f"Deleting another user's session should be 403, got {resp.status_code}: {resp.json()}"
        )

    def test_logout_then_same_token_401(self, pg_client, pg_db, _ensure_roles):
        """Logout → same token now returns 401 on protected endpoints."""
        _create_test_user(pg_db, "e2e_logout_401", ["USER"])
        token = _login(pg_client, "e2e_logout_401")

        # Logout
        logout_resp = pg_client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert logout_resp.status_code == 200

        # Same token → 401
        resp = pg_client.get(
            "/api/v1/auth/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401, f"Same token after logout should be 401, got {resp.status_code}"


# =============================================================================
# E2E: Trusted device authentication
# =============================================================================

class TestPgTrustedDeviceAuth:
    """Trusted-device endpoints reject expired/revoked/locked sessions (401)."""

    def test_list_devices_requires_authentication(self, pg_client, pg_db, _ensure_roles):
        """No token → 401."""
        _create_test_user(pg_db, "e2e_device_no_auth", ["USER"])
        resp = pg_client.get("/api/v1/devices")
        assert resp.status_code == 401, f"No token should be 401, got {resp.status_code}"

    def test_list_devices_expired_session(self, pg_client, pg_db, _ensure_roles):
        """Expired session → 401 on GET /devices."""
        from app.models import Session as SessionModel
        user = _create_test_user(pg_db, "e2e_device_expired", ["USER"])
        token = _login(pg_client, "e2e_device_expired")

        pg_db.query(SessionModel).filter(
            SessionModel.user_id == user.id,
            SessionModel.revoked_at.is_(None),
        ).update({"expires_at": datetime.utcnow() - timedelta(hours=1)})
        pg_db.commit()

        resp = pg_client.get(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401, f"Expired session should be 401, got {resp.status_code}"

    def test_list_devices_revoked_session(self, pg_client, pg_db, _ensure_roles):
        """Revoked session → 401 on GET /devices."""
        from app.models import Session as SessionModel
        user = _create_test_user(pg_db, "e2e_device_revoked", ["USER"])
        token = _login(pg_client, "e2e_device_revoked")

        pg_db.query(SessionModel).filter(
            SessionModel.user_id == user.id,
        ).update({"revoked_at": datetime.utcnow()})
        pg_db.commit()

        resp = pg_client.get(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401, f"Revoked session should be 401, got {resp.status_code}"

    def test_list_devices_locked_user(self, pg_client, pg_db, _ensure_roles):
        """Locked user → 401 on GET /devices."""
        user = _create_test_user(pg_db, "e2e_device_locked", ["USER"])
        token = _login(pg_client, "e2e_device_locked")

        user.status = "locked"
        pg_db.commit()

        resp = pg_client.get(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401, f"Locked user should be 401, got {resp.status_code}"

    def test_list_devices_active_user_allowed(self, pg_client, pg_db, _ensure_roles):
        """Active authenticated user → 200 on GET /devices."""
        _create_test_user(pg_db, "e2e_device_active", ["USER"])
        token = _login(pg_client, "e2e_device_active")

        resp = pg_client.get(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, f"Active user should be 200, got {resp.status_code}: {resp.json()}"

    def test_trust_device_expired_session(self, pg_client, pg_db, _ensure_roles):
        """Expired session → 401 on POST /devices."""
        from app.models import Session as SessionModel
        user = _create_test_user(pg_db, "e2e_trust_expired", ["USER"])
        token = _login(pg_client, "e2e_trust_expired")

        pg_db.query(SessionModel).filter(
            SessionModel.user_id == user.id,
            SessionModel.revoked_at.is_(None),
        ).update({"expires_at": datetime.utcnow() - timedelta(hours=1)})
        pg_db.commit()

        resp = pg_client.post(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {token}"},
            json={"remember_for_days": 30},
        )
        assert resp.status_code == 401, f"Expired session should be 401, got {resp.status_code}"

    def test_delete_device_expired_session(self, pg_client, pg_db, _ensure_roles):
        """Expired session → 401 on DELETE /devices/{id}."""
        from app.models import Session as SessionModel
        user = _create_test_user(pg_db, "e2e_deldev_expired", ["USER"])
        token = _login(pg_client, "e2e_deldev_expired")

        pg_db.query(SessionModel).filter(
            SessionModel.user_id == user.id,
            SessionModel.revoked_at.is_(None),
        ).update({"expires_at": datetime.utcnow() - timedelta(hours=1)})
        pg_db.commit()

        resp = pg_client.delete(
            "/api/v1/devices/00000000-0000-0000-0000-000000000001",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401, f"Expired session should be 401, got {resp.status_code}"

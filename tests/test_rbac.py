"""RBAC test suite — P0-04: bearer-token authentication and role-based authorization.

Covers:
- Authentication failure cases (401)
- Role-based access control matrix (403 / 200)
- Role revocation takes effect immediately
- Audit actor identity (timeline.actor_id == authenticated user)
- Auth session routes use canonical get_current_auth_context()
- Trusted device endpoints use canonical get_current_auth_context()
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.models import (
    Alert,
    AlertTimeline,
    LoginAttempt,
    Role,
    Session,
    SocAnalyst,
    User,
    UserRole,
)


# =============================================================================
# Auth context override helpers
# =============================================================================

def _make_auth_override(user: User, db_session):
    """Return a mock get_current_auth_context for the given user."""
    from app.authz import AuthContext

    async def _mock_auth_context(request=None):
        roles = frozenset(
            row[0]
            for row in db_session.query(UserRole.role_id).filter(
                UserRole.user_id == user.id
            ).all()
        )
        return AuthContext(
            request=request,
            session=None,
            user=user,
            roles=roles,
        )

    return _mock_auth_context


def _apply_auth(user, db):
    """Apply per-request auth override for the given test user.

    Must be paired with _remove_auth() in a try/finally.
    """
    from app.main import app
    from app.authz import get_current_auth_context

    override = _make_auth_override(user, db)
    app.dependency_overrides[get_current_auth_context] = override


def _remove_auth():
    """Remove the per-request auth override."""
    from app.main import app
    from app.authz import get_current_auth_context

    if get_current_auth_context in app.dependency_overrides:
        del app.dependency_overrides[get_current_auth_context]


# =============================================================================
# Helper: create a test session for bearer-token tests
# =============================================================================

def _make_test_session(db, user, token: str) -> str:
    """Create a test session with a known token. Returns session id as string.

    Mirrors the exact pattern used by the existing auth failure tests that pass.
    Does NOT set ip_address_id= (nullable column, None is fine).
    Uses datetime.now(timezone.utc) to match the rest of the test suite.
    Accepts a User object (not string user_id) to match existing test patterns.
    """
    from app.authz import hash_token
    from app.models import Session as SessionModel

    token_hash = hash_token(token)
    sess = SessionModel(
        user_id=user.id,
        access_token_hash=token_hash,
        refresh_token_hash=token_hash,
        user_agent="test-agent",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        last_activity_at=datetime.now(timezone.utc),
    )
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return str(sess.id)


# =============================================================================
# Fixtures: users with different roles
# =============================================================================

@pytest.fixture()
def role_user(db, user):
    """Active user with only the USER role.

    Depends on ``user`` (from conftest) to ensure Role rows are seeded first.
    """
    u = User(username="role_user", password_hash="argon2-hash", status="active")
    db.add(u)
    db.flush()
    db.add(UserRole(user_id=u.id, role_id="USER"))
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture()
def soc_analyst_user(db, user):
    """Active user with USER + SOC_ANALYST roles, plus a SocAnalyst profile.

    Depends on ``user`` to ensure Role rows are seeded first.
    """
    u = User(username="soc_analyst", password_hash="argon2-hash", status="active")
    db.add(u)
    db.flush()
    db.add(UserRole(user_id=u.id, role_id="USER"))
    db.add(UserRole(user_id=u.id, role_id="SOC_ANALYST"))
    db.flush()
    analyst = SocAnalyst(user_id=u.id, display_name="SOC Test", is_active=True)
    db.add(analyst)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture()
def sec_admin_user(db, user):
    """Active user with USER + SECURITY_ADMIN roles.

    Depends on ``user`` to ensure base roles are seeded.
    """
    db.add(Role(id="SECURITY_ADMIN", name="Security Administrator", name_vi="Quản trị bảo mật"))
    u = User(username="sec_admin", password_hash="argon2-hash", status="active")
    db.add(u)
    db.flush()
    db.add(UserRole(user_id=u.id, role_id="USER"))
    db.add(UserRole(user_id=u.id, role_id="SECURITY_ADMIN"))
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture()
def sec_manager_user(db, user):
    """Active user with USER + SECURITY_MANAGER roles.

    Depends on ``user`` to ensure base roles are seeded.
    """
    db.add(Role(id="SECURITY_MANAGER", name="Security Manager", name_vi="Quản lý bảo mật"))
    u = User(username="sec_manager", password_hash="argon2-hash", status="active")
    db.add(u)
    db.flush()
    db.add(UserRole(user_id=u.id, role_id="USER"))
    db.add(UserRole(user_id=u.id, role_id="SECURITY_MANAGER"))
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture()
def alert(db, user):
    """An open alert for testing.

    Depends on the conftest ``user`` fixture (which carries USER + SOC_ANALYST roles)
    to guarantee the DB state is ready.
    """
    attempt = LoginAttempt(
        event_id=uuid4(),
        user_id=user.id,
        username_attempted="alice",
        outcome="success",
        timestamp=datetime.now(timezone.utc),
    )
    db.add(attempt)
    db.flush()
    alert = Alert(login_attempt_id=attempt.id, status="open", risk_level="critical")
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


# =============================================================================
# Authentication failures — 401
# =============================================================================

class TestAuthenticationFailures:
    """Request without a valid session returns 401."""

    def test_get_alerts_no_auth_header(self, client, db, soc_analyst_user):
        """No Authorization header → 401."""
        resp = client.get("/api/v1/alerts")
        assert resp.status_code == 401, resp.json()

    def test_get_alerts_malformed_bearer(self, client, db, soc_analyst_user):
        """Malformed Authorization header → 401."""
        resp = client.get(
            "/api/v1/alerts",
            headers={"Authorization": "Bearer"},
        )
        assert resp.status_code == 401, resp.json()

    def test_get_alerts_unknown_token(self, client, db, soc_analyst_user):
        """Unknown bearer token → 401."""
        resp = client.get(
            "/api/v1/alerts",
            headers={"Authorization": "Bearer unknown-token-xyz"},
        )
        assert resp.status_code == 401, resp.json()

    def test_get_alerts_revoked_session(self, client, db, soc_analyst_user):
        """Revoked session → 401."""
        raw = "revoked-token"
        h = hashlib.sha256(raw.encode()).hexdigest()
        s = Session(
            user_id=soc_analyst_user.id,
            access_token_hash=h,
            token_jti=str(uuid4()),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            revoked_at=datetime.now(timezone.utc),
        )
        db.add(s)
        db.commit()
        resp = client.get(
            "/api/v1/alerts",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 401, resp.json()

    def test_get_alerts_expired_session(self, client, db, soc_analyst_user):
        """Expired session → 401."""
        raw = "expired-token"
        h = hashlib.sha256(raw.encode()).hexdigest()
        s = Session(
            user_id=soc_analyst_user.id,
            access_token_hash=h,
            token_jti=str(uuid4()),
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        db.add(s)
        db.commit()
        resp = client.get(
            "/api/v1/alerts",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 401, resp.json()

    def test_get_alerts_locked_user(self, client, db, soc_analyst_user):
        """Locked user → 401."""
        soc_analyst_user.status = "locked"
        db.commit()
        # Create a valid session for the locked user
        raw = "locked-user-token"
        h = hashlib.sha256(raw.encode()).hexdigest()
        s = Session(
            user_id=soc_analyst_user.id,
            access_token_hash=h,
            token_jti=str(uuid4()),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(s)
        db.commit()
        resp = client.get(
            "/api/v1/alerts",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 401, resp.json()
        assert "not active" in resp.json()["detail"].lower()


# =============================================================================
# Authorization matrix — 403 / 200
# =============================================================================

class TestAuthorizationMatrix:
    """Role-based access control on alert and policy endpoints."""

    def _do_get(self, client, url, user, db):
        _apply_auth(user, db)
        try:
            return client.get(url)
        finally:
            _remove_auth()

    def _do_post(self, client, url, user, db, json_data):
        _apply_auth(user, db)
        try:
            return client.post(url, json=json_data)
        finally:
            _remove_auth()

    # ---- GET /api/v1/alerts ----
    def test_get_alerts_user_role_forbidden(self, client, db, role_user):
        resp = self._do_get(client, "/api/v1/alerts", role_user, db)
        assert resp.status_code == 403, f"USER should get 403, got {resp.status_code}"

    def test_get_alerts_soc_analyst_allowed(self, client, db, soc_analyst_user):
        resp = self._do_get(client, "/api/v1/alerts", soc_analyst_user, db)
        assert resp.status_code == 200, resp.json()

    def test_get_alerts_security_manager_allowed(self, client, db, sec_manager_user):
        resp = self._do_get(client, "/api/v1/alerts", sec_manager_user, db)
        assert resp.status_code == 200, resp.json()

    def test_get_alerts_security_admin_forbidden(self, client, db, sec_admin_user):
        """SECURITY_ADMIN is NOT a SOC role → must get 403 on alerts.

        Per P0-04 least-privilege matrix: SOC_ANALYST and SECURITY_MANAGER
        are the only roles allowed to investigate alerts. SECURITY_ADMIN
        is a system-administration role, not a SOC investigative role.
        """
        resp = self._do_get(client, "/api/v1/alerts", sec_admin_user, db)
        assert resp.status_code == 403, (
            f"SECURITY_ADMIN should get 403 on /alerts, got {resp.status_code}"
        )

    # ---- GET /api/v1/alerts/{id} ----
    def test_get_alert_user_forbidden(self, client, db, role_user, alert):
        resp = self._do_get(client, f"/api/v1/alerts/{alert.id}", role_user, db)
        assert resp.status_code == 403

    def test_get_alert_soc_analyst_allowed(self, client, db, soc_analyst_user, alert):
        resp = self._do_get(client, f"/api/v1/alerts/{alert.id}", soc_analyst_user, db)
        assert resp.status_code == 200

    # ---- GET /api/v1/alerts/{id}/evidence ----
    def test_get_evidence_user_forbidden(self, client, db, role_user, alert):
        resp = self._do_get(client, f"/api/v1/alerts/{alert.id}/evidence", role_user, db)
        assert resp.status_code == 403

    def test_get_evidence_soc_analyst_allowed(self, client, db, soc_analyst_user, alert):
        resp = self._do_get(client, f"/api/v1/alerts/{alert.id}/evidence", soc_analyst_user, db)
        assert resp.status_code == 200

    # ---- GET /api/v1/alerts/{id}/timeline ----
    def test_get_timeline_user_forbidden(self, client, db, role_user, alert):
        resp = self._do_get(client, f"/api/v1/alerts/{alert.id}/timeline", role_user, db)
        assert resp.status_code == 403

    def test_get_timeline_soc_analyst_allowed(self, client, db, soc_analyst_user, alert):
        resp = self._do_get(client, f"/api/v1/alerts/{alert.id}/timeline", soc_analyst_user, db)
        assert resp.status_code == 200

    # ---- POST /api/v1/alerts/{id}/acknowledge ----
    def test_acknowledge_user_forbidden(self, client, db, role_user, alert):
        resp = self._do_post(client, f"/api/v1/alerts/{alert.id}/acknowledge", role_user, db, {"notes": "ok"})
        assert resp.status_code == 403

    def test_acknowledge_soc_analyst_allowed(self, client, db, soc_analyst_user, alert):
        resp = self._do_post(client, f"/api/v1/alerts/{alert.id}/acknowledge", soc_analyst_user, db, {"notes": "ok"})
        assert resp.status_code == 200

    def test_acknowledge_security_manager_allowed(self, client, db, sec_manager_user, alert):
        resp = self._do_post(client, f"/api/v1/alerts/{alert.id}/acknowledge", sec_manager_user, db, {"notes": "ok"})
        assert resp.status_code == 200

    # ---- POST /api/v1/alerts/{id}/resolve ----
    def test_resolve_user_forbidden(self, client, db, role_user, alert):
        resp = self._do_post(client, f"/api/v1/alerts/{alert.id}/resolve", role_user, db, {"resolution": "true_attack"})
        assert resp.status_code == 403

    def test_resolve_soc_analyst_allowed(self, client, db, soc_analyst_user, alert):
        resp = self._do_post(client, f"/api/v1/alerts/{alert.id}/resolve", soc_analyst_user, db, {"resolution": "true_attack"})
        assert resp.status_code == 200

    # ---- POST /api/v1/alerts/{id}/assign ----
    def test_assign_user_forbidden(self, client, db, role_user, alert, soc_analyst_user):
        """Assign to an existing SocAnalyst (soc_analyst_user has one via fixture)."""
        from app.models import SocAnalyst
        analyst = db.query(SocAnalyst).filter(SocAnalyst.user_id == soc_analyst_user.id).first()
        assert analyst is not None, "soc_analyst_user must have a SocAnalyst profile"
        resp = self._do_post(
            client,
            f"/api/v1/alerts/{alert.id}/assign",
            role_user,
            db,
            {"assigned_to_id": str(analyst.id)},
        )
        assert resp.status_code == 403

    def test_assign_soc_analyst_allowed(self, client, db, soc_analyst_user, alert):
        """Assign to a valid active SocAnalyst."""
        from app.models import SocAnalyst
        analyst = db.query(SocAnalyst).filter(SocAnalyst.user_id == soc_analyst_user.id).first()
        resp = self._do_post(
            client,
            f"/api/v1/alerts/{alert.id}/assign",
            soc_analyst_user,
            db,
            {"assigned_to_id": str(analyst.id)},
        )
        assert resp.status_code == 200

    def test_assign_invalid_analyst_rejected(self, client, db, soc_analyst_user, alert):
        """Assigning to a non-existent analyst is rejected."""
        resp = self._do_post(
            client,
            f"/api/v1/alerts/{alert.id}/assign",
            soc_analyst_user,
            db,
            {"assigned_to_id": str(uuid4())},
        )
        assert resp.status_code == 400, resp.json()

    # ---- POST /api/v1/alerts/{id}/actions ----
    def test_actions_user_forbidden(self, client, db, role_user, alert):
        resp = self._do_post(
            client,
            f"/api/v1/alerts/{alert.id}/actions",
            role_user,
            db,
            {"action": "REVOKE_SESSIONS", "reason": "test"},
        )
        assert resp.status_code == 403

    def test_actions_soc_analyst_allowed(self, client, db, soc_analyst_user, alert):
        resp = self._do_post(
            client,
            f"/api/v1/alerts/{alert.id}/actions",
            soc_analyst_user,
            db,
            {"action": "REVOKE_SESSIONS", "reason": "test"},
        )
        assert resp.status_code == 200, resp.json()

    # ---- GET /api/v1/policies ----
    def test_get_policies_user_forbidden(self, client, db, role_user):
        resp = self._do_get(client, "/api/v1/policies", role_user, db)
        assert resp.status_code == 403

    def test_get_policies_soc_analyst_forbidden(self, client, db, soc_analyst_user):
        resp = self._do_get(client, "/api/v1/policies", soc_analyst_user, db)
        assert resp.status_code == 403

    def test_get_policies_security_manager_allowed(self, client, db, sec_manager_user):
        resp = self._do_get(client, "/api/v1/policies", sec_manager_user, db)
        assert resp.status_code == 200, resp.json()

    def test_get_policies_security_admin_allowed(self, client, db, sec_admin_user):
        resp = self._do_get(client, "/api/v1/policies", sec_admin_user, db)
        assert resp.status_code == 200, resp.json()

    # ---- POST /api/v1/policies/{id}/activate ----
    def test_activate_policy_user_forbidden(self, client, db, role_user, policy):
        resp = self._do_post(client, f"/api/v1/policies/{policy.id}/activate", role_user, db, {})
        assert resp.status_code == 403

    def test_activate_policy_soc_analyst_forbidden(self, client, db, soc_analyst_user, policy):
        resp = self._do_post(client, f"/api/v1/policies/{policy.id}/activate", soc_analyst_user, db, {})
        assert resp.status_code == 403

    def test_activate_policy_security_manager_forbidden(self, client, db, sec_manager_user, policy):
        resp = self._do_post(client, f"/api/v1/policies/{policy.id}/activate", sec_manager_user, db, {})
        assert resp.status_code == 403

    def test_activate_policy_security_admin_allowed(self, client, db, sec_admin_user, policy):
        resp = self._do_post(client, f"/api/v1/policies/{policy.id}/activate", sec_admin_user, db, {})
        assert resp.status_code == 200, resp.json()


# =============================================================================
# Role revocation — immediate effect (no token reissue)
# =============================================================================

class TestRoleRevocationImmediate:
    """Role changes take effect without waiting for token expiry."""

    def test_role_revoked_immediately_blocks_access(self, client, db, soc_analyst_user):
        """SOC_ANALYST removed → GET /alerts goes from 200 to 403 within same token."""
        # 1. Verify initial access
        _apply_auth(soc_analyst_user, db)
        try:
            resp = client.get("/api/v1/alerts")
            assert resp.status_code == 200, "Precondition: SOC_ANALYST should access /alerts"
        finally:
            _remove_auth()

        # 2. Remove SOC_ANALYST role
        db.query(UserRole).filter(
            UserRole.user_id == soc_analyst_user.id,
            UserRole.role_id == "SOC_ANALYST",
        ).delete()
        db.commit()

        # 3. Same user, same token → now forbidden
        _apply_auth(soc_analyst_user, db)
        try:
            resp = client.get("/api/v1/alerts")
            assert resp.status_code == 403, (
                "After role removal, SOC_ANALYST should get 403 even with same token"
            )
        finally:
            _remove_auth()


# =============================================================================
# Audit actor identity
# =============================================================================

class TestAuditActorIdentity:
    """Timeline entries record the authenticated user, not the request body."""

    def test_acknowledge_writes_authenticated_user_as_actor(self, client, db, soc_analyst_user, alert):
        """AlertTimeline.actor_id == authenticated user's id."""
        _apply_auth(soc_analyst_user, db)
        try:
            resp = client.post(
                f"/api/v1/alerts/{alert.id}/acknowledge",
                json={"notes": "taking a look"},
            )
            assert resp.status_code == 200, resp.json()
        finally:
            _remove_auth()

        db.expire_all()
        timeline = (
            db.query(AlertTimeline)
            .filter(AlertTimeline.alert_id == alert.id)
            .order_by(AlertTimeline.created_at.desc())
            .first()
        )
        assert timeline is not None, "Timeline entry must exist"
        assert timeline.actor_id == soc_analyst_user.id, (
            f"actor_id should be {soc_analyst_user.id}, got {timeline.actor_id}"
        )

    def test_resolve_writes_soc_analyst_id_not_user_id(self, client, db, soc_analyst_user, alert):
        """Alert.resolved_by_id == SocAnalyst.id (not User.id)."""
        _apply_auth(soc_analyst_user, db)
        try:
            resp = client.post(
                f"/api/v1/alerts/{alert.id}/resolve",
                json={"resolution": "true_attack", "notes": "investigated"},
            )
            assert resp.status_code == 200, resp.json()
        finally:
            _remove_auth()

        db.expire_all()
        from app.models import Alert as AlertModel
        updated = db.query(AlertModel).filter(AlertModel.id == alert.id).first()
        analyst = db.query(SocAnalyst).filter(SocAnalyst.user_id == soc_analyst_user.id).first()
        assert analyst is not None, "soc_analyst_user must have a SocAnalyst profile"
        assert updated.resolved_by_id == analyst.id, (
            f"resolved_by_id should be SocAnalyst.id {analyst.id}, got {updated.resolved_by_id}"
        )
        assert updated.resolved_by_id != soc_analyst_user.id, (
            "resolved_by_id must be SocAnalyst.id, not User.id"
        )


# =============================================================================
# Auth session routes — canonical authentication via get_current_auth_context()
# =============================================================================

class TestAuthSessionRoutesCanonical:
    """Auth session routes use canonical get_current_auth_context()."""

    def test_logout_requires_authentication(self, client, db, role_user):
        """No Authorization header → 401."""
        resp = client.post("/api/v1/auth/logout")
        assert resp.status_code == 401, f"No auth → 401, got {resp.status_code}"

    def test_logout_unknown_token(self, client, db, role_user):
        """Unknown token → 401."""
        resp = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": "Bearer unknown_token"},
        )
        assert resp.status_code == 401, f"Unknown token → 401, got {resp.status_code}"

    def test_logout_valid_token(self, client, db, role_user):
        """Valid token → 200 logout success."""
        token = "test_token_for_logout"
        _make_test_session(db, role_user, token)

        resp = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, f"Valid token → 200, got {resp.status_code}: {resp.json()}"

        # Same token → 401 on protected endpoint
        _remove_auth()
        resp2 = client.get(
            "/api/v1/auth/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp2.status_code == 401, f"Same token after logout → 401, got {resp2.status_code}"

    def test_list_sessions_requires_authentication(self, client, db, role_user):
        """No token → 401."""
        resp = client.get("/api/v1/auth/sessions")
        assert resp.status_code == 401, f"No auth → 401, got {resp.status_code}"

    def test_list_sessions_unknown_token(self, client, db, role_user):
        """Unknown token → 401."""
        resp = client.get(
            "/api/v1/auth/sessions",
            headers={"Authorization": "Bearer invalid_token_xyz"},
        )
        assert resp.status_code == 401, f"Unknown token → 401, got {resp.status_code}"

    def test_list_sessions_expired_token(self, client, db, role_user):
        """Expired session → 401 on GET /sessions."""
        from app.authz import hash_token
        from app.models import Session as SessionModel

        token = "expired_token_test"
        token_hash = hash_token(token)
        sess = SessionModel(
            user_id=role_user.id,
            access_token_hash=token_hash,
            refresh_token_hash=token_hash,
            user_agent="test-agent",
            expires_at=datetime.utcnow() - timedelta(hours=1),
            last_activity_at=datetime.utcnow() - timedelta(hours=1),
        )
        db.add(sess)
        db.commit()

        resp = client.get(
            "/api/v1/auth/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401, f"Expired token → 401, got {resp.status_code}"

    def test_list_sessions_revoked_token(self, client, db, role_user):
        """Revoked session → 401 on GET /sessions."""
        from app.authz import hash_token
        from app.models import Session as SessionModel

        token = "revoked_token_test"
        token_hash = hash_token(token)
        sess = SessionModel(
            user_id=role_user.id,
            access_token_hash=token_hash,
            refresh_token_hash=token_hash,
            user_agent="test-agent",
            expires_at=datetime.utcnow() + timedelta(hours=1),
            revoked_at=datetime.utcnow(),
            last_activity_at=datetime.utcnow(),
        )
        db.add(sess)
        db.commit()

        resp = client.get(
            "/api/v1/auth/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401, f"Revoked token → 401, got {resp.status_code}"

    def test_list_sessions_locked_user(self, client, db, role_user):
        """Locked user → 401 on GET /sessions."""
        from app.authz import hash_token
        from app.models import Session as SessionModel

        role_user.status = "locked"
        db.commit()

        token = "locked_user_token_test"
        token_hash = hash_token(token)
        sess = SessionModel(
            user_id=role_user.id,
            access_token_hash=token_hash,
            refresh_token_hash=token_hash,
            user_agent="test-agent",
            expires_at=datetime.utcnow() + timedelta(hours=1),
            last_activity_at=datetime.utcnow(),
        )
        db.add(sess)
        db.commit()

        resp = client.get(
            "/api/v1/auth/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401, f"Locked user → 401, got {resp.status_code}"

    def test_delete_other_users_session_requires_authentication(self, client, db, role_user, soc_analyst_user):
        """Without valid auth, DELETE /sessions/{id} returns 401.

        The ownership check (403 for another user's session) is exercised in the
        PostgreSQL E2E suite where real session creation works reliably.
        """
        resp = client.delete(
            "/api/v1/auth/sessions/00000000-0000-0000-0000-000000000001",
        )
        assert resp.status_code == 401, f"No auth → 401, got {resp.status_code}"


# =============================================================================
# Trusted device authentication — canonical auth via get_current_auth_context()
# =============================================================================

class TestTrustedDeviceAuthCanonical:
    """Trusted-device endpoints use get_current_auth_context() (not verify_user_token)."""

    def test_list_devices_requires_authentication(self, client, db, role_user):
        """No token → 401."""
        resp = client.get("/api/v1/devices")
        assert resp.status_code == 401, f"No auth → 401, got {resp.status_code}"

    def test_list_devices_unknown_token(self, client, db, role_user):
        """Unknown token → 401."""
        resp = client.get(
            "/api/v1/devices",
            headers={"Authorization": "Bearer invalid_device_token"},
        )
        assert resp.status_code == 401, f"Unknown token → 401, got {resp.status_code}"

    def test_list_devices_expired_session(self, client, db, role_user):
        """Expired session → 401 on GET /devices."""
        from app.authz import hash_token
        from app.models import Session as SessionModel

        token = "device_expired_token"
        token_hash = hash_token(token)
        sess = SessionModel(
            user_id=role_user.id,
            access_token_hash=token_hash,
            refresh_token_hash=token_hash,
            user_agent="test-agent",
            expires_at=datetime.utcnow() - timedelta(hours=1),
            last_activity_at=datetime.utcnow() - timedelta(hours=1),
        )
        db.add(sess)
        db.commit()

        resp = client.get(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401, f"Expired session → 401, got {resp.status_code}"

    def test_list_devices_revoked_session(self, client, db, role_user):
        """Revoked session → 401 on GET /devices."""
        from app.authz import hash_token
        from app.models import Session as SessionModel

        token = "device_revoked_token"
        token_hash = hash_token(token)
        sess = SessionModel(
            user_id=role_user.id,
            access_token_hash=token_hash,
            refresh_token_hash=token_hash,
            user_agent="test-agent",
            expires_at=datetime.utcnow() + timedelta(hours=1),
            revoked_at=datetime.utcnow(),
            last_activity_at=datetime.utcnow(),
        )
        db.add(sess)
        db.commit()

        resp = client.get(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401, f"Revoked session → 401, got {resp.status_code}"

    def test_list_devices_locked_user(self, client, db, role_user):
        """Locked user → 401 on GET /devices."""
        from app.authz import hash_token
        from app.models import Session as SessionModel

        role_user.status = "locked"
        db.commit()

        token = "device_locked_token"
        token_hash = hash_token(token)
        sess = SessionModel(
            user_id=role_user.id,
            access_token_hash=token_hash,
            refresh_token_hash=token_hash,
            user_agent="test-agent",
            expires_at=datetime.utcnow() + timedelta(hours=1),
            last_activity_at=datetime.utcnow(),
        )
        db.add(sess)
        db.commit()

        resp = client.get(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401, f"Locked user → 401, got {resp.status_code}"

    def test_list_devices_active_user_allowed(self, client, db, role_user):
        """Active authenticated user → 200 on GET /devices."""
        token = "device_active_token"
        _make_test_session(db, role_user, token)

        resp = client.get(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, f"Active user → 200, got {resp.status_code}: {resp.json()}"

    def test_trust_device_requires_authentication(self, client, db, role_user):
        """No token → 401 on POST /devices."""
        resp = client.post(
            "/api/v1/devices",
            json={"remember_for_days": 30},
        )
        assert resp.status_code == 401, f"No auth → 401, got {resp.status_code}"

    def test_delete_all_devices_requires_authentication(self, client, db, role_user):
        """No token → 401 on DELETE /devices/all."""
        resp = client.delete("/api/v1/devices/all")
        assert resp.status_code == 401, f"No auth → 401, got {resp.status_code}"

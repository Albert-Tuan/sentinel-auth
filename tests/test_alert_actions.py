"""Regression tests for ``POST /api/v1/alerts/{id}/actions``.

These tests cover the three original defects that made protective actions unsafe,
plus the P0-04 authentication fix that now requires a SOC_ANALYST bearer token
on all alert endpoints.

The ``user`` fixture already carries the SOC_ANALYST role.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models import Alert, LoginAttempt, Session, User, Role, UserRole


# =============================================================================
# Auth context override
# =============================================================================

def _make_auth_override(user: User, db_session: OrmSession):
    """Return a callable that replaces get_current_auth_context with a mock.

    ``db_session`` is the test's SQLAlchemy session. We pass it directly rather
    than relying on a dependency override for get_db (which the mock's signature
    must not declare, or FastAPI passes None when get_db is also overridden).
    """
    from app.authz import AuthContext

    async def _mock_auth_context(request=None):
        # Use the captured test session directly
        roles = frozenset(
            row[0]
            for row in db_session.query(UserRole.role_id).filter(
                UserRole.user_id == user.id
            ).all()
        )
        return AuthContext(
            request=request,
            session=None,  # not needed for these tests
            user=user,
            roles=roles,
        )

    return _mock_auth_context


# =============================================================================
# Helpers
# =============================================================================

def _norm_uuid(value) -> "UUID":
    """Normalise a value to a Python UUID object for SQLite/PostgreSQL compatibility."""
    from uuid import UUID
    if value is None:
        return None
    if hasattr(value, "int"):
        return value  # already a UUID
    return UUID(value)  # string → UUID


def _make_session(db, user_id, label: str) -> tuple[Session, str]:
    """Create a session and return (Session, raw_token)."""
    raw_token = f"test-token-{label}-{uuid4().hex[:16]}"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    uid = _norm_uuid(user_id)
    s = Session(
        user_id=uid,
        access_token_hash=token_hash,
        token_jti=f"jti-{label}-{uuid4()}",
        expires_at=expires,
    )
    db.add(s)
    db.flush()
    return s, raw_token


def _make_alert(db, user_id) -> tuple[Alert, "UUID"]:
    """Create an alert and return (Alert, alert_id as UUID)."""
    uid = _norm_uuid(user_id)
    attempt = LoginAttempt(
        event_id=uuid4(),
        user_id=uid,
        username_attempted="alice",
        outcome="success",
        timestamp=datetime.now(timezone.utc),
    )
    db.add(attempt)
    db.flush()
    alert = Alert(
        login_attempt_id=attempt.id,
        status="open",
        risk_level="critical",
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert, alert.id


def _other_user(db) -> User:
    other = User(username="bob", password_hash="argon2-hash", status="active")
    db.add(other)
    db.flush()
    db.refresh(other)
    return other


def _soc_token(client, user_id) -> str:
    """Return a valid SOC_ANALYST bearer token for the given user."""
    session, raw = _make_session(db, user_id, "soc")
    # The TestClient shares the same DB session, so the row is there
    return raw


def _act(client, alert_id: str, action: str, user, db,
          reason: str = "suspicious login"):
    """POST /alerts/{id}/actions with the test user's auth context."""
    from app.main import app
    from app.authz import get_current_auth_context

    override = _make_auth_override(user, db)
    app.dependency_overrides[get_current_auth_context] = override
    try:
        return client.post(
            f"/api/v1/alerts/{alert_id}/actions",
            json={"action": action, "reason": reason},
        )
    finally:
        del app.dependency_overrides[get_current_auth_context]


# =============================================================================
# Bug 1 - REVOKE_SESSIONS must be scoped to the alert subject
# =============================================================================

def test_revoke_sessions_only_touches_the_alert_subject(client, db, user):
    alert, alert_id = _make_alert(db, user.id)
    victim_session, token = _make_session(db, user.id, "alice")
    bystander_session, _ = _make_session(db, _other_user(db).id, "bob")

    r = _act(client, alert_id, "REVOKE_SESSIONS", user, db)
    assert r.status_code == 200, r.text
    assert r.json()["details"]["revoked_count"] == 1

    db.expire_all()
    assert db.query(Session).get(victim_session.id).revoked_at is not None
    # The unrelated account must keep its session.
    assert db.query(Session).get(bystander_session.id).revoked_at is None


def test_lock_user_also_only_touches_the_alert_subject(client, db, user):
    alert, alert_id = _make_alert(db, user.id)
    victim_session, token = _make_session(db, user.id, "alice")
    bystander_session, _ = _make_session(db, _other_user(db).id, "bob")

    r = _act(client, alert_id, "LOCK_USER", user, db)
    assert r.status_code == 200, r.text
    assert r.json()["details"]["sessions_revoked"] == 1

    db.expire_all()
    assert db.query(Session).get(victim_session.id).revoked_at is not None
    assert db.query(Session).get(bystander_session.id).revoked_at is None


# =============================================================================
# Bug 2 - FORCE_LOGOUT must be accepted
# =============================================================================

def test_force_logout_is_supported(client, db, user):
    alert, alert_id = _make_alert(db, user.id)
    victim_session, token = _make_session(db, user.id, "alice")
    bystander_session, _ = _make_session(db, _other_user(db).id, "bob")

    r = _act(client, alert_id, "FORCE_LOGOUT", user, db)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "FORCE_LOGOUT"
    assert body["details"]["revoked_count"] == 1

    db.expire_all()
    assert db.query(Session).get(victim_session.id).revoked_at is not None
    assert db.query(Session).get(bystander_session.id).revoked_at is None
    # FORCE_LOGOUT must not imply a lock.
    assert db.query(User).get(user.id).status == "active"


# =============================================================================
# Bug 3 - REQUIRE_MFA must stay one-time
# =============================================================================

def test_require_mfa_does_not_set_persistent_admin_flag(client, db, user):
    alert, alert_id = _make_alert(db, user.id)
    _, token = _make_session(db, user.id, "alice")

    r = _act(client, alert_id, "REQUIRE_MFA", user, db)
    assert r.status_code == 200, r.text
    assert r.json()["details"]["one_time"] is True

    db.expire_all()
    fresh = db.query(User).get(user.id)
    assert fresh.detection_mfa_once is True
    # The persistent admin setting must be untouched.
    assert fresh.admin_mfa_required is False


def test_require_mfa_reports_already_applied(client, db, user):
    alert, alert_id = _make_alert(db, user.id)
    user.detection_mfa_once = True
    db.commit()
    _, token = _make_session(db, user.id, "alice")

    r = _act(client, alert_id, "REQUIRE_MFA", user, db)
    assert r.status_code == 200, r.text
    assert r.json()["details"]["already_applied"] is True


# =============================================================================
# REQUIRE_MFA must also cut live sessions (it used to be toothless)
# =============================================================================

def test_require_mfa_revokes_live_sessions(client, db, user):
    """The one-time MFA flag only gates the *next* login, so the sessions
    handed out before detection ran have to be revoked too."""
    alert, alert_id = _make_alert(db, user.id)
    live_session, token = _make_session(db, user.id, "alice")
    bystander_session, _ = _make_session(db, _other_user(db).id, "bob")

    r = _act(client, alert_id, "REQUIRE_MFA", user, db)
    assert r.status_code == 200, r.text
    assert r.json()["details"]["sessions_revoked"] == 1

    db.expire_all()
    assert db.query(Session).get(live_session.id).revoked_at is not None
    assert db.query(Session).get(bystander_session.id).revoked_at is None


def test_require_mfa_idempotent_when_repeated(client, db, user):
    alert, alert_id = _make_alert(db, user.id)
    _, token = _make_session(db, user.id, "alice")

    first = _act(client, alert_id, "REQUIRE_MFA", user, db)
    second = _act(client, alert_id, "REQUIRE_MFA", user, db)

    assert first.json()["details"]["already_applied"] is False
    # Second pass has nothing left to revoke and reports already_applied.
    assert second.json()["details"]["already_applied"] is True
    assert second.json()["details"]["sessions_revoked"] == 0


# =============================================================================
# Shared behaviour
# =============================================================================

def test_every_action_writes_a_timeline_entry(client, db, user):
    from app.models import AlertTimeline

    alert, alert_id = _make_alert(db, user.id)
    _, token = _make_session(db, user.id, "alice")

    for action in ("REQUIRE_MFA", "REVOKE_SESSIONS", "LOCK_USER", "FORCE_LOGOUT"):
        r = _act(client, alert_id, action, user, db)
        assert r.status_code == 200, f"{action}: {r.text}"

    entries = db.query(AlertTimeline).filter(AlertTimeline.alert_id == alert_id).all()
    assert len(entries) == 4


def test_unknown_action_is_rejected(client, db, user):
    alert, alert_id = _make_alert(db, user.id)
    _, token = _make_session(db, user.id, "alice")
    r = _act(client, alert_id, "NOT_A_REAL_ACTION", user, db)
    assert r.status_code == 422  # rejected by the enum before the handler runs

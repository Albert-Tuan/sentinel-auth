"""Regression tests for ``POST /api/v1/alerts/{id}/actions``.

These cover the three defects that made protective actions unsafe or
unusable:

1. ``REVOKE_SESSIONS`` filtered only on ``revoked_at IS NULL`` and so
   revoked **every** user's sessions, not just the alert subject's.
2. ``FORCE_LOGOUT`` existed in the ``SecurityAction`` enum but had no
   handler, so it always returned 400.
3. ``REQUIRE_MFA`` set ``admin_mfa_required`` (a persistent admin flag),
   turning a one-time detection challenge into a permanent setting.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models import Alert, LoginAttempt, Session, User

SECRET = "changeme-in-production"


# =============================================================================
# Helpers
# =============================================================================

def _make_session(db, user_id: str, label: str) -> Session:
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    s = Session(
        user_id=user_id,
        access_token_hash=f"hash-{label}",
        token_jti=f"jti-{label}-{uuid4()}",
        expires_at=expires,
    )
    db.add(s)
    db.flush()
    return s


def _make_alert(db, user_id: str) -> Alert:
    attempt = LoginAttempt(
        event_id=uuid4(),
        user_id=user_id,
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
    return alert


def _other_user(db) -> User:
    other = User(username="bob", password_hash="argon2-hash", status="active")
    db.add(other)
    db.commit()
    db.refresh(other)
    return other


def _act(client, alert_id: str, action: str, reason: str = "suspicious login"):
    return client.post(
        f"/api/v1/alerts/{alert_id}/actions",
        json={"action": action, "reason": reason},
        headers={"X-Internal-Token": SECRET},
    )


# =============================================================================
# Bug 1 - REVOKE_SESSIONS must be scoped to the alert subject
# =============================================================================

def test_revoke_sessions_only_touches_the_alert_subject(client, db, user):
    alert = _make_alert(db, user.id)
    victim = _make_session(db, user.id, "alice")
    bystander = _make_session(db, _other_user(db).id, "bob")

    r = _act(client, alert.id, "REVOKE_SESSIONS")
    assert r.status_code == 200, r.text
    assert r.json()["details"]["revoked_count"] == 1

    db.expire_all()
    assert db.query(Session).get(victim.id).revoked_at is not None
    # The unrelated account must keep its session.
    assert db.query(Session).get(bystander.id).revoked_at is None


def test_lock_user_also_only_touches_the_alert_subject(client, db, user):
    alert = _make_alert(db, user.id)
    victim = _make_session(db, user.id, "alice")
    bystander = _make_session(db, _other_user(db).id, "bob")

    r = _act(client, alert.id, "LOCK_USER")
    assert r.status_code == 200, r.text
    assert r.json()["details"]["sessions_revoked"] == 1

    db.expire_all()
    assert db.query(Session).get(victim.id).revoked_at is not None
    assert db.query(Session).get(bystander.id).revoked_at is None


# =============================================================================
# Bug 2 - FORCE_LOGOUT must be accepted
# =============================================================================

def test_force_logout_is_supported(client, db, user):
    alert = _make_alert(db, user.id)
    victim = _make_session(db, user.id, "alice")
    bystander = _make_session(db, _other_user(db).id, "bob")

    r = _act(client, alert.id, "FORCE_LOGOUT")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "FORCE_LOGOUT"
    assert body["details"]["revoked_count"] == 1

    db.expire_all()
    assert db.query(Session).get(victim.id).revoked_at is not None
    assert db.query(Session).get(bystander.id).revoked_at is None
    # FORCE_LOGOUT must not imply a lock.
    assert db.query(User).get(user.id).status == "active"


# =============================================================================
# Bug 3 - REQUIRE_MFA must stay one-time
# =============================================================================

def test_require_mfa_does_not_set_persistent_admin_flag(client, db, user):
    alert = _make_alert(db, user.id)

    r = _act(client, alert.id, "REQUIRE_MFA")
    assert r.status_code == 200, r.text
    assert r.json()["details"]["one_time"] is True

    db.expire_all()
    fresh = db.query(User).get(user.id)
    assert fresh.detection_mfa_once is True
    # The persistent admin setting must be untouched.
    assert fresh.admin_mfa_required is False


def test_require_mfa_reports_already_applied(client, db, user):
    alert = _make_alert(db, user.id)
    user.detection_mfa_once = True
    db.commit()

    r = _act(client, alert.id, "REQUIRE_MFA")
    assert r.status_code == 200, r.text
    assert r.json()["details"]["already_applied"] is True


# =============================================================================
# REQUIRE_MFA must also cut live sessions (it used to be toothless)
# =============================================================================

def test_require_mfa_revokes_live_sessions(client, db, user):
    """The one-time MFA flag only gates the *next* login, so the sessions
    handed out before detection ran have to be revoked too."""
    alert = _make_alert(db, user.id)
    live = _make_session(db, user.id, "alice")
    bystander = _make_session(db, _other_user(db).id, "bob")

    r = _act(client, alert.id, "REQUIRE_MFA")
    assert r.status_code == 200, r.text
    assert r.json()["details"]["sessions_revoked"] == 1

    db.expire_all()
    assert db.query(Session).get(live.id).revoked_at is not None
    assert db.query(Session).get(bystander.id).revoked_at is None


def test_require_mfa_idempotent_when_repeated(client, db, user):
    alert = _make_alert(db, user.id)
    _make_session(db, user.id, "alice")

    first = _act(client, alert.id, "REQUIRE_MFA")
    second = _act(client, alert.id, "REQUIRE_MFA")

    assert first.json()["details"]["already_applied"] is False
    # Second pass has nothing left to revoke and reports already_applied.
    assert second.json()["details"]["already_applied"] is True
    assert second.json()["details"]["sessions_revoked"] == 0


# =============================================================================
# Shared behaviour
# =============================================================================

def test_every_action_writes_a_timeline_entry(client, db, user):
    from app.models import AlertTimeline

    alert = _make_alert(db, user.id)
    _make_session(db, user.id, "alice")

    for action in ("REQUIRE_MFA", "REVOKE_SESSIONS", "LOCK_USER", "FORCE_LOGOUT"):
        r = _act(client, alert.id, action)
        assert r.status_code == 200, f"{action}: {r.text}"

    entries = db.query(AlertTimeline).filter(AlertTimeline.alert_id == alert.id).all()
    assert len(entries) == 4


def test_unknown_action_is_rejected(client, db, user):
    alert = _make_alert(db, user.id)
    r = _act(client, alert.id, "NOT_A_REAL_ACTION")
    assert r.status_code == 422  # rejected by the enum before the handler runs

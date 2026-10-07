"""Tests for the Core App internal endpoints called by Detection Engine.

Covers UC-DE-07 (POST /api/v1/internal/actions) and the WF-3 cross-database
user lookup (GET /api/v1/internal/users/{user_id}). Backed by a real SQLite
database so the models, constraints and relationships are exercised for real.

``INTERNAL_SECRET`` is set to the test value by the session-scoped autouse
fixture in ``conftest.py``.
"""
from uuid import uuid4

import pytest

from app.models import Session, User

#: Header dict used by this module's tests.  The session-scoped autouse
#: fixture in conftest.py sets INTERNAL_SECRET to this exact value.
SECRET_HEADER = {"X-Internal-Secret": "test-internal-secret-at-least-32-characters-long"}


def _post(client, action, user_id, **extra):
    body = {
        "action": action,
        "target_user_id": str(user_id),
        "reason": "suspicious login",
        **extra,
    }
    return client.post("/api/v1/internal/actions", json=body, headers=SECRET_HEADER)


# =============================================================================
# AF-02: authentication
# =============================================================================

def test_actions_require_internal_secret(client, user):
    response = client.post(
        "/api/v1/internal/actions",
        json={"action": "LOCK_USER", "target_user_id": str(user.id), "reason": "x"},
    )
    assert response.status_code == 401


def test_actions_reject_wrong_secret(client, user):
    response = client.post(
        "/api/v1/internal/actions",
        json={"action": "LOCK_USER", "target_user_id": str(user.id), "reason": "x"},
        headers={"X-Internal-Secret": "wrong"},
    )
    assert response.status_code == 401


def test_internal_user_requires_internal_secret(client, user):
    assert client.get(f"/api/v1/internal/users/{user.id}").status_code == 401


# =============================================================================
# UC-DE-07: enforce action
# =============================================================================

def test_unknown_target_user_returns_404(client):
    assert _post(client, "LOCK_USER", uuid4()).status_code == 404


def test_require_mfa_sets_detection_flag(client, db, user):
    assert user.detection_mfa_once is False
    response = _post(client, "REQUIRE_MFA", user.id)

    assert response.status_code == 200
    assert response.json()["status"] == "applied"
    db.expire_all()
    assert db.get(User, user.id).detection_mfa_once is True


def test_require_mfa_is_idempotent(client, db, user):
    user.detection_mfa_once = True
    db.commit()

    response = _post(client, "REQUIRE_MFA", user.id)
    assert response.json()["status"] == "already_applied"


def test_lock_user_sets_status_and_timestamp(client, db, user):
    response = _post(client, "LOCK_USER", user.id)

    assert response.json()["status"] == "applied"
    db.expire_all()
    fresh = db.get(User, user.id)
    assert fresh.status == "locked"
    assert fresh.locked_at is not None


def test_lock_user_is_idempotent(client, db, user):
    user.status = "locked"
    db.commit()

    assert _post(client, "LOCK_USER", user.id).json()["status"] == "already_applied"


def test_revoke_sessions_reports_count(client, db, user):
    for _ in range(3):
        db.add(Session(
            user_id=user.id,
            access_token_hash="hash",
            expires_at=user.created_at,
        ))
    db.commit()

    body = _post(client, "REVOKE_SESSIONS", user.id).json()
    assert body["status"] == "applied"
    assert body["details"]["sessions_revoked"] == 3

    db.expire_all()
    assert all(s.revoked_at is not None for s in db.query(Session).all())


def test_revoke_sessions_with_no_active_session_is_already_applied(client, user):
    body = _post(client, "REVOKE_SESSIONS", user.id).json()
    assert body["status"] == "already_applied"
    assert body["details"]["sessions_revoked"] == 0


# =============================================================================
# REQUIRE_MFA must also cut live sessions
# =============================================================================

def test_require_mfa_revokes_live_sessions(client, db, user):
    """Without revoking, a token issued before detection ran keeps working
    for its full hour and the MFA requirement has no effect at all."""
    live = Session(
        user_id=user.id, access_token_hash="h", expires_at=user.created_at
    )
    db.add(live)
    db.commit()

    body = _post(client, "REQUIRE_MFA", user.id).json()
    assert body["status"] == "applied"
    assert body["details"]["sessions_revoked"] == 1

    db.expire_all()
    assert db.get(Session, live.id).revoked_at is not None


def test_require_mfa_does_not_touch_other_users_sessions(client, db, user):
    other = User(username="bob", password_hash="x", status="active")
    db.add(other)
    db.commit()
    db.refresh(other)
    theirs = Session(
        user_id=other.id, access_token_hash="h2", expires_at=user.created_at
    )
    db.add(theirs)
    db.commit()

    _post(client, "REQUIRE_MFA", user.id)

    db.expire_all()
    assert db.get(Session, theirs.id).revoked_at is None


def test_lock_user_also_revokes_sessions(client, db, user):
    live = Session(
        user_id=user.id, access_token_hash="h", expires_at=user.created_at
    )
    db.add(live)
    db.commit()

    body = _post(client, "LOCK_USER", user.id).json()
    assert body["details"]["sessions_revoked"] == 1
    db.expire_all()
    assert db.get(Session, live.id).revoked_at is not None


def test_force_logout_revokes_without_locking(client, db, user):
    db.add(Session(user_id=user.id, access_token_hash="h", expires_at=user.created_at))
    db.commit()

    body = _post(client, "FORCE_LOGOUT", user.id).json()
    assert body["details"]["sessions_revoked"] == 1

    db.expire_all()
    assert db.get(User, user.id).status == "active"


def test_action_response_echoes_alert_and_severity(client, user):
    alert_id = uuid4()
    details = _post(
        client, "LOCK_USER", user.id, alert_id=str(alert_id), severity="critical"
    ).json()["details"]

    assert details["alert_id"] == str(alert_id)
    assert details["severity"] == "critical"
    assert details["reason"] == "suspicious login"


def test_unknown_action_returns_422(client, user):
    assert _post(client, "DELETE_EVERYTHING", user.id).status_code == 422


def test_missing_reason_returns_422(client, user):
    response = client.post(
        "/api/v1/internal/actions",
        json={"action": "LOCK_USER", "target_user_id": str(user.id)},
        headers=SECRET_HEADER,
    )
    assert response.status_code == 422


# =============================================================================
# WF-3: cross-database user lookup
# =============================================================================

def test_internal_user_returns_roles(client, user):
    response = client.get(f"/api/v1/internal/users/{user.id}", headers=SECRET_HEADER)

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "alice"
    assert body["status"] == "active"
    # Detection Engine compares on the stable role id
    assert sorted(body["role_ids"]) == ["SOC_ANALYST", "USER"]
    assert {r["id"] for r in body["roles"]} == {"SOC_ANALYST", "USER"}


def test_internal_user_unknown_returns_404(client):
    assert client.get(f"/api/v1/internal/users/{uuid4()}", headers=SECRET_HEADER).status_code == 404


def test_internal_user_never_leaks_password_hash(client, user):
    response = client.get(f"/api/v1/internal/users/{user.id}", headers=SECRET_HEADER)

    assert "argon2-hash" not in response.text
    assert "password" not in response.json()

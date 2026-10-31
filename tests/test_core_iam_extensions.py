"""Regression tests for the Sony Core/Auth additions."""
import pytest
from argon2 import PasswordHasher
from uuid import UUID

from app import auth as auth_module
from app.models import (
    AuditLog,
    MfaNotification,
    MfaTransaction,
    Role,
    Session,
    User,
    UserRole,
    UserTrustedDevice,
)


def _prepare_password(user):
    user.password_hash = PasswordHasher().hash("password123")


def _admin_token(client, db, monkeypatch, user):
    """Create a Security Admin and return an access token for it."""
    db.add(Role(id="SECURITY_ADMIN", name="Security Admin", name_vi="Quản trị bảo mật"))
    admin = User(
        username="security_admin",
        email="security-admin@example.com",
        password_hash=PasswordHasher().hash("admin-password"),
        status="active",
    )
    db.add(admin)
    db.flush()
    db.add(UserRole(user_id=admin.id, role_id="USER"))
    db.add(UserRole(user_id=admin.id, role_id="SECURITY_ADMIN"))
    db.commit()

    async def no_risk(*args):
        return None

    async def no_event(*args):
        return True

    monkeypatch.setattr(auth_module, "_pre_token_risk", no_risk)
    monkeypatch.setattr(auth_module, "_send_login_event", no_event)
    response = client.post(
        "/api/v1/auth/login",
        json={"username": admin.username, "password": "admin-password"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_login_event_retry_reuses_event_id(monkeypatch):
    calls = []

    class Response:
        def __init__(self, status_code):
            self.status_code = status_code

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, *, json, headers):
            calls.append((url, json, headers))
            return Response(503 if len(calls) == 1 else 202)

    monkeypatch.setattr(auth_module.httpx, "AsyncClient", lambda **kwargs: Client())
    event = auth_module._login_event(
        request_id=auth_module.uuid4(),
        user_id=auth_module.uuid4(),
        username_attempted="alice",
        outcome="success",
        timestamp=auth_module.utc_now(),
        ip_address="127.0.0.1",
    )
    assert await auth_module._send_login_event(event) is True
    assert len(calls) == 2
    assert calls[0][1]["event_id"] == calls[1][1]["event_id"] == str(event.event_id)


def test_me_and_logout_all_revoke_every_session(client, db, user, monkeypatch):
    _prepare_password(user)
    db.commit()

    async def no_risk(*args):
        return None

    async def no_event(*args):
        return True

    monkeypatch.setattr(auth_module, "_pre_token_risk", no_risk)
    monkeypatch.setattr(auth_module, "_send_login_event", no_event)

    login = client.post(
        "/api/v1/auth/login",
        json={"username": user.username, "password": "password123"},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == user.username
    assert "USER" in me.json()["roles"]

    db.add(Session(user_id=user.id, access_token_hash="second", expires_at=user.created_at))
    db.commit()
    response = client.post(
        "/api/v1/auth/logout-all",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert db.query(Session).filter(
        Session.user_id == user.id,
        Session.revoked_at.is_(None),
    ).count() == 0


def test_refresh_rotates_both_tokens_without_extending_expiry(client, db, user, monkeypatch):
    _prepare_password(user)
    db.commit()

    async def no_risk(*args):
        return None

    async def no_event(*args):
        return True

    monkeypatch.setattr(auth_module, "_pre_token_risk", no_risk)
    monkeypatch.setattr(auth_module, "_send_login_event", no_event)
    login = client.post(
        "/api/v1/auth/login",
        json={"username": user.username, "password": "password123"},
    )
    assert login.status_code == 200
    payload = login.json()
    session_id = UUID(payload["session_id"])
    original_expiry = db.query(Session).filter(Session.id == session_id).one().expires_at

    refreshed = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": payload["refresh_token"]},
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"] != payload["access_token"]
    assert refreshed.json()["refresh_token"] != payload["refresh_token"]
    assert db.query(Session).filter(Session.id == session_id).one().expires_at == original_expiry

    replay = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": payload["refresh_token"]},
    )
    assert replay.status_code == 401


def test_email_otp_delivery_and_verification_lifecycle(client, db, user, monkeypatch):
    _prepare_password(user)
    user.admin_mfa_required = True
    db.commit()
    delivered = {}

    async def no_risk(*args):
        return None

    async def capture_email(recipient, otp):
        delivered["recipient"] = recipient
        delivered["otp"] = otp

    async def no_event(*args):
        return True

    monkeypatch.setattr(auth_module, "_pre_token_risk", no_risk)
    monkeypatch.setattr(auth_module, "_send_otp_email", capture_email)
    monkeypatch.setattr(auth_module, "_send_login_event", no_event)
    login = client.post(
        "/api/v1/auth/login",
        json={"username": user.username, "password": "password123"},
    )
    assert login.status_code == 200
    transaction_id = login.json()["session_id"]
    assert delivered["recipient"] == user.email
    assert len(delivered["otp"]) == 6

    notification = db.query(MfaNotification).one()
    assert notification.delivered_at is not None
    assert db.query(MfaTransaction).one().status == "pending"

    verified = client.post(
        "/api/v1/auth/mfa/verify",
        json={"session_id": transaction_id, "mfa_code": delivered["otp"]},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["access_token"]
    assert db.query(MfaTransaction).one().status == "completed"


def test_protective_action_idempotency_key_is_audit_backed(client, db, user):
    headers = {"X-Internal-Secret": "test-internal-secret-at-least-32-characters-long"}
    body = {
        "action": "LOCK_USER",
        "target_user_id": str(user.id),
        "reason": "risk",
        "idempotency_key": "evt-sony-001",
    }
    first = client.post("/api/v1/internal/actions", json=body, headers=headers)
    second = client.post("/api/v1/internal/actions", json=body, headers=headers)
    assert first.status_code == 200
    assert first.json()["status"] == "applied"
    assert second.status_code == 200
    assert second.json()["status"] == "already_applied"
    assert second.json()["details"]["deduplicated"] is True
    assert db.query(AuditLog).filter(
        AuditLog.action == "protective_action:LOCK_USER",
        AuditLog.change_reason == "idempotency:evt-sony-001",
    ).count() == 1


def test_security_admin_can_list_assign_and_audit(client, db, user, monkeypatch):
    token = _admin_token(client, db, monkeypatch, user)
    headers = {"Authorization": f"Bearer {token}"}

    listing = client.get("/api/v1/admin/users", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 2

    assignment = client.post(
        f"/api/v1/admin/users/{user.id}/roles",
        json={"role": "SECURITY_ADMIN"},
        headers=headers,
    )
    assert assignment.status_code == 200, assignment.text
    assert "SECURITY_ADMIN" in assignment.json()["roles"]

    logs = client.get(
        "/api/v1/admin/audit-logs?action=assign_role",
        headers=headers,
    )
    assert logs.status_code == 200
    assert logs.json()["total"] == 1


def test_non_admin_cannot_use_security_admin_endpoints(client, user):
    response = client.get("/api/v1/admin/users")
    assert response.status_code == 401


def test_new_device_requires_existing_device_approval_before_session(
    client, db, user, monkeypatch
):
    """A new device cannot self-trust; a familiar session must approve it."""
    _prepare_password(user)
    db.commit()

    async def no_risk(*args):
        return None

    async def no_event(*args):
        return True

    monkeypatch.setattr(auth_module, "_pre_token_risk", no_risk)
    monkeypatch.setattr(auth_module, "_send_login_event", no_event)

    known_headers = {"User-Agent": "KnownBrowser/1.0"}
    login = client.post(
        "/api/v1/auth/login",
        json={"username": user.username, "password": "password123"},
        headers=known_headers,
    )
    assert login.status_code == 200, login.text
    known_token = login.json()["access_token"]

    new_headers = {"User-Agent": "NewBrowser/1.0"}
    pending = client.post(
        "/api/v1/devices/pending",
        json={
            "username": user.username,
            "password": "password123",
            "device_name": "New laptop",
        },
        headers=new_headers,
    )
    assert pending.status_code == 202, pending.text
    request_id = pending.json()["request_id"]
    assert db.query(UserTrustedDevice).count() == 0

    approval = client.post(
        f"/api/v1/devices/pending/{request_id}/approve",
        headers={"Authorization": f"Bearer {known_token}", **known_headers},
    )
    assert approval.status_code == 200, approval.text
    assert approval.json()["status"] == "approved"
    assert db.query(UserTrustedDevice).count() == 1

    complete = client.post(
        f"/api/v1/devices/pending/{request_id}/complete",
        headers=new_headers,
    )
    assert complete.status_code == 200, complete.text
    assert complete.json()["access_token"]
    transaction = db.query(MfaTransaction).filter(MfaTransaction.id == UUID(request_id)).one()
    assert transaction.consumed_at is not None

    replay = client.post(
        f"/api/v1/devices/pending/{request_id}/complete",
        headers=new_headers,
    )
    assert replay.status_code == 409


def test_trusted_device_approval_rejects_unfamiliar_ip(client, db, user, monkeypatch):
    _prepare_password(user)
    db.commit()

    async def no_risk(*args):
        return None

    async def no_event(*args):
        return True

    monkeypatch.setattr(auth_module, "_pre_token_risk", no_risk)
    monkeypatch.setattr(auth_module, "_send_login_event", no_event)
    login = client.post(
        "/api/v1/auth/login",
        json={"username": user.username, "password": "password123"},
    )
    assert login.status_code == 200
    pending = client.post(
        "/api/v1/devices/pending",
        json={"username": user.username, "password": "password123"},
        headers={"User-Agent": "NewBrowser/1.0"},
    )
    assert pending.status_code == 202

    from app import devices as devices_module

    monkeypatch.setattr(devices_module, "get_client_ip", lambda request: "203.0.113.99")
    response = client.post(
        f"/api/v1/devices/pending/{pending.json()['request_id']}/approve",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert response.status_code == 403
    assert db.query(UserTrustedDevice).count() == 0


def test_admin_mfa_wins_over_trusted_device_request(client, db, user, monkeypatch):
    _prepare_password(user)
    user.admin_mfa_required = True
    db.commit()

    async def no_risk(*args):
        return None

    monkeypatch.setattr(auth_module, "_pre_token_risk", no_risk)
    response = client.post(
        "/api/v1/devices/pending",
        json={"username": user.username, "password": "password123"},
    )
    assert response.status_code == 409
    assert db.query(UserTrustedDevice).count() == 0


def test_existing_trusted_device_does_not_bypass_admin_mfa(client, db, user, monkeypatch):
    _prepare_password(user)
    db.commit()
    delivered = {}

    async def no_risk(*args):
        return None

    async def no_event(*args):
        return True

    async def capture_email(recipient, otp):
        delivered["otp"] = otp

    monkeypatch.setattr(auth_module, "_pre_token_risk", no_risk)
    monkeypatch.setattr(auth_module, "_send_login_event", no_event)
    monkeypatch.setattr(auth_module, "_send_otp_email", capture_email)

    first = client.post(
        "/api/v1/auth/login",
        json={"username": user.username, "password": "password123"},
        headers={"User-Agent": "KnownBrowser/1.0"},
    )
    assert first.status_code == 200
    trusted = client.post(
        "/api/v1/devices",
        headers={
            "Authorization": f"Bearer {first.json()['access_token']}",
            "User-Agent": "KnownBrowser/1.0",
        },
        json={},
    )
    assert trusted.status_code == 200, trusted.text

    user.admin_mfa_required = True
    db.commit()
    second = client.post(
        "/api/v1/auth/login",
        json={"username": user.username, "password": "password123"},
        headers={"User-Agent": "KnownBrowser/1.0"},
    )
    assert second.status_code == 200
    assert second.json()["mfa_required"] is True
    assert delivered["otp"]

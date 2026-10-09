"""Tests for the Trusted Device Management feature (UC-05).

These tests cover the full success-path lifecycle:
    A. POST /api/v1/devices — create a trusted device
    B. response contains device id
    C. DB row belongs to authenticated user
    D. device_fingerprint is populated
    E. same device registered again — idempotent update, no duplicate
    F. GET /api/v1/devices — lists created device
    G. POST /api/v1/devices/check with matching fingerprint — trusted==true
    H. DELETE /api/v1/devices/{id} — removes user's own device
    I. DELETE /api/v1/devices/all — removes all user's devices
    J. another user cannot delete another user's device

Also verifies fingerprint determinism (same headers → same fingerprint,
different headers → different fingerprint) and the fingerprint helpers.

The ``conftest.py`` session-scoped fixture provides a valid INTERNAL_SECRET,
so internal endpoints are accessible.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Role, Session, User, UserRole, UserTrustedDevice
from app.authz import hash_token


# =============================================================================
# Local fixtures (role_user is defined in test_rbac.py; repeat here so this
# file is self-contained and does not depend on test_rbac.py being loaded first)
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


# =============================================================================
# Helpers
# =============================================================================

def _token_for_user(db, user) -> str:
    """Return a valid bearer token for ``user`` with a unique token per user."""
    # Use a unique raw token per user so token hashes are distinct.
    raw = f"trusted-device-test-token-{user.id}"
    token_hash = hash_token(raw)
    sess = Session(
        user_id=user.id,
        access_token_hash=token_hash,
        refresh_token_hash=token_hash,
        user_agent="test-agent",
        expires_at=datetime.utcnow() + timedelta(hours=1),
        last_activity_at=datetime.utcnow(),
    )
    db.add(sess)
    db.commit()
    return raw


# =============================================================================
# A–F: Trust device — create, idempotent, list
# =============================================================================

def test_trust_device_creates_row_and_returns_id(client, db, user):
    """POST /api/v1/devices creates a UserTrustedDevice row and returns its id."""
    token = _token_for_user(db, user)
    resp = client.post(
        "/api/v1/devices",
        json={"device_name": "Test Laptop"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "id" in body
    device_id = body["id"]

    # C: row belongs to authenticated user
    row = db.query(UserTrustedDevice).filter(
        UserTrustedDevice.id == UUID(device_id)
    ).first()
    assert row is not None
    assert str(row.user_id) == str(user.id)
    assert row.device_name == "Test Laptop"


def test_trust_device_populates_fingerprint_and_ip(client, db, user):
    """POST /api/v1/devices stores a hashed fingerprint and the client IP."""
    token = _token_for_user(db, user)
    resp = client.post(
        "/api/v1/devices",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    device_id = resp.json()["id"]
    row = db.query(UserTrustedDevice).filter(
        UserTrustedDevice.id == UUID(device_id)
    ).first()

    # D: device_fingerprint is populated
    assert row.device_fingerprint is not None
    assert len(row.device_fingerprint) == 64  # SHA-256 hex digest

    # IP is recorded (TestClient uses 127.0.0.1 by default)
    assert row.last_ip is not None


def test_trust_device_idempotent_no_duplicate(client, db, user):
    """Registering the same device twice updates the existing row, not a new one."""
    token = _token_for_user(db, user)
    headers = {"Authorization": f"Bearer {token}"}

    r1 = client.post("/api/v1/devices", json={}, headers=headers)
    assert r1.status_code == 200
    id1 = r1.json()["id"]

    r2 = client.post("/api/v1/devices", json={"device_name": "Updated Laptop"}, headers=headers)
    assert r2.status_code == 200
    id2 = r2.json()["id"]

    # E: same id returned (not a new row)
    assert id1 == id2
    assert r2.json()["message"] == "Device already trusted, updated expiry"

    # One row total for this user
    count = db.query(UserTrustedDevice).filter(
        UserTrustedDevice.user_id == user.id
    ).count()
    assert count == 1


def test_list_devices_returns_created_device(client, db, user):
    """F: GET /api/v1/devices returns the created trusted device."""
    token = _token_for_user(db, user)
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = client.post("/api/v1/devices", json={"device_name": "Test Laptop"}, headers=headers)
    assert create_resp.status_code == 200

    list_resp = client.get("/api/v1/devices", headers=headers)
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["total"] == 1
    assert body["devices"][0]["id"] == create_resp.json()["id"]
    assert body["devices"][0]["device_name"] == "Test Laptop"


# =============================================================================
# G: Device check
# =============================================================================

def test_device_check_returns_trusted_true_for_same_fingerprint(client, db, user):
    """G: POST /api/v1/devices/check with matching headers returns trusted==true."""
    token = _token_for_user(db, user)
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "Mozilla/5.0 TestBrowser",
        "Accept-Language": "en-US",
        "Accept-Encoding": "gzip",
    }

    # Register the device first so it exists.
    client.post("/api/v1/devices", json={}, headers=headers)

    # Check — same headers → same fingerprint → trusted.
    check_resp = client.post("/api/v1/devices/check", json={}, headers=headers)
    assert check_resp.status_code == 200
    body = check_resp.json()
    assert body["trusted"] is True
    assert "device_id" in body


def test_device_check_returns_trusted_false_for_unknown_fingerprint(client, db, user):
    """A device that was never registered returns trusted==false."""
    token = _token_for_user(db, user)
    headers = {"Authorization": f"Bearer {token}"}

    check_resp = client.post("/api/v1/devices/check", json={}, headers=headers)
    assert check_resp.status_code == 200
    assert check_resp.json()["trusted"] is False


# =============================================================================
# H–J: Delete and ownership
# =============================================================================

def test_delete_device_removes_own_device(client, db, user):
    """H: DELETE /api/v1/devices/{id} removes the user's own device."""
    token = _token_for_user(db, user)
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = client.post("/api/v1/devices", json={}, headers=headers)
    assert create_resp.status_code == 200, f"create failed: {create_resp.status_code} {create_resp.json()}"
    device_id = create_resp.json()["id"]

    # Verify the row exists before delete
    row = db.query(UserTrustedDevice).filter(UserTrustedDevice.id == UUID(device_id)).first()
    assert row is not None

    del_resp = client.delete(f"/api/v1/devices/{device_id}", headers=headers)
    assert del_resp.status_code == 204

    assert db.query(UserTrustedDevice).filter(UserTrustedDevice.id == UUID(device_id)).first() is None


def test_delete_device_nonexistent_returns_404(client, db, user):
    """Deleting a device that does not exist returns 404."""
    token = _token_for_user(db, user)
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.delete(f"/api/v1/devices/{'00000000-0000-0000-0000-000000000000'}", headers=headers)
    assert resp.status_code == 404


def test_delete_all_removes_all_user_devices(client, db, user):
    """I: DELETE /api/v1/devices/all removes all trusted devices for the user."""
    token = _token_for_user(db, user)
    headers = {"Authorization": f"Bearer {token}"}

    # Create two devices with different fingerprints.
    # The fingerprint is derived from User-Agent, Accept-Language, Accept-Encoding.
    r1 = client.post(
        "/api/v1/devices", json={"device_name": "Device 1"},
        headers={**headers, "User-Agent": "Chrome/120"},
    )
    r2 = client.post(
        "/api/v1/devices", json={"device_name": "Device 2"},
        headers={**headers, "User-Agent": "Firefox/121"},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200

    count_before = db.query(UserTrustedDevice).filter(
        UserTrustedDevice.user_id == user.id
    ).count()
    assert count_before == 2

    del_all_resp = client.delete("/api/v1/devices/all", headers=headers)
    assert del_all_resp.status_code == 204

    count_after = db.query(UserTrustedDevice).filter(
        UserTrustedDevice.user_id == user.id
    ).count()
    assert count_after == 0


def test_cannot_delete_another_users_device(client, db, user, role_user):
    """J: User A cannot delete User B's trusted device."""
    # User B registers a device.
    token_b = _token_for_user(db, role_user)
    headers_b = {"Authorization": f"Bearer {token_b}"}
    create_resp = client.post("/api/v1/devices", json={}, headers=headers_b)
    device_id = create_resp.json()["id"]

    # User A tries to delete it.
    token_a = _token_for_user(db, user)
    headers_a = {"Authorization": f"Bearer {token_a}"}
    del_resp = client.delete(f"/api/v1/devices/{device_id}", headers=headers_a)
    assert del_resp.status_code == 404, "Cannot delete another user's device"

    # Device is still there for User B.
    db.expire_all()
    assert db.query(UserTrustedDevice).filter(UserTrustedDevice.id == UUID(device_id)).first() is not None


# =============================================================================
# Fingerprint determinism tests
# =============================================================================

def test_fingerprint_deterministic_same_headers(client, db, user):
    """Same headers produce the same fingerprint (and same stored hash)."""
    token = _token_for_user(db, user)
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "SameBrowser/1.0",
        "Accept-Language": "en-US",
        "Accept-Encoding": "gzip",
    }

    r1 = client.post("/api/v1/devices", json={}, headers=headers)
    assert r1.status_code == 200
    id1 = r1.json()["id"]

    # Second registration with identical headers is idempotent.
    r2 = client.post("/api/v1/devices", json={}, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["id"] == id1


def test_fingerprint_changes_with_user_agent(client, db, user):
    """Different User-Agent → different fingerprint → new device row."""
    token = _token_for_user(db, user)

    r1 = client.post(
        "/api/v1/devices", json={},
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "Chrome/120",
            "Accept-Language": "en",
            "Accept-Encoding": "gzip",
        },
    )
    assert r1.status_code == 200
    id1 = r1.json()["id"]

    r2 = client.post(
        "/api/v1/devices", json={},
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "Firefox/121",
            "Accept-Language": "en",
            "Accept-Encoding": "gzip",
        },
    )
    assert r2.status_code == 200
    id2 = r2.json()["id"]

    # Different device rows.
    assert id1 != id2

    count = db.query(UserTrustedDevice).filter(
        UserTrustedDevice.user_id == user.id
    ).count()
    assert count == 2


def test_hash_fingerprint_produces_sha256(client, db, user):
    """hash_fingerprint returns a SHA-256 hex digest (64 chars)."""
    token = _token_for_user(db, user)
    resp = client.post(
        "/api/v1/devices", json={},
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "TestAgent/1.0",
            "Accept-Language": "en",
            "Accept-Encoding": "gzip",
        },
    )
    assert resp.status_code == 200
    device_id = resp.json()["id"]
    row = db.query(UserTrustedDevice).filter(
        UserTrustedDevice.id == UUID(device_id)
    ).first()
    assert len(row.device_fingerprint) == 64
    # Verify it is a valid SHA-256 hex string.
    assert all(c in "0123456789abcdef" for c in row.device_fingerprint)


def test_generate_device_fingerprint_is_deterministic():
    """generate_device_fingerprint returns consistent results for the same headers."""
    from starlette.requests import Request
    from app.devices import generate_device_fingerprint

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "query_string": b"",
        "headers": [
            (b"user-agent", b"Mozilla/5.0"),
            (b"accept-language", b"en-US"),
            (b"accept-encoding", b"gzip"),
        ],
    }

    fp1 = generate_device_fingerprint(Request(scope))
    fp2 = generate_device_fingerprint(Request(scope))
    assert fp1 == fp2


def test_generate_device_fingerprint_differs_with_different_headers():
    """Different headers produce different fingerprints."""
    from starlette.requests import Request
    from app.devices import generate_device_fingerprint

    chrome_scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "query_string": b"",
        "headers": [(b"user-agent", b"Chrome/120"), (b"accept-language", b"en"), (b"accept-encoding", b"gzip")],
    }
    firefox_scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "query_string": b"",
        "headers": [(b"user-agent", b"Firefox/121"), (b"accept-language", b"en"), (b"accept-encoding", b"gzip")],
    }

    assert generate_device_fingerprint(Request(chrome_scope)) != generate_device_fingerprint(Request(firefox_scope))


# =============================================================================
# Route-table sanity checks
# =============================================================================

def test_only_one_delete_all_route(client, db, user, app):
    """Exactly one DELETE /api/v1/devices/all route is registered."""
    from fastapi.routing import APIRoute

    matching = [
        r
        for r in app.routes
        if isinstance(r, APIRoute)
        and r.path == "/api/v1/devices/all"
        and "DELETE" in r.methods
    ]
    assert len(matching) == 1, (
        f"Expected 1 DELETE /api/v1/devices/all route, found {len(matching)}: "
        f"[(r.path, r.methods) for r in matching]"
    )

    # Functional evidence: DELETE /all still works.
    token = _token_for_user(db, user)
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = client.post("/api/v1/devices", json={}, headers=headers)
    assert create_resp.status_code == 200

    del_all_resp = client.delete("/api/v1/devices/all", headers=headers)
    assert del_all_resp.status_code == 204

    # DELETE /{device_id} must also still work (different route).
    create_resp2 = client.post("/api/v1/devices", json={}, headers=headers)
    assert create_resp2.status_code == 200
    device_id = create_resp2.json()["id"]

    del_resp = client.delete(f"/api/v1/devices/{device_id}", headers=headers)
    assert del_resp.status_code == 204


def test_delete_device_malformed_id_returns_422(client, db, user):
    """DELETE /api/v1/devices/{invalid} with a non-UUID device_id returns 422."""
    token = _token_for_user(db, user)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.delete("/api/v1/devices/not-a-uuid", headers=headers)
    assert resp.status_code == 422, f"expected 422, got {resp.status_code}"

    # No device row was created or modified.
    count = db.query(UserTrustedDevice).filter(
        UserTrustedDevice.user_id == user.id
    ).count()
    assert count == 0

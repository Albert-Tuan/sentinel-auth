"""
Trusted Device Management.
Implements "Remember this device" feature.

Per Bảng Yêu Cầu Chức Năng Nghiệp Vụ v2:
- UC-05: Quản lý thiết bị tin cậy
- U-QĐ-05: Quy định thiết bị tin cậy

Features:
    - Register device as trusted (metadata only; required MFA is not bypassed)
- List trusted devices
- Remove trusted device
- Auto-expire based on TTL
"""
import hashlib
import ipaddress
from datetime import datetime, timedelta
from typing import Optional, List
from uuid import UUID

from app.client_ip import get_client_ip
from app.device_fingerprint import (
    fingerprint_hash_from_headers,
    fingerprint_material_from_headers,
)
from app.device_fingerprint import hash_fingerprint as hash_fingerprint_raw
from app.time_utils import utc_now, as_utc

from fastapi import APIRouter, HTTPException, Header, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.db import get_core_db
from app.models import AuditLog, MfaTransaction, RateLimit, User, Session, UserTrustedDevice
from app.authz import get_current_auth_context, AuthContext
from app.schemas import LoginResponse

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


# =============================================================================
# Device fingerprinting helpers
#
# Design: derive a deterministic fingerprint from non-invasive request headers,
# then store a SHA-256 hash.  This is intentionally lightweight — no browser
# canvas, WebGL, or audio fingerprinting.  It is sufficient to distinguish
# a browser/OS combination without tracking individuals.
#
# The canonical implementation lives in ``app/device_fingerprint`` so that
# Core (``app.auth``) and Detection (``app.detection``) share ONE algorithm
# instead of growing a second one.  The helpers below are thin wrappers kept
# for backward compatibility with existing call sites and tests.

def generate_device_fingerprint(request: Request) -> str:
    """Derive a deterministic device fingerprint from request headers.

    Combines the User-Agent, Accept-Language and Accept-Encoding headers into a
    single string and returns it.  The result is hashed before storage so the
    raw header values never appear in the database.
    """
    return fingerprint_material_from_headers(request.headers)


def hash_fingerprint(fingerprint: str) -> str:
    """Return the SHA-256 hex digest of ``fingerprint``."""
    return hash_fingerprint_raw(fingerprint)


# =============================================================================
# Request/Response Schemas
# =============================================================================

class TrustedDeviceItem(BaseModel):
    id: str
    device_name: Optional[str] = None
    device_fingerprint: str
    last_ip: Optional[str] = None
    last_user_agent: Optional[str] = None
    last_used_at: datetime
    expires_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TrustedDeviceList(BaseModel):
    devices: List[TrustedDeviceItem]
    total: int


class TrustDeviceRequest(BaseModel):
    device_name: Optional[str] = Field(None, max_length=100)
    remember_for_days: Optional[int] = Field(30, ge=1, le=365, description="Days until device expires")


class TrustDeviceResponse(BaseModel):
    id: str
    device_name: Optional[str] = None
    message: str


class DeviceFingerprint(BaseModel):
    """Client-provided device fingerprint for registration."""
    fingerprint: str = Field(..., min_length=16, description="Device fingerprint hash")


class PendingTrustedDeviceRequest(BaseModel):
    """Credentials used to ask an already-known device to approve this device."""

    username: str
    password: str
    device_name: Optional[str] = Field(None, max_length=100)


class PendingTrustedDeviceResponse(BaseModel):
    request_id: UUID
    status: str
    expires_at: datetime
    message: str


class TrustedDeviceApprovalResponse(BaseModel):
    request_id: UUID
    device_id: UUID
    status: str
    expires_at: datetime


def _canonical_ip(value: Optional[str]) -> Optional[str]:
    """Return a canonical IP, or ``None`` for unknown/test-only peers."""
    if not value or value == "unknown":
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def _same_ip(expected: Optional[str], actual: Optional[str]) -> bool:
    """Compare IPs without accepting an unknown address as familiar."""
    if not expected or not actual:
        return False
    expected_norm = _canonical_ip(expected)
    actual_norm = _canonical_ip(actual)
    if expected_norm is not None and actual_norm is not None:
        return expected_norm == actual_norm
    # SQLite/TestClient fixtures may use a stable synthetic peer label.  This
    # branch is deliberately exact-match only; production INET values always
    # take the canonical-IP branch above.
    return expected == actual


def _session_ip_matches(ctx: AuthContext, client_ip: str) -> bool:
    """Require an authenticated session to be used from its familiar IP."""
    session_ip = getattr(getattr(ctx.session, "ip_address", None), "ip_address", None)
    return _same_ip(session_ip, client_ip)


def _device_fingerprint_hash(request: Request) -> str:
    return hash_fingerprint(generate_device_fingerprint(request))


def _audit_device_action(
    db,
    *,
    actor_id,
    action: str,
    resource_id,
    after_state: Optional[dict] = None,
    request: Optional[Request] = None,
) -> None:
    """Persist a device-security audit without recording raw credentials."""
    db.add(
        AuditLog(
            actor_id=actor_id,
            actor_type="user",
            action=action,
            resource="trusted_device",
            resource_id=resource_id,
            after_state=after_state,
            ip_address=get_client_ip(request) if request else None,
            user_agent=request.headers.get("User-Agent") if request else None,
        )
    )


# =============================================================================
# Trusted Device Endpoints
# =============================================================================

@router.get("", response_model=TrustedDeviceList)
async def list_trusted_devices(
    request: Request,
    ctx: AuthContext = Depends(get_current_auth_context),
    db=Depends(get_core_db),
) -> TrustedDeviceList:
    """
    List all trusted devices for current user (UC-05).

    Per U-QĐ-05: User chỉ xem được thiết bị của chính mình.
    Uses canonical get_current_auth_context() for authentication.
    """
    devices = db.query(UserTrustedDevice).filter(
        UserTrustedDevice.user_id == ctx.user.id
    ).order_by(UserTrustedDevice.last_used_at.desc()).all()

    return TrustedDeviceList(
        devices=[TrustedDeviceItem.model_validate({**vars(d), "id": str(d.id)}) for d in devices],
        total=len(devices),
    )


@router.post("", response_model=TrustDeviceResponse)
async def trust_device(
    request: Request,
    body: TrustDeviceRequest,
    ctx: AuthContext = Depends(get_current_auth_context),
    db=Depends(get_core_db),
) -> TrustDeviceResponse:
    """
    Register current device as trusted (UC-05).

    Per U-QĐ-05: Thiết bị được thêm vào danh sách tin cậy.
    Per U-QĐ-07: Trusted device TTL configurable (default: 30 days).
    Uses canonical get_current_auth_context() for authentication.
    """
    client_ip = get_client_ip(request)
    if not _session_ip_matches(ctx, client_ip):
        raise HTTPException(
            status_code=403,
            detail="Trusted-device confirmation must come from the session's familiar IP",
        )

    # Generate or use provided fingerprint
    fingerprint = generate_device_fingerprint(request)
    fingerprint_hash = hash_fingerprint(fingerprint)

    user_agent = request.headers.get("User-Agent", "")

    # Check if device already trusted
    existing = db.query(UserTrustedDevice).filter(
        UserTrustedDevice.user_id == ctx.user.id,
        UserTrustedDevice.device_fingerprint == fingerprint_hash,
    ).first()

    if existing:
        # Update existing device
        existing.last_ip = client_ip
        existing.last_user_agent = user_agent
        existing.last_used_at = utc_now()
        existing.expires_at = utc_now() + timedelta(days=body.remember_for_days or 30)
        if body.device_name:
            existing.device_name = body.device_name

        _audit_device_action(
            db,
            actor_id=ctx.user.id,
            action="trusted_device_updated",
            resource_id=existing.id,
            after_state={"expires_at": existing.expires_at.isoformat() if existing.expires_at else None},
            request=request,
        )
        db.commit()
        db.refresh(existing)

        return TrustDeviceResponse(
            id=str(existing.id),
            device_name=existing.device_name,
            message="Device already trusted, updated expiry",
        )

    # Create new trusted device
    expires_at = None
    if body.remember_for_days:
        expires_at = utc_now() + timedelta(days=body.remember_for_days)

    device = UserTrustedDevice(
        user_id=ctx.user.id,
        device_fingerprint=fingerprint_hash,
        device_name=body.device_name,
        last_ip=client_ip,
        last_user_agent=user_agent,
        last_used_at=utc_now(),
        expires_at=expires_at,
    )
    db.add(device)
    db.flush()
    _audit_device_action(
        db,
        actor_id=ctx.user.id,
        action="trusted_device_created",
        resource_id=device.id,
        after_state={"expires_at": device.expires_at.isoformat() if device.expires_at else None},
        request=request,
    )
    db.commit()
    db.refresh(device)

    return TrustDeviceResponse(
        id=str(device.id),
        device_name=device.device_name,
        message=f"Device trusted until {expires_at.strftime('%Y-%m-%d') if expires_at else 'never'}",
    )


@router.post("/pending", response_model=PendingTrustedDeviceResponse, status_code=202)
async def request_trusted_device_approval(
    body: PendingTrustedDeviceRequest,
    request: Request,
    db=Depends(get_core_db),
) -> PendingTrustedDeviceResponse:
    """Ask a currently logged-in device to approve this new device.

    The new device proves knowledge of the password, but it cannot create a
    trusted-device row or receive a session until an existing session for the
    same user approves the request.  Admin-persistent MFA and Detection's
    high/critical MFA gate always take precedence over this convenience flow.
    """
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHash, VerifyMismatchError

    from app.auth import _pre_token_risk

    client_ip = get_client_ip(request)
    bound_ip = _canonical_ip(client_ip) or client_ip
    if not bound_ip or bound_ip == "unknown":
        raise HTTPException(status_code=400, detail="A valid client IP is required")

    # This endpoint verifies a password, so it gets its own counter rather
    # than relying on the normal login counter.  Persist the increment before
    # credential verification so failed attempts cannot roll it back.
    now = utc_now()
    window_start = now - timedelta(minutes=1)
    rate = (
        db.query(RateLimit)
        .filter(
            RateLimit.ip_address == client_ip,
            RateLimit.action == "trusted_device_approval",
        )
        .with_for_update()
        .first()
    )
    if rate and as_utc(rate.window_start) >= window_start and rate.count >= rate.max_count:
        raise HTTPException(status_code=429, detail="Too many device approval requests")
    if rate is None:
        rate = RateLimit(
            ip_address=client_ip,
            action="trusted_device_approval",
            count=1,
            max_count=5,
            window_start=now,
        )
        db.add(rate)
    elif as_utc(rate.window_start) < window_start:
        rate.window_start = now
        rate.count = 1
    else:
        rate.count += 1
    db.commit()

    user = db.query(User).filter(User.username == body.username).first()
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    try:
        PasswordHasher().verify(user.password_hash, body.password)
    except (VerifyMismatchError, InvalidHash):
        raise HTTPException(status_code=401, detail="Invalid credentials") from None

    if user.status == "locked":
        raise HTTPException(status_code=423, detail="Account is locked")
    if user.admin_mfa_required or user.detection_mfa_once:
        raise HTTPException(
            status_code=409,
            detail="Complete the required MFA through the normal login flow before trusting a device",
        )

    risk_level = await _pre_token_risk(
        user,
        client_ip,
        request.headers.get("User-Agent"),
    )
    if risk_level is not None:
        raise HTTPException(
            status_code=409,
            detail="Detection requires MFA; trusted-device approval cannot bypass it",
        )

    fingerprint_hash = _device_fingerprint_hash(request)
    now = utc_now()
    existing = (
        db.query(UserTrustedDevice)
        .filter(
            UserTrustedDevice.user_id == user.id,
            UserTrustedDevice.device_fingerprint == fingerprint_hash,
        )
        .first()
    )
    if existing and (existing.expires_at is None or as_utc(existing.expires_at) > now) and _same_ip(existing.last_ip, client_ip):
        return PendingTrustedDeviceResponse(
            request_id=existing.id,
            status="already_trusted",
            expires_at=existing.expires_at or now,
            message="This device is already trusted",
        )

    pending = (
        db.query(MfaTransaction)
        .filter(
            MfaTransaction.user_id == user.id,
            MfaTransaction.mfa_type == "trusted_device",
            MfaTransaction.status == "pending",
            MfaTransaction.trusted_device_fingerprint == fingerprint_hash,
        )
        .with_for_update()
        .first()
    )
    expires_at = now + timedelta(minutes=5)
    if pending and as_utc(pending.expires_at) > now:
        return PendingTrustedDeviceResponse(
            request_id=pending.id,
            status="pending",
            expires_at=pending.expires_at,
            message="Approval is pending on an existing signed-in device",
        )

    if pending:
        pending.status = "expired"

    pending = MfaTransaction(
        user_id=user.id,
        mfa_type="trusted_device",
        status="pending",
        bound_ip=bound_ip,
        trusted_device_fingerprint=fingerprint_hash,
        trusted_device_name=body.device_name,
        trusted_device_user_agent=request.headers.get("User-Agent"),
        expires_at=expires_at,
    )
    db.add(pending)
    db.flush()
    _audit_device_action(
        db,
        actor_id=user.id,
        action="trusted_device_requested",
        resource_id=pending.id,
        after_state={"expires_at": expires_at.isoformat()},
        request=request,
    )
    db.commit()
    return PendingTrustedDeviceResponse(
        request_id=pending.id,
        status="pending",
        expires_at=expires_at,
        message="Approval is pending on an existing signed-in device",
    )


@router.post("/pending/{request_id}/approve", response_model=TrustedDeviceApprovalResponse)
async def approve_trusted_device(
    request_id: UUID,
    request: Request,
    ctx: AuthContext = Depends(get_current_auth_context),
    db=Depends(get_core_db),
) -> TrustedDeviceApprovalResponse:
    """Approve a new device from a familiar, already-authenticated session."""
    pending = (
        db.query(MfaTransaction)
        .filter(
            MfaTransaction.id == request_id,
            MfaTransaction.mfa_type == "trusted_device",
        )
        .with_for_update()
        .first()
    )
    if pending is None or pending.user_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="Trusted-device request not found")
    now = utc_now()
    if as_utc(pending.expires_at) <= now:
        pending.status = "expired"
        db.commit()
        raise HTTPException(status_code=410, detail="Trusted-device request expired")
    if pending.status in {"expired", "failed"}:
        raise HTTPException(status_code=410, detail="Trusted-device request is no longer valid")
    if not _session_ip_matches(ctx, get_client_ip(request)):
        raise HTTPException(
            status_code=403,
            detail="Approval must come from the current session's familiar IP",
        )

    device = (
        db.query(UserTrustedDevice)
        .filter(
            UserTrustedDevice.user_id == ctx.user.id,
            UserTrustedDevice.device_fingerprint == pending.trusted_device_fingerprint,
        )
        .with_for_update()
        .first()
    )
    device_expires_at = now + timedelta(days=30)
    if device is None:
        device = UserTrustedDevice(
            user_id=ctx.user.id,
            device_fingerprint=pending.trusted_device_fingerprint,
            device_name=pending.trusted_device_name,
            last_ip=pending.bound_ip,
            last_user_agent=pending.trusted_device_user_agent,
            last_used_at=now,
            expires_at=device_expires_at,
        )
        db.add(device)
        db.flush()
    else:
        device.device_name = pending.trusted_device_name or device.device_name
        device.last_ip = pending.bound_ip
        device.last_user_agent = pending.trusted_device_user_agent
        device.last_used_at = now
        device.expires_at = device_expires_at

    pending.status = "completed"
    _audit_device_action(
        db,
        actor_id=ctx.user.id,
        action="trusted_device_approved",
        resource_id=device.id,
        after_state={"request_id": str(pending.id), "expires_at": device_expires_at.isoformat()},
        request=request,
    )
    db.commit()
    return TrustedDeviceApprovalResponse(
        request_id=pending.id,
        device_id=device.id,
        status="approved",
        expires_at=device_expires_at,
    )


@router.post("/pending/{request_id}/complete", response_model=LoginResponse)
async def complete_trusted_device_login(
    request_id: UUID,
    request: Request,
    db=Depends(get_core_db),
) -> LoginResponse:
    """Finish a trusted-device login after an existing device approved it."""
    from app.auth import _create_session, _login_event, _pre_token_risk, _send_login_event

    pending = (
        db.query(MfaTransaction)
        .filter(
            MfaTransaction.id == request_id,
            MfaTransaction.mfa_type == "trusted_device",
        )
        .with_for_update()
        .first()
    )
    if pending is None:
        raise HTTPException(status_code=404, detail="Trusted-device request not found")
    if pending.status == "pending":
        raise HTTPException(status_code=409, detail="Trusted-device approval is still pending")
    if pending.status in {"expired", "failed"}:
        raise HTTPException(status_code=410, detail="Trusted-device request is no longer valid")
    now = utc_now()
    if pending.consumed_at is not None:
        raise HTTPException(status_code=409, detail="Trusted-device request already completed")
    if as_utc(pending.expires_at) <= now:
        pending.status = "expired"
        db.commit()
        raise HTTPException(status_code=410, detail="Trusted-device request expired")

    client_ip = get_client_ip(request)
    if not _same_ip(pending.bound_ip, client_ip):
        raise HTTPException(status_code=403, detail="Trusted-device IP does not match the request")
    if _device_fingerprint_hash(request) != pending.trusted_device_fingerprint:
        raise HTTPException(status_code=403, detail="Trusted-device fingerprint does not match the request")

    user = db.query(User).filter(User.id == pending.user_id).first()
    if user is None or user.status != "active":
        raise HTTPException(status_code=401, detail="Account is not active")

    # Re-check at completion time: a newly raised Admin/Detection MFA
    # requirement must win even if the request was approved earlier.
    if user.admin_mfa_required or user.detection_mfa_once:
        pending.status = "failed"
        db.commit()
        raise HTTPException(status_code=409, detail="MFA is required for this login")
    risk_level = await _pre_token_risk(user, client_ip, request.headers.get("User-Agent"))
    if risk_level is not None:
        pending.status = "failed"
        db.commit()
        raise HTTPException(status_code=409, detail="Detection requires MFA for this login")

    pending.consumed_at = now
    result, login_event = await _create_session(
        user,
        client_ip,
        request.headers.get("User-Agent"),
        db,
        # The trusted-device flow already verified the fingerprint, so the
        # event carries the same canonical (hashed) fingerprint.
        device_fingerprint=_device_fingerprint_hash(request),
    )
    _audit_device_action(
        db,
        actor_id=user.id,
        action="trusted_device_login",
        resource_id=pending.id,
        after_state={"session_id": str(result.session_id)},
        request=request,
    )
    db.commit()
    await _send_login_event(login_event)
    return result


@router.delete("/all", status_code=204)
async def untrust_all_devices(
    ctx: AuthContext = Depends(get_current_auth_context),
    db=Depends(get_core_db),
) -> None:
    """
    Remove all trusted devices for current user.
    Security feature: allows user to remotely revoke all trusted devices.
    Uses canonical get_current_auth_context() for authentication.
    """
    db.query(UserTrustedDevice).filter(
        UserTrustedDevice.user_id == ctx.user.id
    ).delete()
    db.commit()


@router.delete("/{device_id}", status_code=204)
async def untrust_device(
    device_id: UUID,
    ctx: AuthContext = Depends(get_current_auth_context),
    db=Depends(get_core_db),
) -> None:
    """
    Remove a device from trusted list (UC-05).

    Per U-QĐ-05: Thiết bị được gỡ khỏi danh sách tin cậy.
    Uses canonical get_current_auth_context() for authentication.
    """
    device = db.query(UserTrustedDevice).filter(
        UserTrustedDevice.user_id == ctx.user.id,
        UserTrustedDevice.id == device_id,
    ).first()

    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    db.delete(device)
    db.commit()


@router.post("/check", response_model=dict)
async def check_device_trusted(
    request: Request,
    authorization: Optional[str] = Header(None),
    db=Depends(get_core_db),
) -> dict:
    """
    Check if current device is trusted.
    Available for device-management UI. Core login does not use this result to
    bypass persistent Admin MFA or a Detection-mandated MFA challenge.

    Contract: no token → trusted=false (optional/public authentication).
    If token is provided, validates it canonically; invalid token → trusted=false.
    """
    # Optional authentication: validate token if provided, but never reject
    user_id = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        from app.authz import hash_token as _hash_token
        token_hash = _hash_token(token)
        session = db.query(Session).filter(
            Session.access_token_hash == token_hash,
            Session.revoked_at.is_(None),
            Session.expires_at > utc_now(),
        ).first()
        if session:
            user = db.query(User).filter(User.id == session.user_id).first()
            if user and user.status == "active":
                user_id = user.id

    if user_id is None:
        return {"trusted": False, "reason": "No token"}

    client_ip = get_client_ip(request)
    fingerprint_hash = _device_fingerprint_hash(request)

    device = db.query(UserTrustedDevice).filter(
        UserTrustedDevice.user_id == user_id,
        UserTrustedDevice.device_fingerprint == fingerprint_hash,
    ).first()

    if not device:
        return {"trusted": False, "reason": "Device not registered"}

    if not _same_ip(device.last_ip, client_ip):
        return {"trusted": False, "reason": "Device used from an unfamiliar IP"}

    # Check expiry — as_utc normalises naive SQLite-persisted values to aware UTC.
    now = utc_now()
    if device.expires_at and as_utc(device.expires_at) < now:
        return {"trusted": False, "reason": "Device expired"}

    # Update last used
    device.last_used_at = now
    device.last_ip = client_ip
    device.last_user_agent = request.headers.get("User-Agent", "")
    db.commit()

    return {
        "trusted": True,
        "device_id": str(device.id),
        "device_name": device.device_name,
        "expires_at": device.expires_at.isoformat() if device.expires_at else None,
    }

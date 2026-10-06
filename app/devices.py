"""
Trusted Device Management.
Implements "Remember this device" feature.

Per Bảng Yêu Cầu Chức Năng Nghiệp Vụ v2:
- UC-05: Quản lý thiết bị tin cậy
- U-QĐ-05: Quy định thiết bị tin cậy

Features:
    - Register device as trusted (skip MFA)
- List trusted devices
- Remove trusted device
- Auto-expire based on TTL
"""
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, List
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Header, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.db import get_db
from app.models import User, Session, UserTrustedDevice
from app.authz import get_current_auth_context, AuthContext

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


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


# =============================================================================
# Trusted Device Endpoints
# =============================================================================

@router.get("", response_model=TrustedDeviceList)
async def list_trusted_devices(
    request: Request,
    ctx: AuthContext = Depends(get_current_auth_context),
    db=Depends(get_db),
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
        devices=[TrustedDeviceItem.model_validate(d) for d in devices],
        total=len(devices),
    )


@router.post("", response_model=TrustDeviceResponse)
async def trust_device(
    request: Request,
    body: TrustDeviceRequest,
    ctx: AuthContext = Depends(get_current_auth_context),
    db=Depends(get_db),
) -> TrustDeviceResponse:
    """
    Register current device as trusted (UC-05).

    Per U-QĐ-05: Thiết bị được thêm vào danh sách tin cậy.
    Per U-QĐ-07: Trusted device TTL configurable (default: 30 days).
    Uses canonical get_current_auth_context() for authentication.
    """
    # Generate or use provided fingerprint
    fingerprint = generate_device_fingerprint(request)
    fingerprint_hash = hash_fingerprint(fingerprint)

    client_ip = get_client_ip(request)
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
        existing.last_used_at = datetime.utcnow()
        existing.expires_at = datetime.utcnow() + timedelta(days=body.remember_for_days or 30)
        if body.device_name:
            existing.device_name = body.device_name

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
        expires_at = datetime.utcnow() + timedelta(days=body.remember_for_days)

    device = UserTrustedDevice(
        user_id=ctx.user.id,
        device_fingerprint=fingerprint_hash,
        device_name=body.device_name,
        last_ip=client_ip,
        last_user_agent=user_agent,
        last_used_at=datetime.utcnow(),
        expires_at=expires_at,
    )
    db.add(device)
    db.commit()
    db.refresh(device)

    return TrustDeviceResponse(
        id=str(device.id),
        device_name=device.device_name,
        message=f"Device trusted until {expires_at.strftime('%Y-%m-%d') if expires_at else 'never'}",
    )


@router.delete("/{device_id}", status_code=204)
async def untrust_device(
    device_id: str,
    ctx: AuthContext = Depends(get_current_auth_context),
    db=Depends(get_db),
) -> None:
    """
    Remove a device from trusted list (UC-05).

    Per U-QĐ-05: Thiết bị được gỡ khỏi danh sách tin cậy.
    Uses canonical get_current_auth_context() for authentication.
    """
    device = db.query(UserTrustedDevice).filter(
        UserTrustedDevice.id == device_id,
        UserTrustedDevice.user_id == ctx.user.id,
    ).first()

    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    db.delete(device)
    db.commit()


@router.post("/check", response_model=dict)
async def check_device_trusted(
    request: Request,
    authorization: Optional[str] = Header(None),
    db=Depends(get_db),
) -> dict:
    """
    Check if current device is trusted.
    Used by auth flow to skip MFA for trusted devices.

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
            Session.expires_at > datetime.utcnow(),
        ).first()
        if session:
            user = db.query(User).filter(User.id == session.user_id).first()
            if user and user.status == "active":
                user_id = user.id

    if user_id is None:
        return {"trusted": False, "reason": "No token"}

    fingerprint = generate_device_fingerprint(request)
    fingerprint_hash = hash_fingerprint(fingerprint)
    client_ip = get_client_ip(request)

    device = db.query(UserTrustedDevice).filter(
        UserTrustedDevice.user_id == user_id,
        UserTrustedDevice.device_fingerprint == fingerprint_hash,
    ).first()

    if not device:
        return {"trusted": False, "reason": "Device not registered"}

    # Check expiry
    now = datetime.utcnow()
    if device.expires_at and device.expires_at < now:
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


@router.delete("/all", status_code=204)
async def untrust_all_devices(
    ctx: AuthContext = Depends(get_current_auth_context),
    db=Depends(get_db),
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

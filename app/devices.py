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
# Helper Functions
# =============================================================================

def hash_fingerprint(fingerprint: str) -> str:
    """Create hash of device fingerprint for storage."""
    return hashlib.sha256(fingerprint.encode()).hexdigest()


def generate_device_fingerprint(request: Request) -> str:
    """
    Generate a device fingerprint from request headers.
    Combines User-Agent and other identifying headers.
    """
    user_agent = request.headers.get("User-Agent", "")
    accept_lang = request.headers.get("Accept-Language", "")
    accept_enc = request.headers.get("Accept-Encoding", "")

    raw = f"{user_agent}:{accept_lang}:{accept_enc}"
    return hashlib.sha256(raw.encode()).hexdigest()


def get_client_ip(request: Request) -> str:
    """Extract client IP from request."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def verify_user_token(
    authorization: Optional[str],
    db: DBSession
) -> tuple[User, Session]:
    """
    Verify user token and return user + session.
    Helper for authenticated endpoints.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")

    token = authorization.split(" ")[1]
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    session = db.query(Session).filter(
        Session.access_token_hash == token_hash,
        Session.revoked_at.is_(None),
        Session.expires_at > datetime.utcnow(),
    ).first()

    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.query(User).filter(User.id == session.user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user, session


# =============================================================================
# Trusted Device Endpoints
# =============================================================================

@router.get("", response_model=TrustedDeviceList)
async def list_trusted_devices(
    request: Request,
    authorization: Optional[str] = Header(None),
    db=Depends(get_db),
) -> TrustedDeviceList:
    """
    List all trusted devices for current user (UC-05).

    Per U-QĐ-05: User chỉ xem được thiết bị của chính mình.
    """
    user, _ = verify_user_token(authorization, db)

    devices = db.query(UserTrustedDevice).filter(
        UserTrustedDevice.user_id == user.id
    ).order_by(UserTrustedDevice.last_used_at.desc()).all()

    return TrustedDeviceList(
        devices=[TrustedDeviceItem.model_validate(d) for d in devices],
        total=len(devices),
    )


@router.post("", response_model=TrustDeviceResponse)
async def trust_device(
    request: Request,
    body: TrustDeviceRequest,
    authorization: Optional[str] = Header(None),
    db=Depends(get_db),
) -> TrustDeviceResponse:
    """
    Register current device as trusted (UC-05).

    Per U-QĐ-05: Thiết bị được thêm vào danh sách tin cậy.
    Per U-QĐ-07: Trusted device TTL configurable (default: 30 days).
    """
    user, _ = verify_user_token(authorization, db)

    # Generate or use provided fingerprint
    fingerprint = generate_device_fingerprint(request)
    fingerprint_hash = hash_fingerprint(fingerprint)

    client_ip = get_client_ip(request)
    user_agent = request.headers.get("User-Agent", "")

    # Check if device already trusted
    existing = db.query(UserTrustedDevice).filter(
        UserTrustedDevice.user_id == user.id,
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
        user_id=user.id,
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
    authorization: Optional[str] = Header(None),
    db=Depends(get_db),
) -> None:
    """
    Remove a device from trusted list (UC-05).

    Per U-QĐ-05: Thiết bị được gỡ khỏi danh sách tin cậy.
    """
    user, _ = verify_user_token(authorization, db)

    device = db.query(UserTrustedDevice).filter(
        UserTrustedDevice.id == device_id,
        UserTrustedDevice.user_id == user.id,
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
    """
    if not authorization or not authorization.startswith("Bearer "):
        return {"trusted": False, "reason": "No token"}

    user, _ = verify_user_token(authorization, db)

    fingerprint = generate_device_fingerprint(request)
    fingerprint_hash = hash_fingerprint(fingerprint)
    client_ip = get_client_ip(request)

    device = db.query(UserTrustedDevice).filter(
        UserTrustedDevice.user_id == user.id,
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
    authorization: Optional[str] = Header(None),
    db=Depends(get_db),
) -> None:
    """
    Remove all trusted devices for current user.
    Security feature: allows user to remotely revoke all trusted devices.
    """
    user, _ = verify_user_token(authorization, db)

    db.query(UserTrustedDevice).filter(
        UserTrustedDevice.user_id == user.id
    ).delete()

    db.commit()

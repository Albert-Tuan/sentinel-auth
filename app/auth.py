"""Authentication endpoints - login, MFA."""
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """Login request payload."""
    username: str
    password: str
    source_ip: Optional[str] = None


class LoginResponse(BaseModel):
    """Login response payload."""
    access_token: str
    refresh_token: str
    mfa_required: bool = False
    session_id: str


class MfaVerifyRequest(BaseModel):
    """MFA verification request."""
    session_id: str
    mfa_code: str


class MfaVerifyResponse(BaseModel):
    """MFA verification response."""
    access_token: str
    refresh_token: str
    session_id: str


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest) -> LoginResponse:
    """
    Authenticate user credentials.

    On success returns tokens. If MFA is required, returns
    mfa_required=True and a pre-auth session.
    """
    pass
    return LoginResponse(access_token="", refresh_token="", mfa_required=False, session_id="")


@router.post("/mfa/verify", response_model=MfaVerifyResponse)
async def mfa_verify(request: MfaVerifyRequest) -> MfaVerifyResponse:
    """
    Verify MFA code for a pre-auth transaction.

    Completes the login flow after MFA challenge is satisfied.
    """
    pass
    return MfaVerifyResponse(access_token="", refresh_token="", session_id="")


@router.post("/refresh")
async def refresh(request: dict) -> dict:
    """Refresh access token using refresh token."""
    pass
    return {}


@router.post("/logout")
async def logout(request: dict) -> dict:
    """Revoke session and tokens."""
    pass
    return {"status": "ok"}

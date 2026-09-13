"""Contract-defined public authentication and self-service session endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse

from app.api.dependencies import (
    app_rate_limiter,
    authentication_service,
    current_identity,
    request_source_ip,
    request_user_agent,
)
from app.api.schemas import (
    Denied,
    LoginRequest,
    MfaRequired,
    MfaVerification,
    RefreshRequest,
    RegisterRequest,
    SessionIssued,
    SessionList,
    SessionSummary,
    UserProfile,
)
from app.core.tokens import TokenValidationError
from app.services.authentication import (
    AuthenticatedIdentity,
    AuthenticationRequiredError,
    AuthenticationService,
    DeniedResult,
    MfaRequiredResult,
    MfaVerificationError,
    RateLimitedError,
    RegistrationConflictError,
    SessionIssuedResult,
    SessionNotFoundError,
    SessionOwnershipError,
    UserProfileData,
)
from app.services.rate_limit import AuthenticationRateLimiter


router = APIRouter()
CorrelationId = Annotated[UUID, Header(alias="X-Correlation-ID")]


def problem_response(status: int, title: str, detail: str | None = None) -> JSONResponse:
    body = {"type": f"https://sentinel-auth.local/problems/{status}", "title": title, "status": status}
    if detail is not None:
        body["detail"] = detail
    return JSONResponse(status_code=status, content=body, media_type="application/problem+json")


def _profile(data: UserProfileData) -> UserProfile:
    return UserProfile(
        id=data.id,
        username=data.username,
        email=data.email,
        status=data.status,
        roles=data.roles,
        admin_mfa_required=data.admin_mfa_required,
    )


def _session_issued(data: SessionIssuedResult) -> SessionIssued:
    return SessionIssued(
        access_token=data.access_token,
        refresh_token=data.refresh_token,
        expires_in=data.expires_in,
    )


@router.post("/api/v1/auth/register", status_code=201, response_model=UserProfile)
def register(
    payload: RegisterRequest,
    correlation_id: CorrelationId,
    service: AuthenticationService = Depends(authentication_service),
) -> UserProfile | JSONResponse:
    try:
        return _profile(service.register(username=payload.username, email=payload.email, password=payload.password))
    except RegistrationConflictError:
        return problem_response(409, "Account conflict")


@router.post("/api/v1/auth/login", response_model=SessionIssued | MfaRequired | Denied)
def login(
    payload: LoginRequest,
    request: Request,
    correlation_id: CorrelationId,
    service: AuthenticationService = Depends(authentication_service),
    limiter: AuthenticationRateLimiter = Depends(app_rate_limiter),
) -> SessionIssued | MfaRequired | Denied | JSONResponse:
    source_ip = request_source_ip(request)
    identifier = payload.username if payload.username is not None else payload.email
    assert identifier is not None
    if not limiter.allow(scope="login", source_ip=source_ip, account_identifier=identifier):
        return problem_response(429, "Too many authentication requests")
    try:
        result = service.login(
            username=payload.username,
            email=payload.email,
            password=payload.password,
            source_ip=source_ip,
            user_agent=request_user_agent(request),
            device_fingerprint=payload.device_fingerprint,
            correlation_id=correlation_id,
        )
    except RateLimitedError:
        return problem_response(429, "Too many authentication requests")
    if isinstance(result, SessionIssuedResult):
        return _session_issued(result)
    if isinstance(result, MfaRequiredResult):
        return MfaRequired(
            pre_auth_token=result.pre_auth_token,
            expires_in=result.expires_in,
            otp_expires_in=result.otp_expires_in,
        )
    assert isinstance(result, DeniedResult)
    return Denied(message=result.message)


@router.post("/api/v1/auth/mfa/verify", response_model=SessionIssued)
def verify_mfa(
    payload: MfaVerification,
    request: Request,
    correlation_id: CorrelationId,
    service: AuthenticationService = Depends(authentication_service),
    limiter: AuthenticationRateLimiter = Depends(app_rate_limiter),
) -> SessionIssued | JSONResponse:
    source_ip = request_source_ip(request)
    account_identifier = service.mfa_rate_limit_account_identifier(pre_auth_token=payload.pre_auth_token)
    if not limiter.allow(scope="mfa", source_ip=source_ip, account_identifier=account_identifier):
        return problem_response(429, "Too many authentication requests")
    try:
        return _session_issued(
            service.verify_mfa(
                pre_auth_token=payload.pre_auth_token,
                challenge_response=payload.challenge_response,
                source_ip=source_ip,
                user_agent=request_user_agent(request),
            )
        )
    except MfaVerificationError:
        return problem_response(401, "MFA verification failed")


@router.post("/api/v1/auth/refresh", response_model=SessionIssued)
def refresh(
    payload: RefreshRequest,
    correlation_id: CorrelationId,
    service: AuthenticationService = Depends(authentication_service),
) -> SessionIssued | JSONResponse:
    try:
        return _session_issued(service.refresh(refresh_token=payload.refresh_token))
    except (AuthenticationRequiredError, TokenValidationError):
        return problem_response(401, "Authentication required")


@router.post("/api/v1/auth/logout", status_code=204, response_model=None)
def logout(
    correlation_id: CorrelationId,
    identity: AuthenticatedIdentity = Depends(current_identity),
    service: AuthenticationService = Depends(authentication_service),
) -> Response | JSONResponse:
    try:
        service.revoke_current_session(identity)
    except AuthenticationRequiredError:
        return problem_response(401, "Authentication required")
    return Response(status_code=204)


@router.get("/api/v1/users/me", response_model=UserProfile)
def me(
    identity: AuthenticatedIdentity = Depends(current_identity),
    service: AuthenticationService = Depends(authentication_service),
) -> UserProfile:
    return _profile(service.profile(identity))


@router.get("/api/v1/users/me/sessions", response_model=SessionList)
def my_sessions(
    identity: AuthenticatedIdentity = Depends(current_identity),
    service: AuthenticationService = Depends(authentication_service),
) -> SessionList:
    return SessionList(
        items=[
            SessionSummary(
                id=session.id,
                source_ip=session.source_ip,
                device_id=session.device_id,
                user_agent=session.user_agent,
                created_at=session.created_at,
                expires_at=session.expires_at,
                revoked_at=session.revoked_at,
            )
            for session in service.list_sessions(identity)
        ]
    )


@router.delete("/api/v1/sessions/{session_id}", status_code=204, response_model=None)
def revoke_session(
    session_id: UUID,
    correlation_id: CorrelationId,
    identity: AuthenticatedIdentity = Depends(current_identity),
    service: AuthenticationService = Depends(authentication_service),
) -> Response | JSONResponse:
    try:
        service.revoke_owned_session(identity, session_id)
    except SessionNotFoundError:
        return problem_response(404, "Session not found")
    except SessionOwnershipError:
        return problem_response(403, "Session is not owned by current user")
    return Response(status_code=204)

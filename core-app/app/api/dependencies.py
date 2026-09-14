"""FastAPI dependencies that assemble auth services without router business logic."""

from __future__ import annotations

import ipaddress
from collections.abc import Generator

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings, get_settings
from app.core.tokens import TokenValidationError
from app.database import create_session_factory
from app.services.authentication import AuthenticatedIdentity, AuthenticationService
from app.services.mailer import SmtpMfaMailer
from app.services.rate_limit import AuthenticationRateLimiter, RedisAuthenticationRateLimiter


bearer_scheme = HTTPBearer(auto_error=False)


def app_settings(request: Request) -> Settings:
    return request.app.state.settings or get_settings()


def app_session_factory(request: Request, settings: Settings = Depends(app_settings)) -> sessionmaker[Session]:
    factory = request.app.state.session_factory
    if factory is None:
        factory = create_session_factory(settings)
        request.app.state.session_factory = factory
    return factory


def db_session(factory: sessionmaker[Session] = Depends(app_session_factory)) -> Generator[Session, None, None]:
    session = factory()
    try:
        yield session
    finally:
        session.close()


def app_mailer(request: Request, settings: Settings = Depends(app_settings)) -> SmtpMfaMailer:
    mailer = request.app.state.mailer
    if mailer is None:
        mailer = SmtpMfaMailer(settings)
        request.app.state.mailer = mailer
    return mailer


def app_rate_limiter(
    request: Request,
    settings: Settings = Depends(app_settings),
) -> AuthenticationRateLimiter:
    limiter = request.app.state.rate_limiter
    if limiter is None:
        limiter = RedisAuthenticationRateLimiter(settings)
        request.app.state.rate_limiter = limiter
    return limiter


def authentication_service(
    session: Session = Depends(db_session),
    settings: Settings = Depends(app_settings),
    mailer: SmtpMfaMailer = Depends(app_mailer),
) -> AuthenticationService:
    return AuthenticationService(session=session, settings=settings, mailer=mailer)


def request_source_ip(request: Request) -> str:
    candidate = request.client.host if request.client is not None else "0.0.0.0"
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        # Test transports and untrusted reverse-proxy values are not accepted as
        # IP identity. Production proxy normalization is intentionally out of scope.
        return "0.0.0.0"


def request_user_agent(request: Request) -> str | None:
    value = request.headers.get("user-agent")
    return value[:1024] if value else None


def current_identity(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    service: AuthenticationService = Depends(authentication_service),
) -> AuthenticatedIdentity:
    if credentials is None or credentials.scheme.lower() != "bearer":
        from app.services.authentication import AuthenticationRequiredError

        raise AuthenticationRequiredError("Missing access token")
    try:
        return service.current_identity(access_token=credentials.credentials)
    except TokenValidationError as exc:
        from app.services.authentication import AuthenticationRequiredError

        raise AuthenticationRequiredError("Invalid access token") from exc

"""JWT and opaque-token primitives used by the authentication service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import hmac
import secrets
from typing import Any
from uuid import UUID, uuid4

import jwt
from jwt import InvalidTokenError

from app.core.settings import Settings


class TokenValidationError(ValueError):
    """A token is malformed, invalid, expired, or has an unexpected type."""


def generate_opaque_token() -> str:
    """Create a high-entropy token suitable for pre-auth continuation only."""

    return secrets.token_urlsafe(32)


def token_verifier(token: str) -> str:
    """Return a one-way verifier; raw bearer tokens are never persisted."""

    return sha256(token.encode("utf-8")).hexdigest()


def context_digest(value: str, settings: Settings) -> str:
    """HMAC contextual values such as source IP/device fingerprint before storage."""

    return hmac.new(settings.jwt_secret.encode("utf-8"), value.encode("utf-8"), sha256).hexdigest()


def issue_jwt(
    *,
    settings: Settings,
    subject: UUID,
    session_id: UUID,
    roles: list[str],
    token_type: str,
    expires_in: timedelta,
    token_version: int,
    token_id: UUID | None = None,
) -> tuple[str, UUID, datetime]:
    """Issue an authenticated JWT with the contract's identity/session claims."""

    now = datetime.now(UTC)
    jti = token_id or uuid4()
    expires_at = now + expires_in
    payload = {
        "sub": str(subject),
        "iat": now,
        "exp": expires_at,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "jti": str(jti),
        "sid": str(session_id),
        "roles": roles,
        "token_type": token_type,
        "token_version": token_version,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm), jti, expires_at


def decode_jwt(token: str, *, settings: Settings, expected_type: str) -> dict[str, Any]:
    """Verify JWT signature, issuer, audience, expiry and expected token type."""

    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "iat", "exp", "jti", "sid", "token_type", "token_version"]},
        )
    except InvalidTokenError as exc:
        raise TokenValidationError("Token validation failed") from exc

    if claims.get("token_type") != expected_type:
        raise TokenValidationError("Unexpected token type")
    if not isinstance(claims.get("roles"), list):
        raise TokenValidationError("JWT roles claim is invalid")
    return claims

"""Authorization dependency layer — bearer-token authentication + RBAC.

All human-facing routes use stateful opaque tokens backed by the sessions table.
Authentication validates the bearer token against PostgreSQL; authorization checks
roles against the DB in real-time so that role revocation takes effect immediately.

Service-to-service routes (``/api/v1/internal/*``) continue using X-Internal-Secret
(a separate trust boundary) and are NOT handled here.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from app.time_utils import utc_now
from typing import TYPE_CHECKING, FrozenSet, Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as OrmSession

from app.db import get_db

if TYPE_CHECKING:
    from app.models import Session as SessionModel, User as UserModel


# =============================================================================
# Canonical token utilities
# =============================================================================

def hash_token(token: str) -> str:
    """SHA256 hash of an opaque token — matches sessions.access_token_hash."""
    return hashlib.sha256(token.encode()).hexdigest()


def generate_opaque_token() -> str:
    """Generate a new random opaque token."""
    return secrets.token_urlsafe(32)


# =============================================================================
# Auth context
# =============================================================================

@dataclass
class AuthContext:
    """Authenticated caller identity, resolved from a bearer token."""
    request: Request
    session: "SessionModel"
    user: "UserModel"
    roles: FrozenSet[str] = field(default_factory=frozenset)


# =============================================================================
# Authentication dependency
# =============================================================================

async def get_current_auth_context(
    request: Request,
    db: OrmSession = Depends(get_db),
) -> AuthContext:
    """FastAPI dependency: authenticate a bearer token and return the caller's context.

    Raises HTTPException(401) if:
    - Authorization header is missing or malformed
    - Token hash has no matching Session
    - Session is revoked or expired
    - Associated User does not exist or is not active
    """
    # Import here to avoid circular import; models.py does not import authz.py
    from app.models import Role, Session as SessionModel, User as UserModel, UserRole

    auth_header = request.headers.get("Authorization", "")
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format",
        )

    token = parts[1]
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is empty",
        )

    token_hash = hash_token(token)

    session: Optional[SessionModel] = db.query(SessionModel).filter(
        SessionModel.access_token_hash == token_hash,
        SessionModel.revoked_at.is_(None),
        SessionModel.expires_at > utc_now(),
    ).first()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )

    user: Optional[UserModel] = db.query(UserModel).filter(
        UserModel.id == session.user_id,
    ).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is not active",
        )

    # Resolve roles from DB in real-time — not from the token.
    # Role.id stores the canonical role identifier (e.g. 'SOC_ANALYST').
    role_rows = (
        db.query(Role.id)
        .join(UserRole, UserRole.role_id == Role.id)
        .filter(UserRole.user_id == user.id)
        .all()
    )
    roles: FrozenSet[str] = frozenset(row[0] for row in role_rows)

    return AuthContext(request=request, session=session, user=user, roles=roles)


# =============================================================================
# Role guard factory
# =============================================================================

def require_roles(*allowed_roles: str):
    """FastAPI dependency factory: require at least one of the given roles.

    Usage::

        @router.get("/alerts")
        async def list_alerts(
            ctx: AuthContext = Depends(require_roles("SOC_ANALYST", "SECURITY_MANAGER")),
        ) -> AlertListResponse:
            ...

    Raises HTTPException(403) if the authenticated user has none of the allowed roles.
    """
    async def _guard(
        ctx: AuthContext = Depends(get_current_auth_context),
    ) -> AuthContext:
        if not ctx.roles & frozenset(allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return ctx

    return _guard


# =============================================================================
# Convenience helpers (imported by consumers)
# =============================================================================

def get_authenticated_user_id(ctx: AuthContext) -> str:
    """Return the authenticated user's ID string."""
    return ctx.user.id


def get_authenticated_roles(ctx: AuthContext) -> FrozenSet[str]:
    """Return the authenticated user's role set."""
    return ctx.roles

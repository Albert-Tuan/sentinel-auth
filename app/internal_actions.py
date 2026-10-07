"""
Core App internal endpoints consumed by the Detection Engine.

Implements the two `/api/v1/internal/*` routes that Detection Engine calls
back on Core App (DECISIONS-DETECTION-v3.3.md section 5.2):

* ``POST /api/v1/internal/actions``  - UC-DE-07 enforce a protective action
* ``GET  /api/v1/internal/users/{id}`` - WF-3 validate that a user may act as
  a SOC analyst (cross-database reference, enforced at application level)

Both routes are protected by the ``X-Internal-Secret`` shared secret; no JWT
is used because there is no human on the other side of the call.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as OrmSession

from app.db import get_db
from app.internal_auth import verify_internal_secret
from app.models import Role, Session, User, UserRole
from app.schemas import ActionRequest, ActionResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/internal", tags=["core-internal"])


# =============================================================================
# Helpers
# =============================================================================

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _user_roles(db: OrmSession, user_id: UUID) -> List[dict]:
    """Roles of a user, resolved through ``roles`` (role_id is a FK to roles.id).

    Returns both the stable identifier (``SOC_ANALYST``) and the display name
    so the caller can compare on the id without another lookup.
    """
    rows = (
        db.query(Role.id, Role.name, Role.name_vi)
        .join(UserRole, UserRole.role_id == Role.id)
        .filter(UserRole.user_id == user_id)
        .all()
    )
    return [{"id": r.id, "name": r.name, "name_vi": r.name_vi} for r in rows]


# =============================================================================
# Pydantic models local to this router
# =============================================================================

class InternalUserResponse(BaseModel):
    """Minimal user projection shared across databases."""

    user_id: UUID
    username: str
    status: str
    roles: List[dict] = Field(
        default_factory=list,
        description='Role objects: {"id": "SOC_ANALYST", "name": ..., "name_vi": ...}',
    )
    #: Convenience list of role identifiers, e.g. ["SOC_ANALYST", "USER"]
    role_ids: List[str] = Field(default_factory=list)


# =============================================================================
# POST /api/v1/internal/actions  (UC-DE-07)
# =============================================================================

@router.post("/actions", response_model=ActionResponse)
async def apply_action(
    payload: ActionRequest,
    x_internal_secret: Optional[str] = Header(None),
    db: OrmSession = Depends(get_db),
) -> ActionResponse:
    """Apply a protective action requested by the Detection Engine.

    The action is idempotent: re-delivering the same ``idempotency_key`` (or
    simply re-requesting an action already in effect) reports ``status =
    "already_applied"`` instead of failing.
    """
    verify_internal_secret(x_internal_secret)

    user = db.query(User).filter(User.id == payload.target_user_id).first()
    if user is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Target user not found",
        )

    details = {"reason": payload.reason}
    if payload.alert_id is not None:
        details["alert_id"] = str(payload.alert_id)
    if payload.severity is not None:
        details["severity"] = payload.severity.value

    action = payload.action.value
    already_applied = False

    def _revoke_active_sessions() -> int:
        """Revoke every live session of this user. Returns how many."""
        return int(
            db.query(Session)
            .filter(
                Session.user_id == user.id,
                Session.revoked_at.is_(None),
            )
            .update({Session.revoked_at: _now_utc()}, synchronize_session=False)
            or 0
        )

    if action == "REQUIRE_MFA":
        already_applied = bool(user.detection_mfa_once)
        user.detection_mfa_once = True
        # The one-time MFA flag only gates the *next* login. Without
        # revoking the live sessions, a token handed out before detection
        # ran would keep working until it expired, leaving the requirement
        # toothless.
        details["sessions_revoked"] = _revoke_active_sessions()

    elif action == "REVOKE_SESSIONS":
        details["sessions_revoked"] = _revoke_active_sessions()
        already_applied = details["sessions_revoked"] == 0

    elif action == "LOCK_USER":
        already_applied = user.status == "locked"
        if not already_applied:
            user.status = "locked"
            user.locked_at = _now_utc()
        details["sessions_revoked"] = _revoke_active_sessions()

    elif action == "FORCE_LOGOUT":
        # Same effect as REVOKE_SESSIONS; kept separate so the Detection
        # Engine can express intent without implying a lock.
        details["sessions_revoked"] = _revoke_active_sessions()
        already_applied = details["sessions_revoked"] == 0

    db.commit()

    return ActionResponse(
        status="already_applied" if already_applied else "applied",
        action=payload.action,
        target_user_id=user.id,
        details=details,
    )


# =============================================================================
# GET /api/v1/internal/users/{user_id}  (WF-3 cross-database reference)
# =============================================================================

@router.get("/users/{user_id}", response_model=InternalUserResponse)
async def get_internal_user(
    user_id: UUID,
    x_internal_secret: Optional[str] = Header(None),
    db: OrmSession = Depends(get_db),
) -> InternalUserResponse:
    """Resolve a core-db user for the Detection Engine / SOC workflow.

    ``soc_analysts.user_id`` and ``alert_timeline.actor_id`` live in
    detection-db but point at ``users.id`` in core-db, so the FK cannot be
    enforced by Postgres. This endpoint is the application-level substitute.
    """
    verify_internal_secret(x_internal_secret)

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="User not found")

    roles = _user_roles(db, user.id)
    return InternalUserResponse(
        user_id=user.id,
        username=user.username,
        status=user.status,
        roles=roles,
        role_ids=[r["id"] for r in roles],
    )

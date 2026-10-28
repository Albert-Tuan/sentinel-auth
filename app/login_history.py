"""Detection-owned read endpoint: login history for SOC investigation.

UC-DE-14 (``docs/05-dac-ta-use-case-detection-engine.md`` section 3.14)
requires a paginated search over ``login_attempts`` for the SOC Analyst.
The canonical endpoint is ``GET /api/v1/login-attempts``.

The table lives in ``sentinel_detection``; this handler reads it through the
Detection session only.  It never joins or reaches into the Core schema -
the subject is described by the Detection-owned
``username_attempted`` / ``user_id`` columns.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session as OrmSession

from app.authz import AuthContext, require_roles
from app.db import get_detection_db
from app.models import LoginAttempt

router = APIRouter(prefix="/api/v1", tags=["detection-investigation"])

#: Outcomes that the canonical search vocabulary calls "failed".  The stored
#: value is more granular than the search term, so both the plain failure and
#: the MFA-failure outcome are matched.
FAILED_OUTCOMES = ("failure", "mfa_failed")

#: Risk levels the search accepts.  Kept in sync with the CHECK constraint
#: on ``login_attempts.risk_level``.
RISK_LEVELS = ("low", "medium", "high", "critical")

#: Outcomes the search accepts.  Kept in sync with the CHECK constraint on
#: ``login_attempts.outcome``.
OUTCOMES = (
    "success",
    "failure",
    "mfa_required",
    "mfa_success",
    "mfa_failed",
    "blocked",
    "locked",
    "rate_limited",
)

#: The search vocabulary is narrower than the stored vocabulary: an analyst
#: asks for "success" or "failure", not for the seven granular outcomes.
SEARCH_OUTCOMES = ("success", "failure")


class LoginAttemptItem(BaseModel):
    """One row of the login history."""

    id: str
    event_id: str
    user_id: Optional[str] = None
    username_attempted: Optional[str] = None
    outcome: str
    mfa_used: bool = False
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    device_fingerprint: Optional[str] = None
    timestamp: datetime
    status: str
    risk_level: Optional[str] = None
    detection_decision: Optional[str] = None
    policy_id: Optional[str] = None
    primary_alert_id: Optional[str] = None
    request_id: Optional[str] = None


class LoginAttemptListResponse(BaseModel):
    """Paginated login-history result."""

    attempts: List[LoginAttemptItem]
    total: int
    page: int
    limit: int


def _attempt_to_dict(attempt: LoginAttempt) -> dict:
    """Convert a LoginAttempt ORM row to a JSON-safe dict.

    UUID and INET columns come back as native objects on PostgreSQL and as
    strings on SQLite, so every identifier is normalised to a string here.
    """
    return {
        "id": str(attempt.id),
        "event_id": str(attempt.event_id),
        "user_id": str(attempt.user_id) if attempt.user_id else None,
        "username_attempted": attempt.username_attempted,
        "outcome": attempt.outcome,
        "mfa_used": bool(attempt.mfa_used),
        "ip_address": str(attempt.ip_address) if attempt.ip_address else None,
        "user_agent": attempt.user_agent,
        "device_fingerprint": attempt.device_fingerprint,
        "timestamp": attempt.timestamp,
        "status": attempt.status,
        "risk_level": attempt.risk_level,
        "detection_decision": attempt.detection_decision,
        "policy_id": str(attempt.policy_id) if attempt.policy_id else None,
        "primary_alert_id": (
            str(attempt.primary_alert_id) if attempt.primary_alert_id else None
        ),
        "request_id": str(attempt.request_id) if attempt.request_id else None,
    }


@router.get("/login-attempts", response_model=LoginAttemptListResponse)
async def list_login_attempts(
    ctx: AuthContext = Depends(require_roles("SOC_ANALYST", "SECURITY_MANAGER")),
    user_id: Optional[UUID] = Query(None, description="Filter by subject user"),
    username: Optional[str] = Query(None, min_length=1, max_length=50),
    from_date: Optional[datetime] = Query(None, description="Inclusive start"),
    to_date: Optional[datetime] = Query(None, description="Exclusive end"),
    ip_address: Optional[str] = Query(None, max_length=45),
    outcome: Optional[str] = Query(None, description="success|failure"),
    risk_level: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: OrmSession = Depends(get_detection_db),
) -> LoginAttemptListResponse:
    """Search the login history (UC-DE-14).

    The filters are exactly the canonical search criteria; nothing is
    invented beyond them.  Results are ordered newest first so an analyst
    always sees the most recent activity at the top of a page.
    """
    if outcome is not None and outcome not in SEARCH_OUTCOMES:
        raise HTTPException(
            status_code=400,
            detail=f"outcome must be one of {list(SEARCH_OUTCOMES)}",
        )
    if risk_level is not None and risk_level not in RISK_LEVELS:
        raise HTTPException(
            status_code=400,
            detail=f"risk_level must be one of {list(RISK_LEVELS)}",
        )
    if from_date is not None and to_date is not None and from_date >= to_date:
        raise HTTPException(
            status_code=400,
            detail="from_date must be earlier than to_date",
        )

    query = db.query(LoginAttempt)

    if user_id is not None:
        query = query.filter(LoginAttempt.user_id == user_id)
    if username:
        query = query.filter(LoginAttempt.username_attempted == username)
    if from_date is not None:
        query = query.filter(LoginAttempt.timestamp >= from_date)
    if to_date is not None:
        query = query.filter(LoginAttempt.timestamp < to_date)
    if ip_address:
        query = query.filter(LoginAttempt.ip_address == ip_address)
    if outcome == "failure":
        query = query.filter(LoginAttempt.outcome.in_(FAILED_OUTCOMES))
    elif outcome == "success":
        query = query.filter(LoginAttempt.outcome == "success")
    if risk_level:
        query = query.filter(LoginAttempt.risk_level == risk_level)

    query = query.order_by(LoginAttempt.timestamp.desc(), LoginAttempt.id.desc())
    total = query.count()
    attempts = query.offset((page - 1) * limit).limit(limit).all()

    return LoginAttemptListResponse(
        attempts=[
            LoginAttemptItem.model_validate(_attempt_to_dict(a)) for a in attempts
        ],
        total=total,
        page=page,
        limit=limit,
    )

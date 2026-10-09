"""
SOC Alert Management - Alert CRUD, evidence and timeline.

Schema v3.3. Canonical decisions: docs/DECISIONS-DETECTION-v3.3.md

All endpoints are protected by bearer-token authentication + RBAC.

Authorization matrix:
  - READ  (list, get, evidence, timeline): SOC_ANALYST or SECURITY_MANAGER
  - WRITE (acknowledge, resolve, assign, actions, add-timeline): SOC_ANALYST or SECURITY_MANAGER
  - USER role gets 403 on all alert endpoints.
"""
from datetime import datetime

from app.time_utils import utc_now
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session as OrmSession

from app.db import get_db
from app.models import (
    Alert, AlertTimeline, LoginAttempt, RiskAssessment,
    User, Session, DetectionLog, SocAnalyst,
)
from app.schemas import SecurityAction
from app.authz import (
    AuthContext,
    get_current_auth_context,
    require_roles,
    get_authenticated_user_id,
)

router = APIRouter(prefix="/api/v1", tags=["soc"])


# =============================================================================
# Enums
# =============================================================================

class AlertStatusEnum(str):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    FALSE_POSITIVE = "false_positive"


class TimelineEventType(str):
    CREATED = "created"
    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"
    ACKNOWLEDGED = "acknowledged"
    ESCALATED = "escalated"
    NOTE_ADDED = "note_added"
    STATUS_CHANGED = "status_changed"
    RESOLVED = "resolved"
    FALSE_POSITIVE = "false_positive"


# =============================================================================
# Request/Response Schemas
# =============================================================================

class LoginAttemptSummary(BaseModel):
    id: str
    event_id: str
    timestamp: datetime
    outcome: str
    username_attempted: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    user_id: Optional[str] = None
    mfa_used: bool = False
    risk_level: Optional[str] = None
    detection_decision: Optional[str] = None

    class Config:
        from_attributes = True


class RiskAssessmentSummary(BaseModel):
    rule_score: Optional[float] = None
    ml_score: Optional[float] = None
    combined_score: Optional[float] = None
    ml_status: Optional[str] = None
    ml_model_version: Optional[str] = None
    ml_reason_codes: Optional[list] = None
    ml_features_used: Optional[dict] = None
    rule_hits: Optional[list] = None
    risk_level: Optional[str] = None
    decision: Optional[str] = None

    class Config:
        from_attributes = True


class DetectionLogSummary(BaseModel):
    id: str
    stage: str
    stage_detail: Optional[str] = None
    rule_name: Optional[str] = None
    triggered: Optional[bool] = None
    score_contribution: Optional[float] = None
    decision: Optional[str] = None
    reason: Optional[str] = None
    details: Optional[dict] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AlertEvidence(BaseModel):
    alert: "AlertItem"
    login_attempt: Optional[LoginAttemptSummary] = None
    risk_assessment: Optional[RiskAssessmentSummary] = None
    detection_logs: List[DetectionLogSummary] = []
    timeline: List["TimelineEvent"] = []


class AlertItem(BaseModel):
    id: str
    login_attempt_id: str
    policy_id: Optional[str] = None
    status: str
    risk_level: Optional[str] = None
    detection_reason: Optional[str] = None
    detection_scores: Optional[dict] = None
    assigned_to_id: Optional[str] = None
    resolved_by_id: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolution: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AlertListResponse(BaseModel):
    alerts: List[AlertItem]
    total: int
    page: int
    limit: int


class TimelineEvent(BaseModel):
    id: str
    alert_id: str
    event_type: str
    actor_id: Optional[str] = None
    actor_type: str = "user"
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    comment: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TimelineEventCreate(BaseModel):
    event_type: str
    comment: Optional[str] = None


class AlertAcknowledgeRequest(BaseModel):
    notes: Optional[str] = None


class AlertResolveRequest(BaseModel):
    resolution: str = Field(
        ...,
        description=(
            "Investigation outcome: true_attack | false_positive | "
            "benign_true_positive | insufficient_evidence"
        ),
    )
    notes: Optional[str] = None


class AlertAssignRequest(BaseModel):
    assigned_to_id: str
    notes: Optional[str] = None


class AlertActionRequest(BaseModel):
    """Request a protective action from SOC (UC-DE-12)."""
    action: SecurityAction
    reason: str = Field(..., min_length=1)


class AlertActionResponse(BaseModel):
    status: str
    action: str
    details: dict


# =============================================================================
# Helpers
# =============================================================================

def _uuid_to_str(value) -> Optional[str]:
    """Normalise a UUID to a string for SQLite/PostgreSQL compatibility."""
    if value is None:
        return None
    if hasattr(value, "hex"):
        return str(value)
    return str(value)


def _get_client_ip_from_request(request) -> Optional[str]:
    """Extract client IP from the request for the audit trail."""
    forwarded = request.headers.get("x-forwarded-for") if hasattr(request, "headers") else None
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = getattr(request, "client", None)
    return getattr(client, "host", None)


def _alert_to_dict(alert) -> dict:
    """Convert an Alert ORM object to a dict with string UUIDs.

    Needed because SQLite UUID columns return Python UUID objects while PostgreSQL
    UUID columns return UUID objects too. The Pydantic schema expects str fields.
    Using model_validate() is cleaner but validator inheritance makes it complex;
    this approach is explicit and works across both DB backends.
    """
    return {
        "id": str(alert.id),
        "login_attempt_id": str(alert.login_attempt_id),
        "policy_id": str(alert.policy_id) if alert.policy_id else None,
        "status": alert.status,
        "risk_level": alert.risk_level,
        "detection_reason": alert.detection_reason,
        "detection_scores": alert.detection_scores,
        "assigned_to_id": str(alert.assigned_to_id) if alert.assigned_to_id else None,
        "resolved_by_id": str(alert.resolved_by_id) if alert.resolved_by_id else None,
        "resolved_at": alert.resolved_at,
        "resolution": alert.resolution,
        "notes": alert.notes,
        "created_at": alert.created_at,
        "updated_at": alert.updated_at,
    }


def _timeline_to_dict(event) -> dict:
    """Convert an AlertTimeline ORM object to a dict with string UUIDs."""
    return {
        "id": str(event.id),
        "alert_id": str(event.alert_id),
        "event_type": event.event_type,
        "actor_id": str(event.actor_id) if event.actor_id else None,
        "actor_type": event.actor_type,
        "old_value": event.old_value,
        "new_value": event.new_value,
        "comment": event.comment,
        "ip_address": str(event.ip_address) if event.ip_address else None,
        "created_at": event.created_at,
    }


def _detection_log_to_dict(log) -> dict:
    """Convert a DetectionLog ORM object to a dict with string UUIDs."""
    return {
        "id": str(log.id),
        "stage": log.stage,
        "stage_detail": log.stage_detail,
        "rule_name": log.rule_name,
        "triggered": log.triggered,
        "score_contribution": log.score_contribution,
        "decision": log.decision,
        "reason": log.reason,
        "details": log.details,
        "created_at": log.created_at,
    }


def _create_timeline_event(
    db: OrmSession,
    alert_id: UUID,
    event_type: str,
    actor_id: Optional[str] = None,
    actor_type: str = "user",
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    comment: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> AlertTimeline:
    """Append an immutable entry to the alert timeline."""
    event = AlertTimeline(
        alert_id=alert_id,
        event_type=event_type,
        actor_id=actor_id,
        actor_type=actor_type,
        old_value=old_value,
        new_value=new_value,
        comment=comment,
        ip_address=ip_address,
    )
    db.add(event)
    return event


# =============================================================================
# Alert READ endpoints — SOC_ANALYST or SECURITY_MANAGER
# =============================================================================

@router.get("/alerts", response_model=AlertListResponse)
async def list_alerts(
    ctx: AuthContext = Depends(require_roles("SOC_ANALYST", "SECURITY_MANAGER")),
    status: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    assigned_to_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: OrmSession = Depends(get_db),
) -> AlertListResponse:
    """List alerts with filtering.

    Allowed roles: SOC_ANALYST or SECURITY_MANAGER only.
    SECURITY_ADMIN is NOT a SOC role and gets 403.
    """
    """List alerts with filtering."""
    query = db.query(Alert)

    if status:
        query = query.filter(Alert.status == status)
    if risk_level:
        query = query.filter(Alert.risk_level == risk_level)
    if assigned_to_id:
        query = query.filter(Alert.assigned_to_id == assigned_to_id)

    query = query.order_by(Alert.created_at.desc())
    total = query.count()
    offset = (page - 1) * limit
    alerts = query.offset(offset).limit(limit).all()

    return AlertListResponse(
        alerts=[AlertItem.model_validate(_alert_to_dict(a)) for a in alerts],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/alerts/{alert_id}", response_model=AlertItem)
async def get_alert(
    alert_id: UUID,
    ctx: AuthContext = Depends(require_roles("SOC_ANALYST", "SECURITY_MANAGER")),
    db: OrmSession = Depends(get_db),
) -> AlertItem:
    """Get single alert by ID."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return AlertItem.model_validate(_alert_to_dict(alert))


@router.get("/alerts/{alert_id}/evidence", response_model=AlertEvidence)
async def get_alert_evidence(
    alert_id: UUID,
    ctx: AuthContext = Depends(require_roles("SOC_ANALYST", "SECURITY_MANAGER")),
    db: OrmSession = Depends(get_db),
) -> AlertEvidence:
    """Get full evidence for alert investigation."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    login_attempt = (
        db.query(LoginAttempt)
        .filter(LoginAttempt.id == alert.login_attempt_id)
        .first()
    )

    risk_assessment = None
    if login_attempt:
        risk_assessment = (
            db.query(RiskAssessment)
            .filter(RiskAssessment.login_attempt_id == login_attempt.id)
            .first()
        )

    detection_logs = []
    if login_attempt:
        logs = (
            db.query(DetectionLog)
            .filter(DetectionLog.login_attempt_id == login_attempt.id)
            .order_by(DetectionLog.created_at)
            .all()
        )
        detection_logs = [DetectionLogSummary.model_validate(_detection_log_to_dict(l)) for l in logs]

    timeline_events = (
        db.query(AlertTimeline)
        .filter(AlertTimeline.alert_id == alert_id)
        .order_by(AlertTimeline.created_at)
        .all()
    )

    login_summary = None
    if login_attempt:
        user = (
            db.query(User)
            .filter(User.id == login_attempt.user_id)
            .first()
            if login_attempt.user_id else None
        )
        login_summary = LoginAttemptSummary(
            id=str(login_attempt.id),
            event_id=str(login_attempt.event_id),
            timestamp=login_attempt.timestamp,
            outcome=login_attempt.outcome,
            username_attempted=(
                login_attempt.username_attempted or (user.username if user else None)
            ),
            ip_address=str(login_attempt.ip_address) if login_attempt.ip_address else None,
            user_agent=login_attempt.user_agent,
            user_id=str(login_attempt.user_id) if login_attempt.user_id else None,
            mfa_used=login_attempt.mfa_used,
            risk_level=login_attempt.risk_level,
            detection_decision=login_attempt.detection_decision,
        )

    risk_summary = None
    if risk_assessment:
        risk_summary = RiskAssessmentSummary(
            rule_score=float(risk_assessment.rule_score) if risk_assessment.rule_score is not None else None,
            ml_score=float(risk_assessment.ml_score) if risk_assessment.ml_score is not None else None,
            combined_score=float(risk_assessment.combined_score) if risk_assessment.combined_score is not None else None,
            ml_status=risk_assessment.ml_status,
            ml_model_version=risk_assessment.ml_model_version,
            ml_reason_codes=risk_assessment.ml_reason_codes,
            ml_features_used=risk_assessment.ml_features_used,
            rule_hits=risk_assessment.rule_hits,
            risk_level=risk_assessment.risk_level,
            decision=risk_assessment.decision,
        )

    return AlertEvidence(
        alert=AlertItem.model_validate(_alert_to_dict(alert)),
        login_attempt=login_summary,
        risk_assessment=risk_summary,
        detection_logs=detection_logs,
        timeline=[TimelineEvent.model_validate(_timeline_to_dict(e)) for e in timeline_events],
    )


# =============================================================================
# Alert WRITE endpoints — SOC_ANALYST or SECURITY_MANAGER
# =============================================================================

@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: UUID,
    request: AlertAcknowledgeRequest,
    ctx: AuthContext = Depends(require_roles("SOC_ANALYST", "SECURITY_MANAGER")),
    db: OrmSession = Depends(get_db),
) -> AlertItem:
    """Acknowledge an open alert."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    if alert.status != AlertStatusEnum.OPEN:
        raise HTTPException(
            status_code=400,
            detail=f"Alert is {alert.status}, only open alerts can be acknowledged",
        )

    old_status = alert.status
    alert.status = AlertStatusEnum.ACKNOWLEDGED

    if request.notes:
        if alert.notes:
            alert.notes += f"\n---\n{request.notes}"
        else:
            alert.notes = request.notes

    actor_id = get_authenticated_user_id(ctx)
    client_ip = _get_client_ip_from_request(ctx.request) if ctx.request else None

    _create_timeline_event(
        db=db,
        alert_id=alert_id,
        event_type=TimelineEventType.ACKNOWLEDGED,
        actor_id=actor_id,
        actor_type="user",
        old_value=old_status,
        new_value=AlertStatusEnum.ACKNOWLEDGED,
        comment=request.notes,
        ip_address=client_ip,
    )

    db.commit()
    db.refresh(alert)
    return AlertItem.model_validate(_alert_to_dict(alert))


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: UUID,
    request: AlertResolveRequest,
    ctx: AuthContext = Depends(require_roles("SOC_ANALYST", "SECURITY_MANAGER")),
    db: OrmSession = Depends(get_db),
) -> AlertItem:
    """Resolve or mark an alert as false positive."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    if request.resolution == "false_positive":
        new_status = AlertStatusEnum.FALSE_POSITIVE
    else:
        new_status = AlertStatusEnum.RESOLVED

    valid_from = [AlertStatusEnum.OPEN, AlertStatusEnum.ACKNOWLEDGED]
    if alert.status not in valid_from:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot resolve alert from status: {alert.status}",
        )

    old_status = alert.status
    alert.status = new_status
    alert.resolution = request.resolution

    # resolved_by_id references soc_analysts.id — only fill if the user is a SocAnalyst
    analyst = db.query(SocAnalyst).filter(
        SocAnalyst.user_id == get_authenticated_user_id(ctx)
    ).first()
    if analyst:
        alert.resolved_by_id = analyst.id

    alert.resolved_at = utc_now()

    if request.notes:
        if alert.notes:
            alert.notes += f"\n---\nResolution: {request.notes}"
        else:
            alert.notes = f"Resolution: {request.notes}"

    actor_id = get_authenticated_user_id(ctx)
    client_ip = _get_client_ip_from_request(ctx.request) if ctx.request else None

    _create_timeline_event(
        db=db,
        alert_id=alert_id,
        event_type=TimelineEventType.STATUS_CHANGED,
        actor_id=actor_id,
        actor_type="user",
        old_value=old_status,
        new_value=new_status,
        comment=request.notes,
        ip_address=client_ip,
    )

    _create_timeline_event(
        db=db,
        alert_id=alert_id,
        event_type=(
            TimelineEventType.FALSE_POSITIVE
            if new_status == AlertStatusEnum.FALSE_POSITIVE
            else TimelineEventType.RESOLVED
        ),
        actor_id=actor_id,
        actor_type="user",
        old_value=None,
        new_value=request.resolution,
        comment=request.notes,
        ip_address=client_ip,
    )

    db.commit()
    db.refresh(alert)
    return AlertItem.model_validate(_alert_to_dict(alert))


@router.post("/alerts/{alert_id}/assign")
async def assign_alert(
    alert_id: UUID,
    request: AlertAssignRequest,
    ctx: AuthContext = Depends(require_roles("SOC_ANALYST", "SECURITY_MANAGER")),
    db: OrmSession = Depends(get_db),
) -> AlertItem:
    """Assign an alert to a SOC analyst."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    # Validate assigned_to_id references an existing active SocAnalyst
    try:
        assigned_uuid = UUID(request.assigned_to_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="assigned_to_id must be a valid UUID",
        )

    analyst = db.query(SocAnalyst).filter(
        SocAnalyst.id == assigned_uuid,
        SocAnalyst.is_active == True,  # noqa: E712
    ).first()
    if not analyst:
        raise HTTPException(
            status_code=400,
            detail="assigned_to_id must reference an existing active SOC analyst",
        )

    old_assignee = alert.assigned_to_id
    # Store as string UUID to match SQLite UUID column (TEXT mode)
    alert.assigned_to_id = assigned_uuid

    event_type = (
        TimelineEventType.ASSIGNED if old_assignee is None
        else TimelineEventType.STATUS_CHANGED
    )
    actor_id = get_authenticated_user_id(ctx)
    client_ip = _get_client_ip_from_request(ctx.request) if ctx.request else None

    _create_timeline_event(
        db=db,
        alert_id=alert_id,
        event_type=event_type,
        actor_id=actor_id,
        actor_type="user",
        old_value=old_assignee,
        new_value=request.assigned_to_id,
        comment=request.notes,
        ip_address=client_ip,
    )

    db.commit()
    db.refresh(alert)
    return AlertItem.model_validate(_alert_to_dict(alert))


@router.post("/alerts/{alert_id}/actions")
async def request_security_action(
    alert_id: UUID,
    request: AlertActionRequest,
    ctx: AuthContext = Depends(require_roles("SOC_ANALYST", "SECURITY_MANAGER")),
    db: OrmSession = Depends(get_db),
) -> AlertActionResponse:
    """Apply a protective action (UC-DE-13 / UC-DE-11).

    NOTE: The documentation describes this as a SOC analyst "requesting"
    a protective action. The current implementation directly applies it.
    This semantic gap (request vs. apply) is a documented design question
    not resolved in P0-04.
    """
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    login_attempt = (
        db.query(LoginAttempt)
        .filter(LoginAttempt.id == alert.login_attempt_id)
        .first()
    )

    if not login_attempt or not login_attempt.user_id:
        raise HTTPException(
            status_code=400,
            detail="No user associated with this alert",
        )

    user = db.query(User).filter(User.id == login_attempt.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    action = request.action
    details = {}

    def _revoke_user_sessions() -> int:
        """Revoke every active session of THIS user only."""
        revoked = (
            db.query(Session)
            .filter(
                Session.user_id == user.id,
                Session.revoked_at.is_(None),
            )
            .all()
        )
        for session in revoked:
            session.revoked_at = utc_now()
        return len(revoked)

    if action == SecurityAction.REQUIRE_MFA:
        already_applied = bool(user.detection_mfa_once)
        user.detection_mfa_once = True
        details = {
            "mfa_enabled": True,
            "one_time": True,
            "already_applied": already_applied,
            "sessions_revoked": _revoke_user_sessions(),
            "reason": request.reason,
        }

    elif action == SecurityAction.REVOKE_SESSIONS:
        details = {
            "revoked_count": _revoke_user_sessions(),
            "reason": request.reason,
        }

    elif action == SecurityAction.LOCK_USER:
        user.status = "locked"
        user.locked_at = utc_now()
        details = {
            "status": "locked",
            "sessions_revoked": _revoke_user_sessions(),
            "reason": request.reason,
        }

    elif action == SecurityAction.FORCE_LOGOUT:
        details = {
            "revoked_count": _revoke_user_sessions(),
            "reason": request.reason,
        }

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported action: {action.value}",
        )

    actor_id = get_authenticated_user_id(ctx)
    client_ip = _get_client_ip_from_request(ctx.request) if ctx.request else None

    _create_timeline_event(
        db=db,
        alert_id=alert_id,
        event_type=TimelineEventType.NOTE_ADDED,
        actor_id=actor_id,
        actor_type="user",
        new_value=action.value,
        comment=f"Security action applied: {action.value}. Reason: {request.reason}",
        ip_address=client_ip,
    )

    db.commit()

    return AlertActionResponse(
        status="applied",
        action=action.value,
        details=details,
    )


# =============================================================================
# Alert Timeline READ endpoint — SOC_ANALYST or SECURITY_MANAGER
# =============================================================================

@router.get("/alerts/{alert_id}/timeline", response_model=List[TimelineEvent])
async def get_alert_timeline(
    alert_id: UUID,
    ctx: AuthContext = Depends(require_roles("SOC_ANALYST", "SECURITY_MANAGER")),
    db: OrmSession = Depends(get_db),
) -> List[TimelineEvent]:
    """Get timeline events for an alert."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    events = (
        db.query(AlertTimeline)
        .filter(AlertTimeline.alert_id == alert_id)
        .order_by(AlertTimeline.created_at.asc())
        .all()
    )
    return [TimelineEvent.model_validate(_timeline_to_dict(e)) for e in events]


@router.post("/alerts/{alert_id}/timeline")
async def add_timeline_event(
    alert_id: UUID,
    request: TimelineEventCreate,
    ctx: AuthContext = Depends(require_roles("SOC_ANALYST", "SECURITY_MANAGER")),
    db: OrmSession = Depends(get_db),
) -> TimelineEvent:
    """Add a timeline event to an alert."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    actor_id = get_authenticated_user_id(ctx)
    client_ip = _get_client_ip_from_request(ctx.request) if ctx.request else None

    event = _create_timeline_event(
        db=db,
        alert_id=alert_id,
        event_type=request.event_type,
        actor_id=actor_id,
        actor_type="user",
        comment=request.comment,
        ip_address=client_ip,
    )

    db.commit()
    db.refresh(event)
    return TimelineEvent.model_validate(_timeline_to_dict(event))


AlertEvidence.model_rebuild()

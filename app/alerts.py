"""
SOC Alert Management - Alert CRUD & Timeline.
Implements:
- Alert CRUD operations
- Alert Timeline (audit trail)
- SOC investigation workflow

Per Bảng Yêu Cầu Chức Năng Nghiệp Vụ v2:
- UC-08: Xem bằng chứng Rule/ML/Risk
- UC-09: Tiếp nhận và điều tra Alert
- UC-10: Phân loại kết quả điều tra
- UC-11: Yêu cầu hành động bảo vệ
- UC-12: Đóng hồ sơ Incident
"""
from datetime import datetime
from typing import Optional, List
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Header, Depends, Query
from pydantic import BaseModel, Field
from enum import Enum

from app.db import get_db
from app.models import (
    Alert, AlertTimeline, LoginAttempt, RiskAssessment,
    User, Session, DetectionLog
)

router = APIRouter(prefix="/api/v1", tags=["soc"])


# =============================================================================
# Enums
# =============================================================================

class AlertStatusEnum(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    FALSE_POSITIVE = "false_positive"


class RiskLevelEnum(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TimelineEventType(str, Enum):
    CREATED = "created"
    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"
    ACKNOWLEDGED = "acknowledged"
    ESCALATED = "escalated"
    NOTE_ADDED = "note_added"
    STATUS_CHANGED = "status_changed"
    RESOLVED = "resolved"


# =============================================================================
# Request/Response Schemas
# =============================================================================

class LoginAttemptSummary(BaseModel):
    id: str
    occurred_at: datetime
    outcome: str
    source_ip: Optional[str] = None
    user_agent: Optional[str] = None
    user_id: Optional[str] = None
    username: Optional[str] = None

    class Config:
        from_attributes = True


class RiskAssessmentSummary(BaseModel):
    rule_score: Optional[float] = None
    anomaly_score: Optional[float] = None
    ml_score: Optional[float] = None
    ml_status: Optional[str] = None
    ml_model_version: Optional[str] = None
    ml_features_used: Optional[dict] = None
    rule_hits: Optional[dict] = None
    combined_score: Optional[float] = None
    risk_level: Optional[str] = None
    decision: Optional[str] = None

    class Config:
        from_attributes = True


class DetectionLogSummary(BaseModel):
    id: str
    stage: str
    stage_detail: Optional[str] = None
    score: Optional[float] = None
    decision: Optional[str] = None
    reason: Optional[str] = None
    details: Optional[dict] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AlertEvidence(BaseModel):
    """Full evidence for SOC investigation (UC-08)."""
    alert: "AlertItem"
    login_attempt: Optional[LoginAttemptSummary] = None
    risk_assessment: Optional[RiskAssessmentSummary] = None
    detection_logs: List[DetectionLogSummary] = []
    timeline: List["TimelineEvent"] = []


class AlertItem(BaseModel):
    id: str
    login_attempt_id: str
    status: AlertStatusEnum
    risk_level: Optional[RiskLevelEnum] = None
    detection_reason: Optional[str] = None
    detection_scores: Optional[dict] = None
    assigned_to: Optional[str] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
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


class AlertFilter(BaseModel):
    status: Optional[AlertStatusEnum] = None
    risk_level: Optional[RiskLevelEnum] = None
    assigned_to: Optional[str] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None


class TimelineEvent(BaseModel):
    id: str
    alert_id: str
    event_type: TimelineEventType
    actor: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    comment: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TimelineEventCreate(BaseModel):
    event_type: TimelineEventType
    comment: Optional[str] = None


class AlertAcknowledgeRequest(BaseModel):
    notes: Optional[str] = None


class AlertResolveRequest(BaseModel):
    status: AlertStatusEnum = Field(
        ...,
        description="Must be 'resolved' or 'false_positive'"
    )
    notes: Optional[str] = None
    resolution_notes: Optional[str] = None


class AlertAssignRequest(BaseModel):
    assigned_to: str
    notes: Optional[str] = None


class AlertActionRequest(BaseModel):
    """Request security action from SOC (UC-11)."""
    action: str = Field(
        ...,
        description="REQUIRE_MFA | REVOKE_SESSIONS | LOCK_USER"
    )
    reason: str


class AlertActionResponse(BaseModel):
    status: str
    action: str
    details: dict


# =============================================================================
# Helper Functions
# =============================================================================

def verify_internal_token(x_internal_token: Optional[str]) -> bool:
    """Verify internal API token."""
    if not x_internal_token:
        return False
    return x_internal_token == "changeme-in-production"


def get_client_ip(actor: str, request=None) -> Optional[str]:
    """Get client IP for audit."""
    # In real implementation, extract from request
    return None


def create_timeline_event(
    db,
    alert_id: str,
    event_type: TimelineEventType,
    actor: str,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    comment: Optional[str] = None,
    ip_address: Optional[str] = None
) -> AlertTimeline:
    """Create a timeline event for alert."""
    event = AlertTimeline(
        alert_id=alert_id,
        event_type=event_type.value,
        actor=actor,
        old_value=old_value,
        new_value=new_value,
        comment=comment,
        ip_address=ip_address,
    )
    db.add(event)
    return event


# =============================================================================
# Alert CRUD Endpoints
# =============================================================================

@router.get("/alerts", response_model=AlertListResponse)
async def list_alerts(
    status: Optional[AlertStatusEnum] = Query(None),
    risk_level: Optional[RiskLevelEnum] = Query(None),
    assigned_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    x_internal_token: Optional[str] = Header(None),
    db=Depends(get_db),
) -> AlertListResponse:
    """
    List alerts with filtering (UC-06: SOC Dashboard data source).

    Per S-QĐ-01: Dashboard chỉ hiển thị dữ liệu mà actor có quyền xem.
    """
    query = db.query(Alert)

    # Apply filters
    if status:
        query = query.filter(Alert.status == status.value)
    if risk_level:
        query = query.filter(Alert.risk_level == risk_level.value)
    if assigned_to:
        query = query.filter(Alert.assigned_to == assigned_to)

    # Order by created_at desc
    query = query.order_by(Alert.created_at.desc())

    # Count total
    total = query.count()

    # Paginate
    offset = (page - 1) * limit
    alerts = query.offset(offset).limit(limit).all()

    return AlertListResponse(
        alerts=[AlertItem.model_validate(a) for a in alerts],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/alerts/{alert_id}", response_model=AlertItem)
async def get_alert(
    alert_id: str,
    x_internal_token: Optional[str] = Header(None),
    db=Depends(get_db),
) -> AlertItem:
    """Get single alert by ID."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return AlertItem.model_validate(alert)


@router.get("/alerts/{alert_id}/evidence", response_model=AlertEvidence)
async def get_alert_evidence(
    alert_id: str,
    x_internal_token: Optional[str] = Header(None),
    db=Depends(get_db),
) -> AlertEvidence:
    """
    Get full evidence for alert investigation (UC-08).

    Returns:
    - Alert details
    - Login attempt info
    - Risk assessment scores (rule, ML, combined)
    - Detection logs (rule hits, ML evaluation)
    - Timeline events

    Per S-QĐ-03: Hiển thị Rule Score, Anomaly Score và Total Risk Score riêng biệt.
    """
    # Get alert
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    # Get login attempt
    login_attempt = db.query(LoginAttempt).filter(
        LoginAttempt.id == alert.login_attempt_id
    ).first()

    # Get risk assessment (1:1 with login attempt)
    risk_assessment = None
    if login_attempt:
        risk_assessment = db.query(RiskAssessment).filter(
            RiskAssessment.login_attempt_id == login_attempt.id
        ).first()

    # Get detection logs
    detection_logs = []
    if login_attempt:
        logs = db.query(DetectionLog).filter(
            DetectionLog.login_attempt_id == login_attempt.id
        ).order_by(DetectionLog.created_at).all()
        detection_logs = [DetectionLogSummary.model_validate(l) for l in logs]

    # Get timeline
    timeline_events = db.query(AlertTimeline).filter(
        AlertTimeline.alert_id == alert_id
    ).order_by(AlertTimeline.created_at).all()

    # Build login attempt summary
    login_summary = None
    if login_attempt:
        user = db.query(User).filter(User.id == login_attempt.user_id).first() if login_attempt.user_id else None
        login_summary = LoginAttemptSummary(
            id=str(login_attempt.id),
            occurred_at=login_attempt.occurred_at,
            outcome=login_attempt.outcome,
            source_ip=str(login_attempt.source_ip) if login_attempt.source_ip else None,
            user_agent=login_attempt.user_agent,
            user_id=str(login_attempt.user_id) if login_attempt.user_id else None,
            username=user.username if user else None,
        )

    # Build risk assessment summary
    risk_summary = None
    if risk_assessment:
        risk_summary = RiskAssessmentSummary(
            rule_score=float(risk_assessment.rule_score) if risk_assessment.rule_score else None,
            anomaly_score=float(risk_assessment.anomaly_score) if risk_assessment.anomaly_score else None,
            ml_score=float(risk_assessment.ml_score) if risk_assessment.ml_score else None,
            ml_status=risk_assessment.ml_status,
            ml_model_version=risk_assessment.ml_model_version,
            ml_features_used=risk_assessment.ml_features_used,
            rule_hits=risk_assessment.rule_hits,
            combined_score=float(risk_assessment.combined_score) if risk_assessment.combined_score else None,
            risk_level=risk_assessment.risk_level,
            decision=risk_assessment.decision,
        )

    return AlertEvidence(
        alert=AlertItem.model_validate(alert),
        login_attempt=login_summary,
        risk_assessment=risk_summary,
        detection_logs=detection_logs,
        timeline=[TimelineEvent.model_validate(e) for e in timeline_events],
    )


# =============================================================================
# Alert Actions
# =============================================================================

@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    request: AlertAcknowledgeRequest,
    x_internal_token: Optional[str] = Header(None),
    db=Depends(get_db),
) -> AlertItem:
    """
    Acknowledge an alert (UC-09).

    Per S-QĐ-04: Chuyển alert từ open sang acknowledged.
    """
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    if alert.status != AlertStatusEnum.OPEN.value:
        raise HTTPException(
            status_code=400,
            detail=f"Alert is {alert.status}, only open alerts can be acknowledged"
        )

    # Update status
    old_status = alert.status
    alert.status = AlertStatusEnum.ACKNOWLEDGED.value

    # Update notes if provided
    if request.notes:
        if alert.notes:
            alert.notes += f"\n---\n{request.notes}"
        else:
            alert.notes = request.notes

    # Create timeline event
    create_timeline_event(
        db=db,
        alert_id=alert_id,
        event_type=TimelineEventType.ACKNOWLEDGED,
        actor="soc_analyst",  # In real impl, extract from token
        old_value=old_status,
        new_value=AlertStatusEnum.ACKNOWLEDGED.value,
        comment=request.notes,
    )

    db.commit()
    db.refresh(alert)
    return AlertItem.model_validate(alert)


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: str,
    request: AlertResolveRequest,
    x_internal_token: Optional[str] = Header(None),
    db=Depends(get_db),
) -> AlertItem:
    """
    Resolve or mark as false positive (UC-10, UC-12).

    Per S-QĐ-04: Alert chỉ được chuyển sang resolved hoặc false_positive.
    Per S-QĐ-05: Kết quả điều tra được ghi nhận.
    """
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    if request.status not in [AlertStatusEnum.RESOLVED, AlertStatusEnum.FALSE_POSITIVE]:
        raise HTTPException(
            status_code=400,
            detail="Status must be 'resolved' or 'false_positive'"
        )

    # Validate state transition
    valid_from = [AlertStatusEnum.OPEN.value, AlertStatusEnum.ACKNOWLEDGED.value]
    if alert.status not in valid_from:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot resolve alert from status: {alert.status}"
        )

    # Update alert
    old_status = alert.status
    alert.status = request.status.value
    alert.resolved_by = "soc_analyst"  # In real impl, extract from token
    alert.resolved_at = datetime.utcnow()

    if request.resolution_notes:
        if alert.notes:
            alert.notes += f"\n---\nResolution: {request.resolution_notes}"
        else:
            alert.notes = f"Resolution: {request.resolution_notes}"

    # Create timeline events
    create_timeline_event(
        db=db,
        alert_id=alert_id,
        event_type=TimelineEventType.STATUS_CHANGED,
        actor="soc_analyst",
        old_value=old_status,
        new_value=request.status.value,
        comment=request.notes,
    )

    create_timeline_event(
        db=db,
        alert_id=alert_id,
        event_type=TimelineEventType.RESOLVED,
        actor="soc_analyst",
        old_value=None,
        new_value=request.status.value,
        comment=request.resolution_notes,
    )

    db.commit()
    db.refresh(alert)
    return AlertItem.model_validate(alert)


@router.post("/alerts/{alert_id}/assign")
async def assign_alert(
    alert_id: str,
    request: AlertAssignRequest,
    x_internal_token: Optional[str] = Header(None),
    db=Depends(get_db),
) -> AlertItem:
    """
    Assign alert to a SOC analyst.
    """
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    old_assignee = alert.assigned_to
    alert.assigned_to = request.assigned_to

    # Create timeline event
    event_type = TimelineEventType.ASSIGNED if old_assignee is None else TimelineEventType.STATUS_CHANGED
    create_timeline_event(
        db=db,
        alert_id=alert_id,
        event_type=event_type,
        actor="soc_analyst",
        old_value=old_assignee,
        new_value=request.assigned_to,
        comment=request.notes,
    )

    db.commit()
    db.refresh(alert)
    return AlertItem.model_validate(alert)


@router.post("/alerts/{alert_id}/actions")
async def request_security_action(
    alert_id: str,
    request: AlertActionRequest,
    x_internal_token: Optional[str] = Header(None),
    db=Depends(get_db),
) -> AlertActionResponse:
    """
    Request security action for an alert (UC-11).

    Per S-QĐ-06: Hành động bảo vệ được audit.
    Available actions: REQUIRE_MFA, REVOKE_SESSIONS, LOCK_USER
    """
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    # Get associated login attempt
    login_attempt = db.query(LoginAttempt).filter(
        LoginAttempt.id == alert.login_attempt_id
    ).first()

    if not login_attempt or not login_attempt.user_id:
        raise HTTPException(status_code=400, detail="No user associated with this alert")

    user = db.query(User).filter(User.id == login_attempt.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    action = request.action.upper()
    details = {}

    if action == "REQUIRE_MFA":
        user.admin_mfa_required = True
        user.detection_mfa_once = True
        details = {"mfa_enabled": True, "reason": request.reason}

    elif action == "REVOKE_SESSIONS":
        from app.models import Session
        revoked = db.query(Session).filter(
            Session.user_id == user.id,
            Session.revoked_at.is_(None)
        ).all()
        count = len(revoked)
        for session in revoked:
            session.revoked_at = datetime.utcnow()
        details = {"revoked_count": count, "reason": request.reason}

    elif action == "LOCK_USER":
        user.status = "locked"
        user.locked_at = datetime.utcnow()
        # Also revoke sessions
        from app.models import Session
        revoked = db.query(Session).filter(
            Session.user_id == user.id,
            Session.revoked_at.is_(None)
        ).all()
        for session in revoked:
            session.revoked_at = datetime.utcnow()
        details = {"status": "locked", "sessions_revoked": len(revoked), "reason": request.reason}

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported action: {action}")

    # Create timeline event
    create_timeline_event(
        db=db,
        alert_id=alert_id,
        event_type=TimelineEventType.NOTE_ADDED,
        actor="soc_analyst",
        comment=f"Security action requested: {action}. Reason: {request.reason}",
    )

    db.commit()

    return AlertActionResponse(
        status="applied",
        action=action,
        details=details,
    )


# =============================================================================
# Alert Timeline Endpoints
# =============================================================================

@router.get("/alerts/{alert_id}/timeline", response_model=List[TimelineEvent])
async def get_alert_timeline(
    alert_id: str,
    x_internal_token: Optional[str] = Header(None),
    db=Depends(get_db),
) -> List[TimelineEvent]:
    """
    Get timeline events for an alert.
    """
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    events = db.query(AlertTimeline).filter(
        AlertTimeline.alert_id == alert_id
    ).order_by(AlertTimeline.created_at.asc()).all()

    return [TimelineEvent.model_validate(e) for e in events]


@router.post("/alerts/{alert_id}/timeline")
async def add_timeline_event(
    alert_id: str,
    request: TimelineEventCreate,
    x_internal_token: Optional[str] = Header(None),
    db=Depends(get_db),
) -> TimelineEvent:
    """
    Add a timeline event to an alert.
    Used for notes, escalations, etc.
    """
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    event = create_timeline_event(
        db=db,
        alert_id=alert_id,
        event_type=request.event_type,
        actor="soc_analyst",  # In real impl, extract from token
        comment=request.comment,
    )

    db.commit()
    db.refresh(event)
    return TimelineEvent.model_validate(event)


# Update forward references
AlertEvidence.model_rebuild()

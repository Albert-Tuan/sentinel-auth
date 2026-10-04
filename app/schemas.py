"""
Pydantic schemas for Sentinel Auth API v3.3.
Sync with infra/postgres/schema-*-v3.3.sql definitions.
Canonical decisions: docs/DECISIONS-DETECTION-v3.3.md
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


# =============================================================================
# Common / Shared schemas
# =============================================================================

class HealthResponse(BaseModel):
    status: str = "ok"


class ErrorResponse(BaseModel):
    detail: str
    code: Optional[str] = None


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)


class PaginatedResponse(BaseModel):
    data: List[Any]
    total: int
    page: int
    limit: int
    pages: int


# =============================================================================
# Auth schemas
# =============================================================================

class UserRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]+$")
    email: Optional[str] = None
    password: str = Field(..., min_length=8)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if "@" not in v or "(" in v or ")" in v:
            raise ValueError("Invalid email format")
        return v.lower()


class UserRegisterResponse(BaseModel):
    id: UUID
    username: str
    email: Optional[str] = None
    created_at: datetime


class LoginRequest(BaseModel):
    username: str
    password: str
    # Client IP is derived server-side from X-Forwarded-For / request.client
    # (see app.auth.get_client_ip), never trusted from the request body.


class LoginResponse(BaseModel):
    access_token: str = ""
    refresh_token: str = ""
    mfa_required: bool = False
    session_id: Optional[UUID] = None


class MfaVerifyRequest(BaseModel):
    session_id: UUID
    mfa_code: str = Field(..., pattern=r"^\d{6}$")


class MfaVerifyResponse(BaseModel):
    access_token: str
    refresh_token: str
    session_id: UUID


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None


class LogoutResponse(BaseModel):
    status: str = "ok"


class SessionItem(BaseModel):
    id: UUID
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    expires_at: datetime
    last_activity_at: Optional[datetime] = None
    created_at: datetime
    is_current: bool = False


class SessionList(BaseModel):
    sessions: List[SessionItem]
    total: int


# =============================================================================
# Admin schemas
# =============================================================================

class UserStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    LOCKED = "locked"


class UserRole(str, Enum):
    USER = "USER"
    SECURITY_ADMIN = "SECURITY_ADMIN"
    SOC_ANALYST = "SOC_ANALYST"
    SECURITY_MANAGER = "SECURITY_MANAGER"


class UserItem(BaseModel):
    id: UUID
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    status: UserStatus
    admin_mfa_required: bool
    roles: List[str] = []
    last_login_at: Optional[datetime] = None
    failed_login_count: int
    locked_at: Optional[datetime] = None
    created_at: datetime


class UserList(BaseModel):
    users: List[UserItem]
    total: int
    page: int
    limit: int


class UserListFilter(BaseModel):
    role: Optional[str] = None
    status: Optional[UserStatus] = None


class RoleAssignRequest(BaseModel):
    role: UserRole


class MfaToggleRequest(BaseModel):
    mfa_required: bool


class AuditLogItem(BaseModel):
    id: UUID
    request_id: Optional[UUID] = None
    actor: str
    action: str
    resource: str
    resource_id: Optional[UUID] = None
    before_state: Optional[dict] = None
    after_state: Optional[dict] = None
    change_reason: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime


class AuditLogList(BaseModel):
    logs: List[AuditLogItem]
    total: int
    page: int
    limit: int


class AuditLogFilter(BaseModel):
    actor: Optional[str] = None
    action: Optional[str] = None
    resource: Optional[str] = None
    from_time: Optional[datetime] = None
    to_time: Optional[datetime] = None


# =============================================================================
# Policy schemas (schema v3.3 - rules + config JSONB)
# Canonical structure: docs/DECISIONS-DETECTION-v3.3.md section 1
# =============================================================================

#: The 6 features every rule may reference (UC-DE-02)
ALLOWED_FEATURE_FIELDS = frozenset({
    "hour_of_day",
    "fail_count_24h",
    "ip_change_rate_7d",
    "new_device",
    "average_login_interval_seconds",
    "deviation_score",
})

#: Comparison operators a rule may use
ALLOWED_OPERATORS = frozenset({
    "==", "!=", ">", ">=", "<", "<=", "in", "between", "not_between",
})

#: Operators that require a 2-element [min, max] array
RANGE_OPERATORS = frozenset({"between", "not_between"})


class RuleDefinition(BaseModel):
    """One detection rule. All 7 fields are required - see DECISIONS section 1.2."""

    name: str = Field(..., min_length=1, max_length=100)
    field: str = Field(..., description="Must be one of the 6 features (UC-DE-02)")
    operator: str = Field(..., description="One of: == != > >= < <= in between not_between")
    value: Any = Field(..., description="number | bool | [min,max] | [allowed...]")
    weight: float = Field(..., ge=0.0, le=1.0, description="Rule confidence, 0..1")
    score: float = Field(..., ge=0.0, le=1.0, description="Severity when triggered, 0..1")
    enabled: bool = True
    description: Optional[str] = None

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, v: str) -> str:
        if v not in ALLOWED_OPERATORS:
            raise ValueError(
                f"operator must be one of {sorted(ALLOWED_OPERATORS)}, got {v!r}"
            )
        return v

    @model_validator(mode="after")
    def check_field_and_value(self) -> "RuleDefinition":
        if self.field not in ALLOWED_FEATURE_FIELDS:
            raise ValueError(
                f"field must be one of {sorted(ALLOWED_FEATURE_FIELDS)}, got {self.field!r}"
            )
        if self.operator in RANGE_OPERATORS:
            if not isinstance(self.value, (list, tuple)) or len(self.value) != 2:
                raise ValueError(
                    f"operator {self.operator!r} requires value as [min, max]"
                )
        elif self.operator == "in":
            if not isinstance(self.value, (list, tuple)) or len(self.value) == 0:
                raise ValueError("operator 'in' requires a non-empty list of values")
        elif isinstance(self.value, (list, tuple)):
            raise ValueError(
                f"operator {self.operator!r} requires a single value, not a list"
            )
        return self


class PolicyWeights(BaseModel):
    """Weight of each scoring component. rule + ml must sum to 1.0."""

    rule: float = Field(default=0.4, ge=0.0, le=1.0)
    ml: float = Field(default=0.6, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def check_sum(self) -> "PolicyWeights":
        if self.rule > 0 and self.ml > 0:
            if abs(self.rule + self.ml - 1.0) > 1e-6:
                raise ValueError("weights.rule + weights.ml must equal 1.0")
        return self


class PolicyThresholds(BaseModel):
    """Risk level boundaries. Must be non-decreasing within 0..1."""

    low: float = Field(default=0.25, ge=0.0, le=1.0)
    medium: float = Field(default=0.50, ge=0.0, le=1.0)
    high: float = Field(default=0.75, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def check_ordering(self) -> "PolicyThresholds":
        if not (self.low <= self.medium <= self.high):
            raise ValueError("thresholds must satisfy low <= medium <= high")
        return self


class PolicyConfig(BaseModel):
    """contents of policies.config JSONB."""

    weights: PolicyWeights = Field(default_factory=PolicyWeights)
    thresholds: PolicyThresholds = Field(default_factory=PolicyThresholds)


class PolicyCreate(BaseModel):
    """Body of POST /api/v1/policies (UC-DE-15)."""

    version: str = Field(..., pattern=r"^v\d+(\.\d+)*$", examples=["v1.0"])
    name: Optional[str] = None
    description: Optional[str] = None
    rules: List[RuleDefinition] = Field(..., min_length=1)
    config: PolicyConfig = Field(default_factory=PolicyConfig)

    @field_validator("rules")
    @classmethod
    def check_unique_names(cls, rules: List[RuleDefinition]) -> List[RuleDefinition]:
        names = [r.name for r in rules]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate rule names: {sorted(dupes)}")
        return rules


class PolicyItem(BaseModel):
    id: UUID
    version: str
    name: Optional[str] = None
    description: Optional[str] = None
    rules: List[RuleDefinition] = []
    config: PolicyConfig = Field(default_factory=PolicyConfig)
    is_active: bool
    created_by: Optional[UUID] = None
    created_at: datetime
    activated_at: Optional[datetime] = None
    deactivated_at: Optional[datetime] = None


class PolicyList(BaseModel):
    policies: List[PolicyItem]
    total: int


# =============================================================================
# SOC Alert schemas
# =============================================================================

class AlertStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    FALSE_POSITIVE = "false_positive"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class LoginAttemptSummary(BaseModel):
    id: UUID
    event_id: UUID
    timestamp: datetime
    outcome: str
    username_attempted: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    mfa_used: bool = False
    risk_level: Optional[RiskLevel] = None


class RiskAssessmentSummary(BaseModel):
    rule_score: Optional[float] = None
    ml_score: Optional[float] = None
    combined_score: Optional[float] = None
    ml_status: Optional[str] = None
    ml_model_version: Optional[str] = None
    risk_level: Optional[RiskLevel] = None
    decision: Optional[str] = None


class AlertItem(BaseModel):
    id: UUID
    login_attempt_id: UUID
    status: AlertStatus
    risk_level: Optional[RiskLevel] = None
    detection_reason: Optional[str] = None
    detection_scores: Optional[dict] = None
    assigned_to_id: Optional[UUID] = None
    resolved_by_id: Optional[UUID] = None
    resolved_at: Optional[datetime] = None
    resolution: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    # Nested data
    login_attempt: Optional[LoginAttemptSummary] = None
    risk_assessment: Optional[RiskAssessmentSummary] = None


class AlertList(BaseModel):
    alerts: List[AlertItem]
    total: int
    page: int
    limit: int


class AlertFilter(BaseModel):
    status: Optional[AlertStatus] = None
    risk_level: Optional[RiskLevel] = None
    assigned_to_id: Optional[UUID] = None


class AlertTimelineItem(BaseModel):
    id: UUID
    alert_id: UUID
    event_type: str
    actor_id: Optional[UUID] = None
    actor_type: str = "user"
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    comment: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime


class AlertTimelineList(BaseModel):
    timeline: List[AlertTimelineItem]
    total: int


class AlertNoteRequest(BaseModel):
    comment: str = Field(..., min_length=1, max_length=2000)


class AlertAssignRequest(BaseModel):
    assigned_to_id: UUID
    comment: Optional[str] = None


class AlertAcknowledgeRequest(BaseModel):
    notes: Optional[str] = None


class AlertResolveRequest(BaseModel):
    resolution: str = Field(
        ...,
        pattern=r"^(true_attack|false_positive|benign_true_positive|insufficient_evidence)$",
        description="One of: true_attack, false_positive, benign_true_positive, insufficient_evidence",
    )
    notes: Optional[str] = None


class AlertEscalateRequest(BaseModel):
    reason: str = Field(..., min_length=1)
    escalate_to_id: Optional[UUID] = None
    notes: Optional[str] = None


# =============================================================================
# Detection engine internal schemas
# API paths: /api/v1/internal/*  (see DECISIONS section 5)
# =============================================================================

class LoginEventRequest(BaseModel):
    """Body of POST /api/v1/internal/login-events (UC-DE-01).

    Sent by core-app's outbox poller, originating from the core-db
    outbox_events table.
    """

    event_id: UUID = Field(..., description="Idempotency key from core-app")
    username_attempted: str = Field(..., min_length=1, max_length=50)
    user_id: Optional[UUID] = None
    outcome: str = Field(
        ...,
        # Must stay in sync with the CHECK constraint on
        # login_attempts.outcome in infra/postgres/schema-detection-v3.3.sql
        pattern=r"^(success|failure|mfa_required|mfa_success|mfa_failed|blocked|locked|rate_limited)$",
    )
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    mfa_used: bool = False
    timestamp: datetime
    request_id: Optional[UUID] = None
    # Optional pre-computed features; if omitted the engine builds them
    features: Optional[Dict[str, Any]] = None


class LoginEventResponse(BaseModel):
    """Response of POST /api/v1/internal/login-events - returns 202 Accepted."""

    status: str = "accepted"
    event_id: UUID
    login_attempt_id: UUID
    processing: str = "pending"


class LoginAttemptStatusResponse(BaseModel):
    """Response of GET /api/v1/internal/login-attempts/{id}."""

    login_attempt_id: UUID
    status: str = Field(..., description="pending | processed | failed")
    risk_level: Optional[RiskLevel] = None
    decision: Optional[str] = None
    alert_id: Optional[UUID] = None


class DetectionFeatureVector(BaseModel):
    """The 6 features a rule may reference (UC-DE-02)."""

    hour_of_day: Optional[int] = Field(default=None, ge=0, le=23)
    fail_count_24h: Optional[int] = Field(default=None, ge=0)
    ip_change_rate_7d: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    new_device: Optional[bool] = None
    average_login_interval_seconds: Optional[int] = Field(default=None, ge=0)
    deviation_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class RuleHit(BaseModel):
    """One evaluated rule. score_contribution values sum to rule_score."""

    rule_name: str
    rule_id: Optional[UUID] = None
    triggered: bool
    score: float = Field(..., ge=0.0, le=1.0, description="Rule's configured score")
    weight: float = Field(..., ge=0.0, le=1.0, description="Rule's configured weight")
    score_contribution: float = Field(
        ..., ge=0.0, le=1.0,
        description="score * weight / total_weight; sums exactly to rule_score",
    )
    reason: Optional[str] = None


class DetectionResponse(BaseModel):
    """Result of evaluating one login attempt (formula: DECISIONS section 2)."""

    rule_score: float = Field(..., ge=0.0, le=1.0)
    ml_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    combined_score: float = Field(..., ge=0.0, le=1.0)
    ml_status: str = Field(default="unavailable", description="success | unavailable | error")
    ml_model_version: Optional[str] = None
    ml_reason_codes: List[str] = []
    risk_level: RiskLevel
    decision: str = Field(..., description="allow | challenge | block")
    rule_hits: List[RuleHit] = []
    alert_id: Optional[UUID] = None


class MlScoreRequest(BaseModel):
    """Body of POST /api/v1/internal/ml/score sent to ML Service (UC-DE-03)."""

    request_id: UUID
    features: DetectionFeatureVector


class MlScoreResponse(BaseModel):
    """ML Service response. Field name is fixed by the ML team API contract."""

    normalized_anomaly_score: float = Field(..., ge=0.0, le=1.0)
    is_anomaly: bool = False
    model_version: Optional[str] = None
    reason_codes: List[str] = []
    model_status: str = "ready"


class SecurityAction(str, Enum):
    REQUIRE_MFA = "REQUIRE_MFA"
    REVOKE_SESSIONS = "REVOKE_SESSIONS"
    LOCK_USER = "LOCK_USER"
    FORCE_LOGOUT = "FORCE_LOGOUT"


class ActionRequest(BaseModel):
    """Body of POST /api/v1/internal/actions (UC-DE-07)."""

    action: SecurityAction
    target_user_id: UUID
    reason: str = Field(..., min_length=1)
    alert_id: Optional[UUID] = None
    severity: Optional[RiskLevel] = None
    idempotency_key: Optional[str] = None


class ActionResponse(BaseModel):
    status: str = "applied"
    action: SecurityAction
    target_user_id: UUID
    details: Optional[dict] = None


# =============================================================================
# Token / JWT schemas (for internal use)
# =============================================================================

class TokenPayload(BaseModel):
    sub: str  # user_id
    username: str
    roles: List[str]
    session_id: Optional[UUID] = None
    jti: Optional[str] = None
    exp: Optional[int] = None
    iat: Optional[int] = None
    type: str = "access"  # 'access' | 'refresh'

"""
Pydantic schemas for Sentinel Auth API v2.
Sync with schema-v2.sql definitions.
"""
from datetime import datetime
from typing import Optional, List, Any
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, EmailStr, Field, field_validator


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
    source_ip: Optional[str] = None


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
# Policy / Rule versioning schemas
# =============================================================================

class RuleDefinition(BaseModel):
    name: str
    description: Optional[str] = None
    conditions: dict = {}
    score: float = Field(..., ge=0.0, le=1.0)
    enabled: bool = True


class PolicyRulesJson(BaseModel):
    rules: List[RuleDefinition]
    weights: dict = {"rule": 0.4, "ml": 0.6}
    thresholds: dict = {"challenge": 0.3, "block": 0.7}


class PolicyVersionItem(BaseModel):
    id: UUID
    version: str
    description: Optional[str] = None
    rules_json: dict
    weights: dict
    thresholds: dict
    is_active: bool
    created_by_user_id: Optional[UUID] = None
    created_at: datetime
    activated_at: Optional[datetime] = None
    deactivated_at: Optional[datetime] = None


class PolicyVersionList(BaseModel):
    versions: List[PolicyVersionItem]
    total: int


class PolicyVersionCreate(BaseModel):
    version: str = Field(..., pattern=r"^v\d+(\.\d+)*$")
    description: Optional[str] = None
    rules_json: dict
    weights: Optional[dict] = None
    thresholds: Optional[dict] = None


class PolicyVersionActivate(BaseModel):
    version_id: UUID


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
    occurred_at: datetime
    outcome: str
    source_ip: Optional[str] = None
    user_agent: Optional[str] = None
    risk_level: Optional[RiskLevel] = None


class RiskAssessmentSummary(BaseModel):
    rule_score: Optional[float] = None
    anomaly_score: Optional[float] = None
    ml_score: Optional[float] = None
    ml_status: Optional[str] = None
    ml_model_version: Optional[str] = None
    combined_score: Optional[float] = None
    risk_level: Optional[RiskLevel] = None
    decision: Optional[str] = None


class AlertItem(BaseModel):
    id: UUID
    login_attempt_id: UUID
    status: AlertStatus
    risk_level: Optional[RiskLevel] = None
    detection_reason: Optional[str] = None
    detection_scores: Optional[dict] = None
    assigned_to: Optional[str] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
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
    assigned_to: Optional[str] = None


class AlertAcknowledgeRequest(BaseModel):
    notes: Optional[str] = None


class AlertResolveRequest(BaseModel):
    status: AlertStatus = Field(..., description="Must be 'resolved' or 'false_positive'")
    notes: Optional[str] = None


# =============================================================================
# Detection engine schemas (internal)
# =============================================================================

class DetectionFeatureVector(BaseModel):
    login_hour: Optional[int] = None
    login_day: Optional[int] = None
    ip_country: Optional[str] = None
    ip_reputation: Optional[float] = None
    user_agent_family: Optional[str] = None
    asn_reputation: Optional[float] = None
    failed_attempts_1h: int = 0
    failed_attempts_24h: int = 0
    geo_velocity_kmh: Optional[float] = None
    login_streak: int = 0
    is_known_device: bool = False
    is_known_ip: bool = False
    mfa_used_recently: bool = False


class DetectionRequest(BaseModel):
    username: str
    user_id: Optional[UUID] = None
    source_ip: str
    user_agent: Optional[str] = None
    timestamp: Optional[datetime] = None
    failed_attempts: int = 0
    detection_features: Optional[dict] = None
    risk_level_override: Optional[str] = None


class RuleHit(BaseModel):
    rule_name: str
    rule_id: Optional[str] = None
    score: float
    reason: Optional[str] = None


class DetectionResponse(BaseModel):
    rule_score: float
    anomaly_score: Optional[float] = None
    ml_score: Optional[float] = None
    ml_status: str = "unavailable"
    ml_model_version: Optional[str] = None
    combined_score: float
    risk_level: RiskLevel
    decision: str  # 'allow' | 'challenge' | 'block'
    rule_hits: List[RuleHit] = []
    alert_id: Optional[UUID] = None


class MlScoreRequest(BaseModel):
    features: DetectionFeatureVector


class MlScoreResponse(BaseModel):
    anomaly_score: float
    ml_status: str = "success"  # 'success' | 'unavailable' | 'error'
    model_version: Optional[str] = None


class SecurityAction(str, Enum):
    REQUIRE_MFA = "REQUIRE_MFA"
    REVOKE_SESSIONS = "REVOKE_SESSIONS"
    LOCK_USER = "LOCK_USER"


class ActionRequest(BaseModel):
    action: SecurityAction
    target_user_id: UUID
    reason: str


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

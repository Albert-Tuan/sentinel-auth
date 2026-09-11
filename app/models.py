"""
SQLAlchemy ORM models for Sentinel Auth v2.
Sync with schema-v2.sql definitions.
Import Base from app.db: from app.models import Base
"""
from datetime import datetime
from uuid import uuid4
from typing import Optional, List
from sqlalchemy import (
    Column, String, Text, Boolean, Integer, Numeric, DateTime,
    ForeignKey, CheckConstraint, UniqueConstraint, Index, JSON, func
)
from sqlalchemy.dialects.postgresql import UUID, INET, ARRAY
from sqlalchemy.orm import relationship, Mapped, mapped_column
from app.db import Base


# =============================================================================
# Helper: auto-update timestamp
# =============================================================================

def now_utc():
    return datetime.utcnow()


# =============================================================================
# Role (reference table)
# =============================================================================

class Role(Base):
    """Reference table for roles."""
    __tablename__ = "roles"

    id: Mapped[str] = Column(String, primary_key=True)
    name: Mapped[str] = Column(Text, nullable=False)
    description: Mapped[Optional[str]] = Column(Text, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    # Relationships
    user_roles: Mapped[List["UserRole"]] = relationship("UserRole", back_populates="role")


# =============================================================================
# User
# =============================================================================

class User(Base):
    """Core user accounts with authentication and MFA settings."""
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("length(username) BETWEEN 3 AND 50", name="chk_username_length"),
        CheckConstraint("username ~ '^[a-zA-Z0-9_]+$'", name="chk_username_chars"),
        Index("idx_users_username", "username"),
        Index("idx_users_email", "email"),
        Index("idx_users_status", "status"),
    )

    id: Mapped[str] = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    username: Mapped[str] = Column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = Column(Text, nullable=False)
    email: Mapped[Optional[str]] = Column(Text, nullable=True)
    full_name: Mapped[Optional[str]] = Column(Text, nullable=True)
    status: Mapped[str] = Column(Text, nullable=False, default="active")
    admin_mfa_required: Mapped[bool] = Column(Boolean, nullable=False, default=False)
    detection_mfa_once: Mapped[bool] = Column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    failed_login_count: Mapped[int] = Column(Integer, nullable=False, default=0)
    locked_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc)

    # Relationships
    roles: Mapped[List["UserRole"]] = relationship("UserRole", back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[List["Session"]] = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    pre_auth_transactions: Mapped[List["PreAuthTransaction"]] = relationship("PreAuthTransaction", back_populates="user")
    login_attempts: Mapped[List["LoginAttempt"]] = relationship("LoginAttempt", back_populates="user")
    audit_logs: Mapped[List["AuditLog"]] = relationship("AuditLog", foreign_keys="AuditLog.actor", back_populates="actor_user")


# =============================================================================
# UserRole (many-to-many)
# =============================================================================

class UserRole(Base):
    """Many-to-many relationship between users and roles."""
    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_role"),
        Index("idx_user_roles_user_id", "user_id"),
        Index("idx_user_roles_role_id", "role_id"),
    )

    user_id: Mapped[str] = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[str] = Column(String, ForeignKey("roles.id"), primary_key=True)
    assigned_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    assigned_by: Mapped[Optional[str]] = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="roles", foreign_keys=[user_id])
    role: Mapped["Role"] = relationship("Role", back_populates="user_roles")
    assigner: Mapped[Optional["User"]] = relationship("User", foreign_keys=[assigned_by])


# =============================================================================
# Session
# =============================================================================

class Session(Base):
    """Active user sessions with JWT refresh tokens."""
    __tablename__ = "sessions"
    __table_args__ = (
        Index("idx_sessions_user_id", "user_id"),
        Index("idx_sessions_access_hash", "access_token_hash"),
        Index("idx_sessions_expires_at", "expires_at"),
        Index("idx_sessions_token_jti", "token_jti", postgresql_where=token_jti.isnot(None)),
        Index("idx_sessions_refresh_family", "refresh_token_family", postgresql_where=refresh_token_family.isnot(None)),
    )

    id: Mapped[str] = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[str] = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    access_token_hash: Mapped[str] = Column(Text, nullable=False)
    refresh_token_hash: Mapped[Optional[str]] = Column(Text, nullable=True)
    refresh_token_family: Mapped[Optional[str]] = Column(UUID(as_uuid=True), nullable=True)
    token_jti: Mapped[Optional[str]] = Column(Text, nullable=True, unique=True)
    expires_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    ip_address: Mapped[Optional[str]] = Column(INET, nullable=True)
    user_agent: Mapped[Optional[str]] = Column(Text, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="sessions")


# =============================================================================
# PreAuthTransaction (MFA)
# =============================================================================

class PreAuthTransaction(Base):
    """Pending MFA challenges before session creation."""
    __tablename__ = "pre_auth_transactions"
    __table_args__ = (
        Index("idx_pre_auth_user_id", "user_id"),
        Index("idx_pre_auth_status", "status"),
        Index("idx_pre_auth_expires", "expires_at"),
        Index("idx_pre_auth_user_status_expires", "user_id", "status", "expires_at"),
    )

    id: Mapped[str] = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[str] = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    mfa_type: Mapped[str] = Column(Text, nullable=False, default="one_time",
                                    doc="'persistent' or 'one_time'")
    expires_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = Column(Text, nullable=False, default="pending")
    bound_ip: Mapped[Optional[str]] = Column(Text, nullable=True)
    notification_id: Mapped[Optional[str]] = Column(UUID(as_uuid=True), ForeignKey("mfa_notifications.id", ondelete="SET NULL"), nullable=True)
    fail_count: Mapped[int] = Column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="pre_auth_transactions")
    notification: Mapped[Optional["MfaNotification"]] = relationship("MfaNotification", foreign_keys=[notification_id])


# =============================================================================
# MfaNotification (NEW)
# =============================================================================

class MfaNotification(Base):
    """Email/SMS OTP notification lifecycle tracking."""
    __tablename__ = "mfa_notifications"
    __table_args__ = (
        Index("idx_mfa_notif_transaction_id", "pre_auth_transaction_id"),
        Index("idx_mfa_notif_recipient", "recipient"),
        Index("idx_mfa_notif_expires", "expires_at"),
    )

    id: Mapped[str] = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    pre_auth_transaction_id: Mapped[str] = Column(UUID(as_uuid=True), ForeignKey("pre_auth_transactions.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = Column(Text, nullable=False, default="email")
    recipient: Mapped[str] = Column(Text, nullable=False)
    mfa_code_hash: Mapped[str] = Column(Text, nullable=False, doc="Argon2id hash of 6-digit OTP")
    sent_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    delivered_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[Optional[str]] = Column(Text, nullable=True)
    expires_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    # Relationships
    pre_auth_transaction: Mapped["PreAuthTransaction"] = relationship("PreAuthTransaction", back_populates="notification", foreign_keys=[pre_auth_transaction_id])


# =============================================================================
# RateLimit
# =============================================================================

class RateLimit(Base):
    """Rate limiting per IP and action. Composite PK (ip_address, action)."""
    __tablename__ = "rate_limits"

    ip_address: Mapped[str] = Column(INET, primary_key=True)
    action: Mapped[str] = Column(Text, primary_key=True)
    count: Mapped[int] = Column(Integer, nullable=False, default=1)
    max_count: Mapped[int] = Column(Integer, nullable=False, default=5)
    window_start: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    __table_args__ = (
        CheckConstraint("count >= 0", name="chk_rate_count"),
        CheckConstraint("max_count > 0", name="chk_rate_max"),
        Index("idx_rate_limits_window", "window_start"),
    )


# =============================================================================
# PolicyVersion (renamed from RuleVersion)
# =============================================================================

class PolicyVersion(Base):
    """Versioned detection rule sets with weights and thresholds."""
    __tablename__ = "policy_versions"
    __table_args__ = (
        UniqueConstraint("version", name="uq_policy_version"),
        Index("idx_policy_versions_version", "version"),
        Index("idx_policy_versions_is_active", "is_active", postgresql_where=is_active.is_(True)),
    )

    id: Mapped[str] = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    version: Mapped[str] = Column(Text, nullable=False, unique=True)
    description: Mapped[Optional[str]] = Column(Text, nullable=True)
    rules_json: Mapped[dict] = Column(JSON, nullable=False)
    weights: Mapped[dict] = Column(JSON, nullable=False, default=lambda: {"rule": 0.4, "ml": 0.6})
    thresholds: Mapped[dict] = Column(JSON, nullable=False, default=lambda: {"challenge": 0.3, "block": 0.7})
    is_active: Mapped[bool] = Column(Boolean, nullable=False, default=False)
    created_by_user_id: Mapped[Optional[str]] = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    activated_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    deactivated_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    creator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by_user_id])
    login_attempts: Mapped[List["LoginAttempt"]] = relationship("LoginAttempt", back_populates="policy_version")
    risk_assessments: Mapped[List["RiskAssessment"]] = relationship("RiskAssessment", back_populates="policy_version")
    alerts: Mapped[List["Alert"]] = relationship("Alert", back_populates="policy_version")


# =============================================================================
# LoginAttempt
# =============================================================================

class LoginAttempt(Base):
    """All login attempts with outcome and risk metadata."""
    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("idx_login_attempts_user_id", "user_id"),
        Index("idx_login_attempts_occurred", "occurred_at"),
        Index("idx_login_attempts_outcome", "outcome"),
        Index("idx_login_attempts_risk_level", "risk_level"),
        Index("idx_login_attempts_request_id", "request_id"),
        Index("idx_login_attempts_username_attempted", "username_attempted"),
    )

    id: Mapped[str] = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[Optional[str]] = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username_attempted: Mapped[Optional[str]] = Column(Text, nullable=True)
    occurred_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    outcome: Mapped[str] = Column(Text, nullable=False)
    source_ip: Mapped[Optional[str]] = Column(INET, nullable=True)
    user_agent: Mapped[Optional[str]] = Column(Text, nullable=True)
    rate_limited: Mapped[bool] = Column(Boolean, nullable=False, default=False)
    policy_version_id: Mapped[Optional[str]] = Column(UUID(as_uuid=True), ForeignKey("policy_versions.id"), nullable=True)
    request_id: Mapped[str] = Column(UUID(as_uuid=True), nullable=False, default=uuid4)
    detection_features: Mapped[Optional[dict]] = Column(JSON, nullable=True)
    primary_alert_id: Mapped[Optional[str]] = Column(UUID(as_uuid=True), ForeignKey("alerts.id"), nullable=True)
    risk_level: Mapped[Optional[str]] = Column(Text, nullable=True)
    mfa_used: Mapped[bool] = Column(Boolean, nullable=False, default=False)
    detection_decision: Mapped[Optional[str]] = Column(Text, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc)

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="login_attempts")
    policy_version: Mapped[Optional["PolicyVersion"]] = relationship("PolicyVersion", back_populates="login_attempts")
    primary_alert: Mapped[Optional["Alert"]] = relationship("Alert", foreign_keys=[primary_alert_id])
    risk_assessment: Mapped[Optional["RiskAssessment"]] = relationship("RiskAssessment", back_populates="login_attempt", uselist=False)
    detection_logs: Mapped[List["DetectionLog"]] = relationship("DetectionLog", back_populates="login_attempt")
    alerts: Mapped[List["Alert"]] = relationship("Alert", foreign_keys="Alert.login_attempt_id", back_populates="login_attempt")


# =============================================================================
# RiskAssessment
# =============================================================================

class RiskAssessment(Base):
    """Per-attempt risk scoring (rule + ML + combined). 1:1 with LoginAttempt."""
    __tablename__ = "risk_assessments"
    __table_args__ = (
        UniqueConstraint("login_attempt_id", name="uq_risk_assessment_login_attempt"),
        Index("idx_risk_login_attempt_id", "login_attempt_id"),
        Index("idx_risk_risk_level", "risk_level"),
    )

    id: Mapped[str] = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    login_attempt_id: Mapped[str] = Column(UUID(as_uuid=True), ForeignKey("login_attempts.id", ondelete="CASCADE"), nullable=False)
    policy_version_id: Mapped[Optional[str]] = Column(UUID(as_uuid=True), ForeignKey("policy_versions.id"), nullable=True)
    rule_score: Mapped[Optional[float]] = Column(Numeric(5, 4), nullable=True)
    anomaly_score: Mapped[Optional[float]] = Column(Numeric(5, 4), nullable=True)
    ml_score: Mapped[Optional[float]] = Column(Numeric(5, 4), nullable=True)
    ml_status: Mapped[Optional[str]] = Column(Text, nullable=True)
    ml_model_version: Mapped[Optional[str]] = Column(Text, nullable=True)
    rule_hits: Mapped[Optional[dict]] = Column(JSON, nullable=True)
    ml_features_used: Mapped[Optional[dict]] = Column(JSON, nullable=True)
    combined_score: Mapped[Optional[float]] = Column(Numeric(5, 4), nullable=True)
    risk_level: Mapped[Optional[str]] = Column(Text, nullable=True)
    decision: Mapped[Optional[str]] = Column(Text, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    # Relationships
    login_attempt: Mapped["LoginAttempt"] = relationship("LoginAttempt", back_populates="risk_assessment")
    policy_version: Mapped[Optional["PolicyVersion"]] = relationship("PolicyVersion", back_populates="risk_assessments")


# =============================================================================
# DetectionLog
# =============================================================================

class DetectionLog(Base):
    """Detailed audit trail of detection engine decisions."""
    __tablename__ = "detection_logs"
    __table_args__ = (
        Index("idx_detection_logs_login_id", "login_attempt_id"),
        Index("idx_detection_logs_stage", "stage"),
        Index("idx_detection_logs_request_id", "request_id"),
    )

    id: Mapped[str] = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    login_attempt_id: Mapped[Optional[str]] = Column(UUID(as_uuid=True), ForeignKey("login_attempts.id", ondelete="SET NULL"), nullable=True)
    request_id: Mapped[Optional[str]] = Column(UUID(as_uuid=True), nullable=True)
    stage: Mapped[str] = Column(Text, nullable=False)
    stage_detail: Mapped[Optional[str]] = Column(Text, nullable=True)
    rule_id: Mapped[Optional[str]] = Column(UUID(as_uuid=True), nullable=True)
    rule_name: Mapped[Optional[str]] = Column(Text, nullable=True)
    score: Mapped[Optional[float]] = Column(Numeric(5, 4), nullable=True)
    decision: Mapped[Optional[str]] = Column(Text, nullable=True)
    reason: Mapped[Optional[str]] = Column(Text, nullable=True)
    details: Mapped[Optional[dict]] = Column(JSON, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    # Relationships
    login_attempt: Mapped[Optional["LoginAttempt"]] = relationship("LoginAttempt", back_populates="detection_logs")


# =============================================================================
# Alert
# =============================================================================

class Alert(Base):
    """SOC alerts created from high-risk login attempts."""
    __tablename__ = "alerts"
    __table_args__ = (
        Index("idx_alerts_login_attempt_id", "login_attempt_id"),
        Index("idx_alerts_status", "status"),
        Index("idx_alerts_risk_level", "risk_level"),
        Index("idx_alerts_assigned_to", "assigned_to"),
        Index("idx_alerts_created_at", "created_at"),
    )

    id: Mapped[str] = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    login_attempt_id: Mapped[str] = Column(UUID(as_uuid=True), ForeignKey("login_attempts.id", ondelete="CASCADE"), nullable=False)
    policy_version_id: Mapped[Optional[str]] = Column(UUID(as_uuid=True), ForeignKey("policy_versions.id"), nullable=True)
    request_id: Mapped[Optional[str]] = Column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = Column(Text, nullable=False, default="open")
    risk_level: Mapped[Optional[str]] = Column(Text, nullable=True)
    detection_reason: Mapped[Optional[str]] = Column(Text, nullable=True)
    detection_scores: Mapped[Optional[dict]] = Column(JSON, nullable=True)
    assigned_to: Mapped[Optional[str]] = Column(Text, nullable=True)
    resolved_by: Mapped[Optional[str]] = Column(Text, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    notes: Mapped[Optional[str]] = Column(Text, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc)

    # Relationships
    login_attempt: Mapped["LoginAttempt"] = relationship("LoginAttempt", foreign_keys=[login_attempt_id], back_populates="alerts")
    policy_version: Mapped[Optional["PolicyVersion"]] = relationship("PolicyVersion", back_populates="alerts")


# =============================================================================
# AuditLog
# =============================================================================

class AuditLog(Base):
    """Immutable audit trail of all admin and system actions."""
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_logs_actor", "actor"),
        Index("idx_audit_logs_action", "action"),
        Index("idx_audit_logs_resource", "resource"),
        Index("idx_audit_logs_created_at", "created_at"),
        Index("idx_audit_logs_request_id", "request_id"),
    )

    id: Mapped[str] = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    request_id: Mapped[Optional[str]] = Column(UUID(as_uuid=True), nullable=True)
    actor: Mapped[str] = Column(Text, nullable=False)
    action: Mapped[str] = Column(Text, nullable=False)
    resource: Mapped[str] = Column(Text, nullable=False)
    resource_id: Mapped[Optional[str]] = Column(UUID(as_uuid=True), nullable=True)
    before_state: Mapped[Optional[dict]] = Column(JSON, nullable=True)
    after_state: Mapped[Optional[dict]] = Column(JSON, nullable=True)
    change_reason: Mapped[Optional[str]] = Column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = Column(INET, nullable=True)
    user_agent: Mapped[Optional[str]] = Column(Text, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    # Relationships
    actor_user: Mapped[Optional["User"]] = relationship("User", foreign_keys="AuditLog.actor", back_populates="audit_logs", primaryjoin="AuditLog.actor==User.id", viewonly=True)

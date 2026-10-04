"""
SQLAlchemy ORM models for Sentinel Auth v3.3.

The SQL files in ``infra/postgres/`` are the single source of truth; this
module mirrors them 1:1 (same table names, same column names, same types).
When the two disagree, the SQL schema wins - see
``scripts/_audit_orm_vs_sql.py`` which diffs them.

Detached conventions
--------------------
* ``id`` is a surrogate key on every table, even when the SQL declares a
  natural/composite primary key as well (e.g. ``user_roles``, ``rate_limits``).
* ``created_at``/``updated_at`` are handled in Python; the SQL also installs
  ``update_updated_at_column()`` triggers, so either path keeps them fresh.
* Columns prefixed with a comment marked *cross-DB* reference a table that
  lives in another database and therefore cannot be a real ``ForeignKey``.
"""
from datetime import datetime
from typing import Any, List, Optional
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Mapped, relationship

from app.db import Base


def now_utc() -> datetime:
    return datetime.utcnow()


#: Postgres-only column types, with a TEXT fallback so the same models can
#: create their schema on SQLite (used by the test suite).
def uuid_type() -> UUID:
    return UUID(as_uuid=True)


def inet_type() -> INET:
    return INET().with_variant(Text(), "sqlite")


#: ``~`` is the Postgres regex-match operator. SQLite has no equivalent, so the
#: constraint is written with ``GLOB`` there; both patterns accept exactly the
#: same usernames (``^[a-zA-Z0-9_]+$``).
USERNAME_CHARS_PG = "username ~ '^[a-zA-Z0-9_]+$'"
USERNAME_CHARS_SQLITE = "username GLOB '[a-zA-Z0-9_]*' AND username NOT GLOB '*[^a-zA-Z0-9_]*'"


# =============================================================================
# Core database - reference and identity
# =============================================================================

class Role(Base):
    """Role definitions with i18n support."""
    __tablename__ = "roles"

    id: Mapped[str] = Column(Text, primary_key=True)
    name: Mapped[str] = Column(Text, nullable=False)
    name_vi: Mapped[str] = Column(Text, nullable=False)
    description: Mapped[Optional[str]] = Column(Text, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    user_roles: Mapped[List["UserRole"]] = relationship("UserRole", back_populates="role")


class User(Base):
    """Core user accounts with authentication and MFA settings."""
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("length(username) BETWEEN 3 AND 50", name="chk_username_length"),
        CheckConstraint(USERNAME_CHARS_PG, name="chk_username_chars"),
        Index("idx_users_username", "username"),
        Index("idx_users_email", "email"),
        Index("idx_users_status", "status"),
    )

    id: Mapped[str] = Column(uuid_type(), primary_key=True, default=uuid4)
    username: Mapped[str] = Column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = Column(Text, nullable=False)
    email: Mapped[Optional[str]] = Column(Text, nullable=True, unique=True)
    full_name: Mapped[Optional[str]] = Column(Text, nullable=True)
    status: Mapped[str] = Column(Text, nullable=False, default="active")
    admin_mfa_required: Mapped[bool] = Column(Boolean, nullable=False, default=False)
    detection_mfa_once: Mapped[bool] = Column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    failed_login_count: Mapped[int] = Column(Integer, nullable=False, default=0)
    locked_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = Column(
        DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc
    )

    # Relationships
    # user_roles has two FKs to users (user_id and assigned_by), so the join
    # condition must be stated explicitly.
    roles: Mapped[List["UserRole"]] = relationship(
        "UserRole",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="UserRole.user_id",
    )
    sessions: Mapped[List["Session"]] = relationship(
        "Session", back_populates="user", cascade="all, delete-orphan"
    )
    mfa_transactions: Mapped[List["MfaTransaction"]] = relationship(
        "MfaTransaction", back_populates="user", cascade="all, delete-orphan"
    )
    trusted_devices: Mapped[List["UserTrustedDevice"]] = relationship(
        "UserTrustedDevice", back_populates="user", cascade="all, delete-orphan"
    )
    notifications: Mapped[List["UserNotification"]] = relationship(
        "UserNotification", back_populates="user", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[List["AuditLog"]] = relationship(
        "AuditLog", back_populates="actor_user", cascade="all, delete-orphan"
    )


class UserRole(Base):
    """User-role assignments with audit trail."""
    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_role"),
        Index("idx_user_roles_user", "user_id"),
        Index("idx_user_roles_role", "role_id"),
        Index("idx_user_roles_assigned_by", "assigned_by"),
    )

    id: Mapped[str] = Column(uuid_type(), primary_key=True, default=uuid4)
    user_id: Mapped[str] = Column(uuid_type(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[str] = Column(Text, ForeignKey("roles.id"), nullable=False)
    assigned_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    assigned_by: Mapped[Optional[str]] = Column(uuid_type(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="roles", foreign_keys=[user_id])
    role: Mapped["Role"] = relationship("Role", back_populates="user_roles")
    assigner: Mapped[Optional["User"]] = relationship("User", foreign_keys=[assigned_by])


class IpAddress(Base):
    """Normalized IP address tracking."""
    __tablename__ = "ip_addresses"
    __table_args__ = (
        UniqueConstraint("ip_address", name="uq_ip_address"),
        Index("idx_ip_addresses_first_seen", "first_seen_at"),
        Index("idx_ip_addresses_country", "country_code"),
    )

    id: Mapped[str] = Column(uuid_type(), primary_key=True, default=uuid4)
    ip_address: Mapped[str] = Column(inet_type(), nullable=False)
    country_code: Mapped[Optional[str]] = Column(Text, nullable=True)
    country_name: Mapped[Optional[str]] = Column(Text, nullable=True)
    is_proxy: Mapped[bool] = Column(Boolean, nullable=False, default=False)
    is_vpn: Mapped[bool] = Column(Boolean, nullable=False, default=False)
    is_tor: Mapped[bool] = Column(Boolean, nullable=False, default=False)
    first_seen_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    last_seen_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    sessions: Mapped[List["Session"]] = relationship("Session", back_populates="ip_address")


class Session(Base):
    """Active user sessions with JWT refresh tokens."""
    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("token_jti", name="uq_sessions_token_jti"),
        Index("idx_sessions_user", "user_id"),
        Index("idx_sessions_access_hash", "access_token_hash"),
        Index("idx_sessions_expires", "expires_at"),
        Index("idx_sessions_ip", "ip_address_id"),
    )

    id: Mapped[str] = Column(uuid_type(), primary_key=True, default=uuid4)
    user_id: Mapped[str] = Column(uuid_type(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    access_token_hash: Mapped[str] = Column(Text, nullable=False)
    refresh_token_hash: Mapped[Optional[str]] = Column(Text, nullable=True)
    refresh_token_family: Mapped[Optional[str]] = Column(uuid_type(), nullable=True)
    token_jti: Mapped[Optional[str]] = Column(Text, nullable=True)
    expires_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    # The SQL normalises IPs into ip_addresses; sessions hold only the FK
    ip_address_id: Mapped[Optional[str]] = Column(
        uuid_type(), ForeignKey("ip_addresses.id", ondelete="SET NULL"), nullable=True
    )
    user_agent: Mapped[Optional[str]] = Column(Text, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = Column(
        DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc
    )

    user: Mapped["User"] = relationship("User", back_populates="sessions")
    ip_address: Mapped[Optional["IpAddress"]] = relationship("IpAddress", back_populates="sessions")


# =============================================================================
# Core database - MFA
# =============================================================================

class MfaTransaction(Base):
    """MFA challenge transactions (pending login before session creation)."""
    __tablename__ = "mfa_transactions"
    __table_args__ = (
        CheckConstraint("mfa_type IN ('one_time', 'persistent')", name="chk_mfa_transactions_type"),
        CheckConstraint(
            "status IN ('pending', 'completed', 'expired', 'failed')",
            name="chk_mfa_transactions_status",
        ),
        Index("idx_mfa_transactions_user", "user_id"),
        Index("idx_mfa_transactions_status", "status"),
        Index("idx_mfa_transactions_expires", "expires_at"),
        Index("idx_mfa_transactions_user_status_expires", "user_id", "status", "expires_at"),
    )

    id: Mapped[str] = Column(uuid_type(), primary_key=True, default=uuid4)
    user_id: Mapped[str] = Column(uuid_type(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    mfa_type: Mapped[str] = Column(Text, nullable=False, default="one_time")
    status: Mapped[str] = Column(Text, nullable=False, default="pending")
    bound_ip: Mapped[Optional[str]] = Column(inet_type(), nullable=True)
    # The SQL adds this FK via ALTER TABLE (fk_mfa_transaction_notification);
    # declared here so the ORM can resolve the circular relationship.
    notification_id: Mapped[Optional[str]] = Column(
        uuid_type(), ForeignKey("mfa_notifications.id", ondelete="SET NULL"), nullable=True
    )
    fail_count: Mapped[int] = Column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = Column(
        DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc
    )

    user: Mapped["User"] = relationship("User", back_populates="mfa_transactions")
    notification: Mapped[Optional["MfaNotification"]] = relationship(
        "MfaNotification", back_populates="mfa_transaction", foreign_keys="MfaTransaction.notification_id"
    )


class MfaNotification(Base):
    """Email/SMS OTP notification lifecycle tracking."""
    __tablename__ = "mfa_notifications"
    __table_args__ = (
        CheckConstraint("channel IN ('email', 'sms', 'totp')", name="chk_mfa_notifications_channel"),
        Index("idx_mfa_notifications_transaction", "mfa_transaction_id"),
        Index("idx_mfa_notifications_recipient", "recipient"),
        Index("idx_mfa_notifications_expires", "expires_at"),
    )

    id: Mapped[str] = Column(uuid_type(), primary_key=True, default=uuid4)
    mfa_transaction_id: Mapped[str] = Column(
        uuid_type(), ForeignKey("mfa_transactions.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = Column(Text, nullable=False, default="email")
    recipient: Mapped[str] = Column(Text, nullable=False)
    mfa_code_hash: Mapped[str] = Column(Text, nullable=False, doc="Argon2id hash of the OTP")
    sent_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    delivered_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[Optional[str]] = Column(Text, nullable=True)
    expires_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    # back_populates is defined on MfaTransaction.notification
    mfa_transaction: Mapped["MfaTransaction"] = relationship("MfaTransaction", foreign_keys=[mfa_transaction_id])


# =============================================================================
# Core database - audit, devices, config
# =============================================================================

class AuditLog(Base):
    """Immutable audit trail of all admin and system actions."""
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint("actor_type IN ('user', 'system')", name="chk_audit_logs_actor_type"),
        Index("idx_audit_logs_actor", "actor_id"),
        Index("idx_audit_logs_actor_type", "actor_type"),
        Index("idx_audit_logs_action", "action"),
        Index("idx_audit_logs_resource", "resource"),
        Index("idx_audit_logs_created", "created_at"),
        Index("idx_audit_logs_request", "request_id"),
    )

    id: Mapped[str] = Column(uuid_type(), primary_key=True, default=uuid4)
    request_id: Mapped[Optional[str]] = Column(uuid_type(), nullable=True)
    actor_id: Mapped[Optional[str]] = Column(
        uuid_type(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_type: Mapped[str] = Column(Text, nullable=False, default="system")
    action: Mapped[str] = Column(Text, nullable=False)
    resource: Mapped[str] = Column(Text, nullable=False)
    resource_id: Mapped[Optional[str]] = Column(uuid_type(), nullable=True)
    before_state: Mapped[Optional[dict]] = Column(JSON, nullable=True)
    after_state: Mapped[Optional[dict]] = Column(JSON, nullable=True)
    change_reason: Mapped[Optional[str]] = Column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = Column(inet_type(), nullable=True)
    user_agent: Mapped[Optional[str]] = Column(Text, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    actor_user: Mapped[Optional["User"]] = relationship("User", back_populates="audit_logs")


class UserTrustedDevice(Base):
    """Trusted devices that skip MFA on login."""
    __tablename__ = "user_trusted_devices"
    __table_args__ = (
        UniqueConstraint("user_id", "device_fingerprint", name="uq_trusted_device"),
        Index("idx_user_trusted_devices_user", "user_id"),
        Index("idx_user_trusted_devices_fingerprint", "device_fingerprint"),
    )

    id: Mapped[str] = Column(uuid_type(), primary_key=True, default=uuid4)
    user_id: Mapped[str] = Column(uuid_type(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    device_fingerprint: Mapped[str] = Column(Text, nullable=False)
    device_name: Mapped[Optional[str]] = Column(Text, nullable=True)
    last_ip: Mapped[Optional[str]] = Column(inet_type(), nullable=True)
    last_user_agent: Mapped[Optional[str]] = Column(Text, nullable=True)
    last_used_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    expires_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    user: Mapped["User"] = relationship("User", back_populates="trusted_devices")


class SystemSetting(Base):
    """Dynamic system configuration values."""
    __tablename__ = "system_settings"
    __table_args__ = (
        CheckConstraint(
            "value_type IN ('string', 'integer', 'boolean', 'json')",
            name="chk_system_settings_value_type",
        ),
        CheckConstraint(
            "category IN ('auth', 'mfa', 'rate_limit', 'detection', 'notification', 'general')",
            name="chk_system_settings_category",
        ),
        Index("idx_system_settings_category", "category"),
        Index("idx_system_settings_updated_by", "updated_by"),
    )

    key: Mapped[str] = Column(Text, primary_key=True)
    value: Mapped[str] = Column(Text, nullable=False)
    value_type: Mapped[str] = Column(Text, nullable=False, default="string")
    description: Mapped[Optional[str]] = Column(Text, nullable=True)
    category: Mapped[str] = Column(Text, nullable=False, default="general")
    updated_by: Mapped[Optional[str]] = Column(
        uuid_type(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = Column(
        DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc
    )


# =============================================================================
# Core database - transactional outbox (ADR-002, drives WF-2)
# =============================================================================

class OutboxEvent(Base):
    """Transactional outbox: Core App writes here, a poller publishes to
    Detection Engine via ``POST /api/v1/internal/login-events``."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'published', 'failed')",
            name="chk_outbox_events_status",
        ),
        Index("idx_outbox_events_pending", "created_at"),
        Index("idx_outbox_events_aggregate", "aggregate_type", "aggregate_id"),
        Index("idx_outbox_events_event_type", "event_type"),
        Index("idx_outbox_events_status", "status"),
    )

    id: Mapped[str] = Column(uuid_type(), primary_key=True, default=uuid4)
    aggregate_type: Mapped[str] = Column(Text, nullable=False)
    aggregate_id: Mapped[str] = Column(uuid_type(), nullable=False)
    event_type: Mapped[str] = Column(Text, nullable=False)
    version: Mapped[int] = Column(Integer, nullable=False, default=1)
    payload: Mapped[dict] = Column(JSON, nullable=False)
    headers: Mapped[Optional[dict]] = Column(JSON, nullable=True)
    status: Mapped[str] = Column(Text, nullable=False, default="pending")
    retry_count: Mapped[int] = Column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = Column(Integer, nullable=False, default=3)
    last_error: Mapped[Optional[str]] = Column(Text, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    published_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)


class UserNotification(Base):
    """In-app notifications for users."""
    __tablename__ = "user_notifications"
    __table_args__ = (
        CheckConstraint(
            "type IN ('mfa_success', 'mfa_failed', 'new_login', 'password_changed',"
            " 'account_locked', 'account_unlocked', 'alert_resolved', 'system')",
            name="chk_user_notifications_type",
        ),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name="chk_user_notifications_priority",
        ),
        Index("idx_user_notifications_user", "user_id"),
        Index("idx_user_notifications_created", "created_at"),
        Index("idx_user_notifications_type", "type"),
        Index("idx_user_notifications_priority", "priority"),
    )

    id: Mapped[str] = Column(uuid_type(), primary_key=True, default=uuid4)
    user_id: Mapped[str] = Column(uuid_type(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = Column(Text, nullable=False)
    title: Mapped[str] = Column(Text, nullable=False)
    body: Mapped[str] = Column(Text, nullable=False)
    link: Mapped[Optional[str]] = Column(Text, nullable=True)
    priority: Mapped[str] = Column(Text, nullable=False, default="normal")
    read: Mapped[bool] = Column(Boolean, nullable=False, default=False)
    read_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    user: Mapped["User"] = relationship("User", back_populates="notifications")


class RateLimit(Base):
    """Rate limiting counters per IP and action."""
    __tablename__ = "rate_limits"
    __table_args__ = (
        CheckConstraint("count >= 0", name="chk_rate_limits_count"),
        CheckConstraint("max_count > 0", name="chk_rate_limits_max"),
        Index("idx_rate_limits_window", "window_start"),
    )

    ip_address: Mapped[str] = Column(inet_type(), primary_key=True)
    action: Mapped[str] = Column(Text, primary_key=True)
    count: Mapped[int] = Column(Integer, nullable=False, default=1)
    max_count: Mapped[int] = Column(Integer, nullable=False, default=5)
    window_start: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)


# =============================================================================
# Detection database
# Canonical decisions: docs/DECISIONS-DETECTION-v3.3.md
# =============================================================================

class Policy(Base):
    """Detection policy: ``rules`` + ``config`` stored as JSONB."""
    __tablename__ = "policies"
    __table_args__ = (
        Index("idx_policies_version", "version"),
        Index("idx_policies_active", "is_active"),
        Index("idx_policies_created_by", "created_by"),
    )

    id: Mapped[str] = Column(uuid_type(), primary_key=True, default=uuid4)
    version: Mapped[str] = Column(Text, nullable=False, unique=True)
    name: Mapped[Optional[str]] = Column(Text, nullable=True)
    description: Mapped[Optional[str]] = Column(Text, nullable=True)
    # rules: JSONB array of 7-field rules
    #   {name, field, operator, value, weight, score, enabled, description?}
    rules: Mapped[List[Any]] = Column(JSON, nullable=False, default=list)
    # config: {weights: {rule, ml}, thresholds: {low, medium, high}}
    config: Mapped[dict] = Column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = Column(Boolean, nullable=False, default=False)
    # cross-DB: references users.id in core-db
    created_by: Mapped[Optional[str]] = Column(uuid_type(), nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    activated_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    deactivated_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)

    login_attempts: Mapped[List["LoginAttempt"]] = relationship("LoginAttempt", back_populates="policy")
    risk_assessments: Mapped[List["RiskAssessment"]] = relationship("RiskAssessment", back_populates="policy")
    alerts: Mapped[List["Alert"]] = relationship("Alert", back_populates="policy")


class LoginAttempt(Base):
    """All login events received from core-app over HTTP."""
    __tablename__ = "login_attempts"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('success', 'failure', 'mfa_required', 'mfa_success',"
            " 'mfa_failed', 'blocked', 'locked', 'rate_limited')",
            name="chk_login_attempts_outcome",
        ),
        CheckConstraint(
            "status IN ('pending', 'processed', 'failed')",
            name="chk_login_attempts_status",
        ),
        CheckConstraint(
            "risk_level IN ('low', 'medium', 'high', 'critical')",
            name="chk_login_attempts_risk_level",
        ),
        CheckConstraint(
            "detection_decision IN ('allow', 'challenge', 'block')",
            name="chk_login_attempts_decision",
        ),
        Index("idx_login_attempts_event_id", "event_id"),
        Index("idx_login_attempts_user_id", "user_id"),
        Index("idx_login_attempts_timestamp", "timestamp"),
        Index("idx_login_attempts_outcome", "outcome"),
        Index("idx_login_attempts_risk_level", "risk_level"),
        Index("idx_login_attempts_request_id", "request_id"),
        Index("idx_login_attempts_username", "username_attempted"),
        Index("idx_login_attempts_ip", "ip_address"),
        Index("idx_login_attempts_policy", "policy_id"),
        Index("idx_login_attempts_status", "status"),
    )

    id: Mapped[str] = Column(uuid_type(), primary_key=True, default=uuid4)
    # Idempotency key from core-app: same event delivered twice -> one row only
    event_id: Mapped[str] = Column(uuid_type(), nullable=False, unique=True)
    # cross-DB: references users.id in core-db; NULL when the username is unknown
    user_id: Mapped[Optional[str]] = Column(uuid_type(), nullable=True)
    username_attempted: Mapped[Optional[str]] = Column(Text, nullable=True)
    outcome: Mapped[str] = Column(Text, nullable=False)
    mfa_used: Mapped[bool] = Column(Boolean, nullable=False, default=False)
    ip_address: Mapped[Optional[str]] = Column(inet_type(), nullable=True)
    user_agent: Mapped[Optional[str]] = Column(Text, nullable=True)
    timestamp: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    # Work queue for the background detection worker
    status: Mapped[str] = Column(Text, nullable=False, default="pending")
    policy_id: Mapped[Optional[str]] = Column(uuid_type(), ForeignKey("policies.id", ondelete="SET NULL"), nullable=True)
    request_id: Mapped[str] = Column(uuid_type(), nullable=False, default=uuid4)
    # The SQL adds this FK via ALTER TABLE (fk_login_attempt_primary_alert);
    # declared here so the ORM can resolve the circular relationship.
    primary_alert_id: Mapped[Optional[str]] = Column(
        uuid_type(), ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True
    )
    risk_level: Mapped[Optional[str]] = Column(Text, nullable=True)
    detection_decision: Mapped[Optional[str]] = Column(Text, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = Column(
        DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc
    )

    # Relationships
    policy: Mapped[Optional["Policy"]] = relationship("Policy", back_populates="login_attempts")
    risk_assessment: Mapped[Optional["RiskAssessment"]] = relationship(
        "RiskAssessment", back_populates="login_attempt", uselist=False
    )
    detection_logs: Mapped[List["DetectionLog"]] = relationship(
        "DetectionLog", back_populates="login_attempt", cascade="all, delete-orphan"
    )
    # login_attempts has two FKs to alerts (login_attempt_id and
    # primary_alert_id), so the join condition must be stated explicitly.
    alerts: Mapped[List["Alert"]] = relationship(
        "Alert",
        back_populates="login_attempt",
        cascade="all, delete-orphan",
        foreign_keys="Alert.login_attempt_id",
    )
    primary_alert: Mapped[Optional["Alert"]] = relationship(
        "Alert",
        foreign_keys=[primary_alert_id],
        overlaps="alerts",
        viewonly=True,
    )


class RiskAssessment(Base):
    """Per-attempt risk scoring. 1:1 with ``login_attempts``."""
    __tablename__ = "risk_assessments"
    __table_args__ = (
        UniqueConstraint("login_attempt_id", name="uq_risk_assessment_login"),
        CheckConstraint("ml_status IN ('success', 'unavailable', 'error')", name="chk_risk_assessments_ml_status"),
        CheckConstraint("risk_level IN ('low', 'medium', 'high', 'critical')", name="chk_risk_assessments_risk_level"),
        CheckConstraint("decision IN ('allow', 'challenge', 'block')", name="chk_risk_assessments_decision"),
        Index("idx_risk_assessments_login", "login_attempt_id"),
        Index("idx_risk_assessments_risk_level", "risk_level"),
        Index("idx_risk_assessments_policy", "policy_id"),
        Index("idx_risk_assessments_ml_status", "ml_status"),
    )

    id: Mapped[str] = Column(uuid_type(), primary_key=True, default=uuid4)
    login_attempt_id: Mapped[str] = Column(
        uuid_type(), ForeignKey("login_attempts.id", ondelete="CASCADE"), nullable=False
    )
    policy_id: Mapped[Optional[str]] = Column(uuid_type(), ForeignKey("policies.id", ondelete="SET NULL"), nullable=True)
    rule_score: Mapped[Optional[float]] = Column(Numeric(5, 4), nullable=True)
    # ml_score: 0..1, NULL when ml_status is 'unavailable' or 'error'
    ml_score: Mapped[Optional[float]] = Column(Numeric(5, 4), nullable=True)
    combined_score: Mapped[Optional[float]] = Column(Numeric(5, 4), nullable=True)
    ml_status: Mapped[Optional[str]] = Column(Text, nullable=True)
    ml_model_version: Mapped[Optional[str]] = Column(Text, nullable=True)
    rule_hits: Mapped[Optional[Any]] = Column(JSON, nullable=True)
    ml_reason_codes: Mapped[Optional[Any]] = Column(JSON, nullable=True)
    ml_features_used: Mapped[Optional[Any]] = Column(JSON, nullable=True)
    risk_level: Mapped[Optional[str]] = Column(Text, nullable=True)
    decision: Mapped[Optional[str]] = Column(Text, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    login_attempt: Mapped["LoginAttempt"] = relationship("LoginAttempt", back_populates="risk_assessment")
    policy: Mapped[Optional["Policy"]] = relationship("Policy", back_populates="risk_assessments")


class DetectionLog(Base):
    """Detailed audit trail for each detection stage (4 stages)."""
    __tablename__ = "detection_logs"
    __table_args__ = (
        CheckConstraint(
            "stage IN ('rule_evaluation', 'ml_call', 'scoring', 'action_sent')",
            name="chk_detection_logs_stage",
        ),
        CheckConstraint("decision IN ('allow', 'challenge', 'block')", name="chk_detection_logs_decision"),
        Index("idx_detection_logs_login", "login_attempt_id"),
        Index("idx_detection_logs_stage", "stage"),
        Index("idx_detection_logs_request", "request_id"),
        Index("idx_detection_logs_decision", "decision"),
    )

    id: Mapped[str] = Column(uuid_type(), primary_key=True, default=uuid4)
    login_attempt_id: Mapped[Optional[str]] = Column(
        uuid_type(), ForeignKey("login_attempts.id", ondelete="SET NULL"), nullable=True
    )
    request_id: Mapped[Optional[str]] = Column(uuid_type(), nullable=True)
    stage: Mapped[str] = Column(Text, nullable=False)
    stage_detail: Mapped[Optional[str]] = Column(Text, nullable=True)
    rule_id: Mapped[Optional[str]] = Column(uuid_type(), nullable=True)
    rule_name: Mapped[Optional[str]] = Column(Text, nullable=True)
    triggered: Mapped[Optional[bool]] = Column(Boolean, nullable=True)
    # Contribution AFTER normalization; sums exactly to rule_score
    score_contribution: Mapped[Optional[float]] = Column(Numeric(5, 4), nullable=True)
    decision: Mapped[Optional[str]] = Column(Text, nullable=True)
    reason: Mapped[Optional[str]] = Column(Text, nullable=True)
    details: Mapped[Optional[Any]] = Column(JSON, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    login_attempt: Mapped[Optional["LoginAttempt"]] = relationship(
        "LoginAttempt", back_populates="detection_logs"
    )


class SocAnalyst(Base):
    """SOC analyst profile; ``user_id`` references users.id in core-db."""
    __tablename__ = "soc_analysts"
    __table_args__ = (
        Index("idx_soc_analysts_user", "user_id"),
        Index("idx_soc_analysts_active", "is_active"),
    )

    id: Mapped[str] = Column(uuid_type(), primary_key=True, default=uuid4)
    # cross-DB: references users.id in core-db
    user_id: Mapped[str] = Column(uuid_type(), nullable=False, unique=True)
    display_name: Mapped[Optional[str]] = Column(Text, nullable=True)
    is_active: Mapped[bool] = Column(Boolean, nullable=False, default=True)
    max_alerts: Mapped[int] = Column(Integer, nullable=False, default=50)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = Column(
        DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc
    )


class Alert(Base):
    """SOC alerts created from high/critical risk login attempts."""
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved', 'false_positive')",
            name="chk_alerts_status",
        ),
        CheckConstraint("risk_level IN ('low', 'medium', 'high', 'critical')", name="chk_alerts_risk_level"),
        Index("idx_alerts_login_attempt", "login_attempt_id"),
        Index("idx_alerts_status", "status"),
        Index("idx_alerts_risk_level", "risk_level"),
        Index("idx_alerts_assigned_to", "assigned_to_id"),
        Index("idx_alerts_resolved_by", "resolved_by_id"),
        Index("idx_alerts_created", "created_at"),
        Index("idx_alerts_policy", "policy_id"),
    )

    id: Mapped[str] = Column(uuid_type(), primary_key=True, default=uuid4)
    login_attempt_id: Mapped[str] = Column(
        uuid_type(), ForeignKey("login_attempts.id", ondelete="CASCADE"), nullable=False
    )
    policy_id: Mapped[Optional[str]] = Column(uuid_type(), ForeignKey("policies.id", ondelete="SET NULL"), nullable=True)
    request_id: Mapped[Optional[str]] = Column(uuid_type(), nullable=True)
    status: Mapped[str] = Column(Text, nullable=False, default="open")
    risk_level: Mapped[Optional[str]] = Column(Text, nullable=True)
    detection_reason: Mapped[Optional[str]] = Column(Text, nullable=True)
    detection_scores: Mapped[Optional[dict]] = Column(JSON, nullable=True)
    assigned_to_id: Mapped[Optional[str]] = Column(
        uuid_type(), ForeignKey("soc_analysts.id", ondelete="SET NULL"), nullable=True
    )
    resolved_by_id: Mapped[Optional[str]] = Column(
        uuid_type(), ForeignKey("soc_analysts.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[Optional[str]] = Column(Text, nullable=True)
    notes: Mapped[Optional[str]] = Column(Text, nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = Column(
        DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc
    )

    login_attempt: Mapped["LoginAttempt"] = relationship(
        "LoginAttempt",
        back_populates="alerts",
        foreign_keys=[login_attempt_id],
    )
    policy: Mapped[Optional["Policy"]] = relationship("Policy", back_populates="alerts")
    timeline: Mapped[List["AlertTimeline"]] = relationship(
        "AlertTimeline",
        back_populates="alert",
        cascade="all, delete-orphan",
        order_by="AlertTimeline.created_at",
    )


class AlertTimeline(Base):
    """Immutable audit trail for SOC analyst actions on alerts."""
    __tablename__ = "alert_timeline"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('created', 'acknowledged', 'assigned', 'unassigned',"
            " 'escalated', 'note_added', 'status_changed', 'resolved', 'false_positive')",
            name="chk_alert_timeline_event_type",
        ),
        CheckConstraint("actor_type IN ('user', 'system')", name="chk_alert_timeline_actor_type"),
        Index("idx_alert_timeline_alert", "alert_id"),
        Index("idx_alert_timeline_created", "created_at"),
        Index("idx_alert_timeline_actor", "actor_id"),
        Index("idx_alert_timeline_event_type", "event_type"),
    )

    id: Mapped[str] = Column(uuid_type(), primary_key=True, default=uuid4)
    alert_id: Mapped[str] = Column(uuid_type(), ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = Column(Text, nullable=False)
    # cross-DB: references users.id in core-db
    actor_id: Mapped[Optional[str]] = Column(uuid_type(), nullable=True)
    actor_type: Mapped[str] = Column(Text, nullable=False, default="user")
    old_value: Mapped[Optional[str]] = Column(Text, nullable=True)
    new_value: Mapped[Optional[str]] = Column(Text, nullable=True)
    comment: Mapped[Optional[str]] = Column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = Column(inet_type(), nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    alert: Mapped["Alert"] = relationship("Alert", back_populates="timeline")


# =============================================================================
# ML service database
# =============================================================================

class ModelVersion(Base):
    """Model registry for versioning ML models."""
    __tablename__ = "model_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('staged', 'active', 'archived', 'failed')",
            name="chk_model_versions_status",
        ),
        Index("idx_model_versions_version", "version"),
        Index("idx_model_versions_status", "status"),
        Index("idx_model_versions_production", "is_production"),
        Index("idx_model_versions_algorithm", "algorithm"),
    )

    id: Mapped[str] = Column(uuid_type(), primary_key=True, default=uuid4)
    name: Mapped[str] = Column(Text, nullable=False)
    version: Mapped[str] = Column(Text, nullable=False, unique=True)
    algorithm: Mapped[str] = Column(Text, nullable=False, default="IsolationForest")
    description: Mapped[Optional[str]] = Column(Text, nullable=True)
    model_path: Mapped[str] = Column(Text, nullable=False, doc="Path to the model file on disk")
    config: Mapped[dict] = Column(JSON, nullable=False, default=dict)
    status: Mapped[str] = Column(Text, nullable=False, default="staged")
    is_production: Mapped[bool] = Column(Boolean, nullable=False, default=False)
    # cross-DB: references users.id in core-db
    trained_by: Mapped[Optional[str]] = Column(uuid_type(), nullable=True)
    training_date: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    deployed_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = Column(
        DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc
    )

    inference_logs: Mapped[List["InferenceLog"]] = relationship("InferenceLog", back_populates="model_version")


class InferenceLog(Base):
    """Inference logging for debugging and monitoring."""
    __tablename__ = "inference_logs"
    __table_args__ = (
        CheckConstraint(
            "model_status IN ('ready', 'degraded', 'error')",
            name="chk_inference_logs_model_status",
        ),
        Index("idx_inference_logs_request", "request_id"),
        Index("idx_inference_logs_model", "model_version_id"),
        Index("idx_inference_logs_anomaly", "is_anomaly"),
        Index("idx_inference_logs_created", "created_at"),
        Index("idx_inference_logs_status", "model_status"),
    )

    id: Mapped[str] = Column(uuid_type(), primary_key=True, default=uuid4)
    # Idempotency key: one row per ML scoring request
    request_id: Mapped[str] = Column(uuid_type(), nullable=False, unique=True)
    model_version_id: Mapped[Optional[str]] = Column(
        uuid_type(), ForeignKey("model_versions.id"), nullable=True
    )
    model_version_used: Mapped[str] = Column(Text, nullable=False)
    features: Mapped[dict] = Column(JSON, nullable=False)
    raw_score: Mapped[Optional[float]] = Column(Numeric(10, 6), nullable=True)
    normalized_score: Mapped[float] = Column(Numeric(5, 4), nullable=False)
    is_anomaly: Mapped[bool] = Column(Boolean, nullable=False)
    reason_codes: Mapped[Optional[Any]] = Column(JSON, nullable=True, default=list)
    model_status: Mapped[str] = Column(Text, nullable=False, default="ready")
    processing_time_ms: Mapped[Optional[int]] = Column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = Column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = Column(inet_type(), nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)

    model_version: Mapped[Optional["ModelVersion"]] = relationship("ModelVersion", back_populates="inference_logs")


class FeatureStatistic(Base):
    """Feature distribution statistics for data-drift monitoring."""
    __tablename__ = "feature_statistics"
    __table_args__ = (
        Index("idx_feature_stats_feature", "feature_name"),
        Index("idx_feature_stats_timestamp", "timestamp"),
    )

    id: Mapped[str] = Column(uuid_type(), primary_key=True, default=uuid4)
    feature_name: Mapped[str] = Column(Text, nullable=False)
    timestamp: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)
    count: Mapped[int] = Column(Integer, nullable=False, default=0)
    mean: Mapped[Optional[float]] = Column(Numeric(10, 6), nullable=True)
    std: Mapped[Optional[float]] = Column(Numeric(10, 6), nullable=True)
    min: Mapped[Optional[float]] = Column(Numeric(10, 6), nullable=True)
    max: Mapped[Optional[float]] = Column(Numeric(10, 6), nullable=True)
    p25: Mapped[Optional[float]] = Column(Numeric(10, 6), nullable=True)
    p50: Mapped[Optional[float]] = Column(Numeric(10, 6), nullable=True)
    p75: Mapped[Optional[float]] = Column(Numeric(10, 6), nullable=True)
    p95: Mapped[Optional[float]] = Column(Numeric(10, 6), nullable=True)
    anomaly_rate: Mapped[Optional[float]] = Column(Numeric(5, 4), nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=now_utc)


# =============================================================================
# Dialect compatibility
# =============================================================================

@compiles(CheckConstraint, "sqlite")
def _compile_check_constraint_sqlite(element, compiler, **kw):  # noqa: ARG001
    """Rewrite Postgres-only CHECK expressions so the DDL compiles on SQLite.

    ``chk_username_chars`` uses ``~`` (regex match), which SQLite lacks; the
    GLOB form below accepts exactly the same usernames.
    """
    text = str(element.sqltext)
    if USERNAME_CHARS_PG in text:
        return compiler.process(
            CheckConstraint(USERNAME_CHARS_SQLITE, name=element.name)
        )
    return compiler.visit_check_constraint(element)

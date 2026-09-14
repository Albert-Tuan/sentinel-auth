"""Authentication state, MFA and durable outbox models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin, utc_now
from app.models.enums import LoginOutcome, MfaChallengeStatus, OutboxStatus, PreAuthStatus


class Session(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sessions"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    access_jti: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    source_ip: Mapped[str] = mapped_column(String(45), nullable=False)
    device_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    user: Mapped["User"] = relationship(back_populates="sessions")


class LoginAttempt(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "login_attempts"

    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    correlation_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    outcome: Mapped[LoginOutcome] = mapped_column(String(16), nullable=False)
    source_ip: Mapped[str] = mapped_column(String(45), nullable=False)
    device_fingerprint_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    region_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    mfa_completed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class PreAuthTransaction(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "pre_auth_transactions"
    __table_args__ = (
        Index(
            "uq_pre_auth_transactions_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    login_attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey("login_attempts.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    token_hash: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    status: Mapped[PreAuthStatus] = mapped_column(String(16), nullable=False, default=PreAuthStatus.ACTIVE)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bound_ip_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    bound_device_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)

    challenge: Mapped["MfaChallenge"] = relationship(back_populates="pre_auth_transaction", uselist=False)


class MfaChallenge(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "mfa_challenges"
    __table_args__ = (
        Index(
            "uq_mfa_challenges_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    pre_auth_transaction_id: Mapped[UUID] = mapped_column(
        ForeignKey("pre_auth_transactions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    code_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[MfaChallengeStatus] = mapped_column(String(16), nullable=False, default=MfaChallengeStatus.ACTIVE)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)

    pre_auth_transaction: Mapped[PreAuthTransaction] = relationship(back_populates="challenge")


class OutboxEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "outbox_events"

    login_attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey("login_attempts.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    producer: Mapped[str] = mapped_column(String(64), nullable=False, default="core-app")
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    payload_checksum: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[OutboxStatus] = mapped_column(String(16), nullable=False, default=OutboxStatus.PENDING, index=True)
    publish_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


from app.models.identity import User  # noqa: E402  # isort: skip

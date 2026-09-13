"""Security-action audit and IP enforcement models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin, utc_now
from app.models.enums import EnforcementAction, EnforcementResult


class EnforcementAudit(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "enforcement_audits"

    request_id: Mapped[UUID | None] = mapped_column(nullable=True, unique=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    correlation_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_ref: Mapped[UUID | None] = mapped_column(nullable=True)
    approval_ref: Mapped[UUID | None] = mapped_column(nullable=True)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    request_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_status: Mapped[EnforcementResult] = mapped_column(String(32), nullable=False)
    before_state: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    after_state: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class IpRateLimit(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ip_rate_limits"

    source_ip: Mapped[str] = mapped_column(String(45), nullable=False, unique=True)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    enforced_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    enforcement_audit_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("enforcement_audits.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

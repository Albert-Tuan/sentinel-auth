"""Create the core-app identity, authentication and enforcement foundation.

Revision ID: 20260910_0001
Revises:
Create Date: 2026-09-10
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260910_0001"
down_revision = None
branch_labels = None
depends_on = None


ROLE_SEEDS = (
    (UUID("d8de0173-d4b8-4f8b-b13e-a9bd7b35e001"), "USER"),
    (UUID("d8de0173-d4b8-4f8b-b13e-a9bd7b35e002"), "SECURITY_ADMIN"),
    (UUID("d8de0173-d4b8-4f8b-b13e-a9bd7b35e003"), "SOC_ANALYST"),
    (UUID("d8de0173-d4b8-4f8b-b13e-a9bd7b35e004"), "SECURITY_MANAGER"),
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=254), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("admin_mfa_required", sa.Boolean(), nullable=False),
        sa.Column("detection_mfa_once", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'LOCKED')", name="ck_users_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "code IN ('USER', 'SECURITY_ADMIN', 'SOC_ANALYST', 'SECURITY_MANAGER')",
            name="ck_roles_code",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_roles_code"),
    )
    op.bulk_insert(
        sa.table(
            "roles",
            sa.column("id", sa.Uuid()),
            sa.column("code", sa.String()),
            sa.column("created_at", sa.DateTime(timezone=True)),
        ),
        [{"id": role_id, "code": code, "created_at": datetime.now(UTC)} for role_id, code in ROLE_SEEDS],
    )

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by", sa.Uuid(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assigned_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_role"),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("access_jti", sa.String(length=128), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=512), nullable=False),
        sa.Column("source_ip", sa.String(length=45), nullable=False),
        sa.Column("device_id", sa.String(length=512), nullable=True),
        sa.Column("user_agent", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("access_jti", name="uq_sessions_access_jti"),
        sa.UniqueConstraint("refresh_token_hash", name="uq_sessions_refresh_token_hash"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("source_ip", sa.String(length=45), nullable=False),
        sa.Column("device_fingerprint_hash", sa.String(length=128), nullable=True),
        sa.Column("user_agent", sa.String(length=1024), nullable=True),
        sa.Column("region_code", sa.String(length=32), nullable=True),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("mfa_completed", sa.Boolean(), nullable=True),
        sa.CheckConstraint("outcome IN ('ALLOW', 'MFA_REQUIRED', 'DENY')", name="ck_login_attempts_outcome"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_login_attempts_user_id", "login_attempts", ["user_id"])
    op.create_index("ix_login_attempts_correlation_id", "login_attempts", ["correlation_id"])

    op.create_table(
        "pre_auth_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("login_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bound_ip_hash", sa.String(length=128), nullable=False),
        sa.Column("bound_device_hash", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_reason", sa.String(length=128), nullable=True),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'VERIFIED', 'EXPIRED', 'INVALIDATED')",
            name="ck_pre_auth_transactions_status",
        ),
        sa.ForeignKeyConstraint(["login_attempt_id"], ["login_attempts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("login_attempt_id", name="uq_pre_auth_transactions_login_attempt"),
        sa.UniqueConstraint("token_hash", name="uq_pre_auth_transactions_token_hash"),
    )
    op.create_index("ix_pre_auth_transactions_user_id", "pre_auth_transactions", ["user_id"])
    op.create_index(
        "uq_pre_auth_transactions_active_user",
        "pre_auth_transactions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )

    op.create_table(
        "mfa_challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("pre_auth_transaction_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fail_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_reason", sa.String(length=128), nullable=True),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'VERIFIED', 'EXPIRED', 'LOCKED', 'INVALIDATED')",
            name="ck_mfa_challenges_status",
        ),
        sa.ForeignKeyConstraint(["pre_auth_transaction_id"], ["pre_auth_transactions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pre_auth_transaction_id", name="uq_mfa_challenges_pre_auth_transaction"),
    )
    op.create_index("ix_mfa_challenges_user_id", "mfa_challenges", ["user_id"])
    op.create_index(
        "uq_mfa_challenges_active_user",
        "mfa_challenges",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("login_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("producer", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_checksum", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("publish_attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=1024), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('PENDING', 'PUBLISHED', 'DEAD_LETTER')", name="ck_outbox_events_status"),
        sa.ForeignKeyConstraint(["login_attempt_id"], ["login_attempts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("login_attempt_id", name="uq_outbox_events_login_attempt"),
        sa.UniqueConstraint("payload_checksum", name="uq_outbox_events_payload_checksum"),
    )
    op.create_index("ix_outbox_events_correlation_id", "outbox_events", ["correlation_id"])
    op.create_index("ix_outbox_events_status", "outbox_events", ["status"])

    op.create_table(
        "enforcement_audits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("evidence_ref", sa.Uuid(), nullable=True),
        sa.Column("approval_ref", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("request_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_status", sa.String(length=32), nullable=False),
        sa.Column("before_state", sa.JSON(), nullable=True),
        sa.Column("after_state", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "result_status IN ('APPLIED', 'PENDING_APPROVAL', 'REJECTED', 'DUPLICATE')",
            name="ck_enforcement_audits_result_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_enforcement_audits_request_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_enforcement_audits_idempotency_key"),
    )
    op.create_index("ix_enforcement_audits_correlation_id", "enforcement_audits", ["correlation_id"])

    op.create_table(
        "ip_rate_limits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_ip", sa.String(length=45), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("enforced_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enforcement_audit_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["enforcement_audit_id"], ["enforcement_audits.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_ip", name="uq_ip_rate_limits_source_ip"),
        sa.UniqueConstraint("enforcement_audit_id", name="uq_ip_rate_limits_enforcement_audit"),
    )
    op.create_index("ix_ip_rate_limits_enforced_until", "ip_rate_limits", ["enforced_until"])


def downgrade() -> None:
    op.drop_index("ix_ip_rate_limits_enforced_until", table_name="ip_rate_limits")
    op.drop_table("ip_rate_limits")
    op.drop_index("ix_enforcement_audits_correlation_id", table_name="enforcement_audits")
    op.drop_table("enforcement_audits")
    op.drop_index("ix_outbox_events_status", table_name="outbox_events")
    op.drop_index("ix_outbox_events_correlation_id", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("uq_mfa_challenges_active_user", table_name="mfa_challenges")
    op.drop_index("ix_mfa_challenges_user_id", table_name="mfa_challenges")
    op.drop_table("mfa_challenges")
    op.drop_index("uq_pre_auth_transactions_active_user", table_name="pre_auth_transactions")
    op.drop_index("ix_pre_auth_transactions_user_id", table_name="pre_auth_transactions")
    op.drop_table("pre_auth_transactions")
    op.drop_index("ix_login_attempts_correlation_id", table_name="login_attempts")
    op.drop_index("ix_login_attempts_user_id", table_name="login_attempts")
    op.drop_table("login_attempts")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("user_roles")
    op.drop_table("roles")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")

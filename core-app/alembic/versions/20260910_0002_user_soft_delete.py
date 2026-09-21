"""Support soft deletion in the core-app user lifecycle.

Revision ID: 20260910_0002
Revises: 20260910_0001
Create Date: 2026-09-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260910_0002"
down_revision = "20260910_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
            batch_op.drop_constraint("ck_users_status", type_="check")
            batch_op.create_check_constraint(
                "ck_users_status", "status IN ('ACTIVE', 'LOCKED', 'DELETED')"
            )
        return

    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint("ck_users_status", "users", type_="check")
    op.create_check_constraint(
        "ck_users_status", "users", "status IN ('ACTIVE', 'LOCKED', 'DELETED')"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_constraint("ck_users_status", type_="check")
            batch_op.drop_column("deleted_at")
            batch_op.create_check_constraint("ck_users_status", "status IN ('ACTIVE', 'LOCKED')")
        return

    op.drop_constraint("ck_users_status", "users", type_="check")
    op.drop_column("users", "deleted_at")
    op.create_check_constraint("ck_users_status", "users", "status IN ('ACTIVE', 'LOCKED')")

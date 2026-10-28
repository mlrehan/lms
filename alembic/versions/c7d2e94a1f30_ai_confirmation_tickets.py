"""AI confirmation tickets, persisted.

Replaces the in-process ticket dictionary: pending confirmations now survive a
restart, are visible to every API process, and are consumed exactly once under
a row lock. See backend/models/ai_ticket.py.

New and empty, so there is nothing to backfill: tickets that were pending in
memory at deploy time are lost with the old process, exactly as they were on
any restart before this.

Revision ID: c7d2e94a1f30
Revises: f3b8c1a9d012
Create Date: 2026-10-28 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7d2e94a1f30"
down_revision: Union[str, None] = "f3b8c1a9d012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_confirmation_tickets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticket_id", sa.String(length=64), nullable=False),
        sa.Column("action_name", sa.String(length=100), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("actor_public_id", sa.String(length=36), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("parameters_hash", sa.String(length=64), nullable=False),
        sa.Column("affected_records_count", sa.Integer(), nullable=False),
        sa.Column("preview_summary", sa.Text(), nullable=False),
        sa.Column("via_registry", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED', 'CANCELLED')",
            name=op.f("ck_ai_confirmation_tickets_status"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_ai_confirmation_tickets_actor_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_confirmation_tickets")),
    )
    op.create_index(
        op.f("ix_ai_confirmation_tickets_ticket_id"), "ai_confirmation_tickets", ["ticket_id"], unique=True
    )
    op.create_index(
        op.f("ix_ai_confirmation_tickets_public_id"), "ai_confirmation_tickets", ["public_id"], unique=True
    )
    op.create_index("idx_ai_tickets_actor_status", "ai_confirmation_tickets", ["actor_user_id", "status"])
    op.create_index("idx_ai_tickets_expires_at", "ai_confirmation_tickets", ["expires_at"])


def downgrade() -> None:
    op.drop_index("idx_ai_tickets_expires_at", table_name="ai_confirmation_tickets")
    op.drop_index("idx_ai_tickets_actor_status", table_name="ai_confirmation_tickets")
    op.drop_index(op.f("ix_ai_confirmation_tickets_public_id"), table_name="ai_confirmation_tickets")
    op.drop_index(op.f("ix_ai_confirmation_tickets_ticket_id"), table_name="ai_confirmation_tickets")
    op.drop_table("ai_confirmation_tickets")

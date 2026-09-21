"""Google Calendar mirror: connection, and the mapping columns on batches and sessions.

Revision ID: c48d7a2e9b15
Revises: b27e4c90a1d3
Create Date: 2026-09-20 18:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c48d7a2e9b15"
down_revision: Union[str, Sequence[str], None] = "b27e4c90a1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "google_connections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("account_email", sa.String(255), nullable=False),
        sa.Column("refresh_token_enc", sa.Text(), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=False),
        sa.Column("status", sa.String(10), server_default=sa.text("'ACTIVE'"), nullable=False),
        sa.Column("connected_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(300), nullable=True),
    )
    op.create_index("ix_google_connections_public_id", "google_connections", ["public_id"], unique=True)
    op.create_index("ux_google_connections_one_active", "google_connections", [sa.text("(true)")], unique=True,
                    postgresql_where=sa.text("status = 'ACTIVE'"))

    op.add_column("batches", sa.Column("google_calendar_id", sa.String(255), nullable=True))
    op.add_column("batches", sa.Column("google_synced_hash", sa.String(64), nullable=True))
    op.add_column("batches", sa.Column("google_admins_hash", sa.String(64), nullable=True))
    op.add_column("batches", sa.Column("google_synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("batches", sa.Column("google_pulled_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_batches_google_calendar_id", "batches", ["google_calendar_id"])

    op.add_column("batch_sessions", sa.Column("google_event_id", sa.String(128), nullable=True))
    op.add_column("batch_sessions", sa.Column("google_synced_hash", sa.String(64), nullable=True))
    op.add_column("batch_sessions", sa.Column("google_synced_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for col in ("google_synced_at", "google_synced_hash", "google_event_id"):
        op.drop_column("batch_sessions", col)
    op.drop_constraint("uq_batches_google_calendar_id", "batches", type_="unique")
    for col in ("google_pulled_at", "google_synced_at", "google_admins_hash", "google_synced_hash", "google_calendar_id"):
        op.drop_column("batches", col)
    op.drop_index("ux_google_connections_one_active", table_name="google_connections")
    op.drop_index("ix_google_connections_public_id", table_name="google_connections")
    op.drop_table("google_connections")

"""Cancelled sessions, session origin, and the Google change-request queue.

Revision ID: d5a1c93f7e20
Revises: c48d7a2e9b15
Create Date: 2026-09-21 09:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5a1c93f7e20"
down_revision: Union[str, Sequence[str], None] = "c48d7a2e9b15"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A cancelled session is kept (attendance and history hang off it), not deleted.
    op.add_column("batch_sessions", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("batch_sessions", sa.Column("cancelled_reason", sa.String(200), nullable=True))
    # Where a session came from. NULL/'LAIT' sessions are derived data the LAIT sync may re-derive
    # and remove; anything else (created in the LMS or in Google) is somebody's decision and is
    # never deleted by a sync.
    op.add_column("batch_sessions", sa.Column("origin", sa.String(10), nullable=True))
    op.create_index("ix_batch_sessions_cancelled", "batch_sessions", ["batch_id"], postgresql_where=sa.text("cancelled_at IS NOT NULL"))

    op.create_table(
        "google_change_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),  # ENROL_ADD | ENROL_REMOVE
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("status", sa.String(10), server_default=sa.text("'PENDING'"), nullable=False),  # PENDING|APPROVED|REJECTED|SUPERSEDED
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("last_error", sa.String(300), nullable=True),
    )
    op.create_index("ix_google_change_requests_public_id", "google_change_requests", ["public_id"], unique=True)
    op.create_index("ix_google_change_requests_status", "google_change_requests", ["status"])
    # One open request per (batch, person, kind): a guest list edited on five events is one proposal.
    op.create_index("ux_google_change_requests_open", "google_change_requests", ["batch_id", "email", "kind"], unique=True, postgresql_where=sa.text("status = 'PENDING'"))


def downgrade() -> None:
    op.drop_index("ux_google_change_requests_open", table_name="google_change_requests")
    op.drop_index("ix_google_change_requests_status", table_name="google_change_requests")
    op.drop_index("ix_google_change_requests_public_id", table_name="google_change_requests")
    op.drop_table("google_change_requests")
    op.drop_index("ix_batch_sessions_cancelled", table_name="batch_sessions")
    for col in ("origin", "cancelled_reason", "cancelled_at"):
        op.drop_column("batch_sessions", col)

"""Attendance as a workflow: a sheet per session (draft -> finalized) with an append-only trail.

Revision ID: c4f9a26e8b57
Revises: b3e8d17a5c46
Create Date: 2026-09-22 12:00:00.000000

Sessions that already have attendance rows have no sheet; they read as finalized, and gain a sheet the first time
they are edited (with the edit recorded), so nothing about existing registers changes on upgrade.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4f9a26e8b57"
down_revision: Union[str, Sequence[str], None] = "b3e8d17a5c46"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("attendances", sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("attendances", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "attendance_sheets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("batch_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="DRAFT"),
        sa.Column("assigned_tutor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("draft", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_on_behalf", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.UniqueConstraint("session_id", name="uq_attendance_sheets_session_id"),
        sa.CheckConstraint("status IN ('DRAFT', 'FINALIZED')", name="ck_attendance_sheets_status"),
    )
    op.create_index("ix_attendance_sheets_public_id", "attendance_sheets", ["public_id"], unique=True)

    op.create_table(
        "attendance_sheet_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sheet_id", sa.Integer(), sa.ForeignKey("attendance_sheets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(12), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("assigned_tutor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("on_behalf", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("changes", sa.JSON(), nullable=True),
        sa.CheckConstraint("action IN ('STARTED', 'FINALIZED', 'EDITED')", name="ck_attendance_sheet_events_action"),
    )
    op.create_index("ix_attendance_sheet_events_sheet", "attendance_sheet_events", ["sheet_id", "id"])

    # The trail is append-only. A trigger, not a grant: a REVOKE means nothing to the table's owner or a superuser, and
    # the application connects as one of those in some deployments. Rows may still go when their sheet (and so their
    # session) is removed, but no row can be edited once written.
    op.execute("""
        CREATE FUNCTION attendance_sheet_events_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'attendance_sheet_events rows cannot be modified';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_attendance_sheet_events_immutable
        BEFORE UPDATE ON attendance_sheet_events
        FOR EACH ROW EXECUTE FUNCTION attendance_sheet_events_immutable()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_attendance_sheet_events_immutable ON attendance_sheet_events")
    op.execute("DROP FUNCTION IF EXISTS attendance_sheet_events_immutable()")
    op.drop_table("attendance_sheet_events")
    op.drop_table("attendance_sheets")
    op.drop_column("attendances", "updated_at")
    op.drop_column("attendances", "updated_by_id")

"""Who has read which announcement.

Revision ID: f2a9c31e6b84
Revises: e9a1c74f0b36
Create Date: 2026-10-13

One new table and nothing else, so this is safe against live data and reverses
cleanly.

The sidebar badge wants "unread announcements", and there was nowhere to record
that an announcement had been read. Notifications already carry an `is_read`
flag on the row itself, but an announcement is *one row read by many people* --
the flag would have to live on the pair, not on the announcement.

Rows are written only when somebody reads something, so the table stays sparse:
an announcement nobody opened costs nothing, and the unread count is a LEFT
JOIN that finds no row rather than a scan of a read-state matrix.

`ondelete="CASCADE"` on both sides is deliberate. A deleted announcement has no
read state worth keeping, and a deleted user's reading history is not evidence
of anything -- the audit log is where destructive administrative acts are
recorded, not here.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f2a9c31e6b84"
down_revision = "e9a1c74f0b36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "announcement_reads",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("announcement_id", sa.Integer(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name="fk_announcement_reads_user_id_users", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["announcement_id"], ["announcements.id"],
            name="fk_announcement_reads_announcement_id_announcements",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_announcement_reads"),
        # Reading twice is not an event. The upsert on this constraint is what
        # makes "mark read" idempotent, which matters because the console may
        # send it from more than one open tab.
        sa.UniqueConstraint(
            "user_id", "announcement_id", name="uq_announcement_reads_user_announcement"
        ),
    )
    # The badge query is "announcements visible to me with no read row for me",
    # so it starts from one user and looks for their rows.
    op.create_index(
        "ix_announcement_reads_user", "announcement_reads", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_announcement_reads_user", table_name="announcement_reads")
    op.drop_table("announcement_reads")

"""LAIT academic sync: course images, batch enrolment count, run kind.

Revision ID: b27e4c90a1d3
Revises: a15c0de5f1d7
Create Date: 2026-09-20 14:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b27e4c90a1d3"
down_revision: Union[str, Sequence[str], None] = "a15c0de5f1d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # One picture column becomes two: the site publishes a thumbnail and a
    # full-size image. Renamed rather than dropped so existing values survive.
    op.alter_column("courses", "course_picture", new_column_name="course_image",
                    existing_type=sa.String(255), type_=sa.String(500), existing_nullable=True)
    op.add_column("courses", sa.Column("small_course_image", sa.String(500), nullable=True,
                                       comment="Thumbnail image URL"))

    op.add_column("batches", sa.Column("total_enrollments", sa.Integer(), server_default=sa.text("0"),
                                       nullable=False))
    # Backfill from what already exists, so the number is right before the first sync.
    op.execute("""
        UPDATE batches b SET total_enrollments = COALESCE(
            (SELECT count(*) FROM enrollments e WHERE e.batch_id = b.id
             AND e.status IN ('PENDING', 'CONFIRMED', 'COMPLETED')), 0)
    """)

    op.add_column("user_sync_runs", sa.Column("kind", sa.String(10), server_default=sa.text("'USERS'"),
                                              nullable=False))
    # A session is generated once per (batch, start): this also makes a re-sync idempotent.
    op.create_index("ux_batch_sessions_batch_start", "batch_sessions", ["batch_id", "session_start_time"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_batch_sessions_batch_start", table_name="batch_sessions")
    op.drop_column("user_sync_runs", "kind")
    op.drop_column("batches", "total_enrollments")
    op.drop_column("courses", "small_course_image")
    op.alter_column("courses", "course_image", new_column_name="course_picture",
                    existing_type=sa.String(500), type_=sa.String(255), existing_nullable=True)

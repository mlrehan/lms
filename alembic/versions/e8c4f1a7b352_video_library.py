"""Video library: videos and video_shares

Revision ID: e8c4f1a7b352
Revises: d7b3e8f2a640
Create Date: 2026-11-02 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8c4f1a7b352"
down_revision: Union[str, None] = "d7b3e8f2a640"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "videos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("batches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_videos_public_id", "videos", ["public_id"], unique=True)
    op.create_index("ix_videos_course_id", "videos", ["course_id"])
    op.create_index("ix_videos_batch_id", "videos", ["batch_id"])
    op.create_index("ix_videos_owner_id", "videos", ["owner_id"])
    op.create_index("ix_videos_live", "videos", ["id"], postgresql_where=sa.text("deleted_at IS NULL"))

    op.create_table(
        "video_shares",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("batches.id", ondelete="CASCADE"), nullable=True),
        sa.Column("shared_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("(user_id IS NULL) <> (batch_id IS NULL)", name="ck_video_shares_one_recipient"),
    )
    op.create_index("ix_video_shares_video_id", "video_shares", ["video_id"])
    op.create_index("ix_video_shares_user_id", "video_shares", ["user_id"])
    op.create_index("ix_video_shares_batch_id", "video_shares", ["batch_id"])
    op.create_index("uq_video_shares_user", "video_shares", ["video_id", "user_id"], unique=True,
                    postgresql_where=sa.text("user_id IS NOT NULL"))
    op.create_index("uq_video_shares_batch", "video_shares", ["video_id", "batch_id"], unique=True,
                    postgresql_where=sa.text("batch_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_table("video_shares")
    op.drop_table("videos")

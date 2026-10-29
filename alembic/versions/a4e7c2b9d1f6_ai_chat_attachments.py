"""AI chat attachments.

`ai_attachments` holds files a person attaches to an assistant message, with
their extracted text; `ai_conversation_messages.attachments` records which
files a message carried (names and ids, never contents) so a reopened
conversation shows them and later turns can refer back to them.

Additive only: a new table and a nullable column.

Revision ID: a4e7c2b9d1f6
Revises: f3c9a1d47e85
Create Date: 2026-10-29 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4e7c2b9d1f6"
down_revision: Union[str, None] = "f3c9a1d47e85"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_attachments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(127), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("status IN ('READY', 'EMPTY')", name="ck_ai_attachments_status"),
    )
    op.create_index("ix_ai_attachments_public_id", "ai_attachments", ["public_id"], unique=True)
    op.create_index("idx_ai_attachments_user_created", "ai_attachments", ["user_id", "created_at"])
    op.add_column("ai_conversation_messages", sa.Column("attachments", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_conversation_messages", "attachments")
    op.drop_index("idx_ai_attachments_user_created", table_name="ai_attachments")
    op.drop_index("ix_ai_attachments_public_id", table_name="ai_attachments")
    op.drop_table("ai_attachments")

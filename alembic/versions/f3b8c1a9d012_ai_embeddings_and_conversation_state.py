"""AI embeddings and conversation state tables.

Revision ID: f3b8c1a9d012
Revises: 91a150439935
Create Date: 2026-10-21 14:00:00.000000
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3b8c1a9d012"
down_revision: Union[str, None] = "91a150439935"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Enable pgvector if available on the host/container
    conn = op.get_bind()
    try:
        is_available = conn.execute(
            sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector';")
        ).scalar()
        if is_available:
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector;"))
    except Exception:
        # Graceful fallback if pgvector extension is not installed; embeddings stored as JSON
        pass

    # 2. Resource Embeddings table
    op.create_table(
        "resource_embeddings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("embedding_model", sa.String(length=64), nullable=False, server_default="text-embedding-3-large"),
        sa.Column("dimensions", sa.Integer(), nullable=False, server_default="3072"),
        sa.Column("course_id", sa.Integer(), nullable=True),
        sa.Column("batch_id", sa.Integer(), nullable=True),
        sa.Column("is_restricted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index("idx_resource_embeddings_resource_id", "resource_embeddings", ["resource_id"])
    op.create_index("idx_resource_embeddings_course_restricted", "resource_embeddings", ["course_id", "is_restricted"])
    op.create_index("idx_resource_embeddings_batch_id", "resource_embeddings", ["batch_id"])

    # 3. AI Conversation Messages table
    op.create_table(
        "ai_conversation_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_calls", sa.JSON(), nullable=True),
        sa.Column("is_flagged", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index("idx_ai_messages_user_created", "ai_conversation_messages", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("ai_conversation_messages")
    op.drop_table("resource_embeddings")


"""Resource index state for the course-material search.

Records, per resource, which stored file was indexed, with which embedding
model, and the outcome -- so the indexer knows what is new, what changed and
what to stop retrying. See backend/models/ai_index_state.py.

New and empty: every existing resource simply starts out unindexed, which is
what it is (resource_embeddings has never been written to).

Revision ID: d4e8a17b3c52
Revises: c7d2e94a1f30
Create Date: 2026-10-28 16:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e8a17b3c52"
down_revision: Union[str, None] = "c7d2e94a1f30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "resource_index_states",
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("embedding_model", sa.String(length=64), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('INDEXED', 'EMPTY', 'UNSUPPORTED', 'FAILED')",
            name=op.f("ck_resource_index_states_status"),
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["resources.id"],
            name=op.f("fk_resource_index_states_resource_id_resources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("resource_id", name=op.f("pk_resource_index_states")),
    )


def downgrade() -> None:
    op.drop_table("resource_index_states")

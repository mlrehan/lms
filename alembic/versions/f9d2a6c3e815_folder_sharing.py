"""Folder sharing, and the index "Shared with me" was missing

Revision ID: f9d2a6c3e815
Revises: e8c4f1a7b352
Create Date: 2026-11-07 12:00:00.000000

* ``shared_folders``: a folder handed to one person at a level. Access to the
  files inside is *computed* from the tree (a file's folder and its
  ancestors), never copied into a row per file, so a folder of a thousand
  files is one row and a file moved in or out gains or loses access at once.
  ``UNIQUE (folder_id, shared_with_user_id)`` is the duplicate guard, the same
  one ``shared_resources`` already has, and what makes a retried share a no-op.
* ``ix_shared_resources_shared_with_user_id``: "Shared with me" filters
  ``shared_resources`` by recipient, and the only index on the table leads
  with ``resource_id``, so every read of that page was a sequential scan.

Additive only: nothing existing is altered, so the downgrade is a plain drop.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f9d2a6c3e815"
down_revision: Union[str, None] = "e8c4f1a7b352"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shared_folders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "folder_id", sa.Integer(),
            sa.ForeignKey("resource_folders.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "shared_with_user_id", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "shared_by_user_id", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("folder_id", "shared_with_user_id", name="uq_shared_folders_folder_user"),
        sa.CheckConstraint(
            "level IN ('VIEW', 'DOWNLOAD', 'EDIT', 'MANAGE')", name="ck_shared_folders_level"
        ),
    )
    op.create_index("ix_shared_folders_public_id", "shared_folders", ["public_id"], unique=True)
    op.create_index("ix_shared_folders_shared_with_user_id", "shared_folders", ["shared_with_user_id"])
    op.create_index(
        "ix_shared_resources_shared_with_user_id", "shared_resources", ["shared_with_user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_shared_resources_shared_with_user_id", table_name="shared_resources")
    op.drop_index("ix_shared_folders_shared_with_user_id", table_name="shared_folders")
    op.drop_index("ix_shared_folders_public_id", table_name="shared_folders")
    op.drop_table("shared_folders")

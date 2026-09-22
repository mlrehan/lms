"""Give a share an access level.

`shared_resources` recorded *that* a file had been shared and never *how*, so a
recipient's rights came entirely from their global role. That is why a read-only
audience could still download, and why staff could edit a file that had been
handed to them to look at.

Existing rows are backfilled to DOWNLOAD rather than VIEW: that is what they
effectively had before this migration, and silently tightening access on files
people already hold would break links that work today. Tightening is a decision
for whoever owns the file, made per share.

Revision ID: d8b1f4e07a23
Revises: c4f9a26e8b57
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d8b1f4e07a23"
down_revision = "c4f9a26e8b57"
branch_labels = None
depends_on = None

_LEVELS = ("VIEW", "DOWNLOAD", "EDIT", "MANAGE")


def upgrade() -> None:
    op.add_column(
        "shared_resources",
        sa.Column(
            "level",
            sa.Enum(*_LEVELS, name="resource_permission_level", native_enum=False),
            nullable=False,
            server_default="DOWNLOAD",
        ),
    )


def downgrade() -> None:
    op.drop_column("shared_resources", "level")

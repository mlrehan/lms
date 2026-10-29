"""batches.created_at

Batches had no creation timestamp, so "which batch did the last sync add?" had
no answer anywhere in the database. Existing rows stay NULL -- their creation
time was never recorded -- and only new rows get the database's clock: the
column is added with no default, which leaves existing rows NULL, and the
default is set afterwards for future inserts. Adding it WITH a default would
have stamped every existing batch with today's date, which is false.

Revision ID: b5f8d3c2e7a4
Revises: a4e7c2b9d1f6
Create Date: 2026-10-29 14:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b5f8d3c2e7a4"
down_revision: Union[str, None] = "a4e7c2b9d1f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("batches", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("batches", "created_at", server_default=sa.text("now()"))


def downgrade() -> None:
    op.drop_column("batches", "created_at")

"""batches.grading_scheme_id

A batch may be graded under a different scheme from the rest of its course
(batch -> course -> institution default). Null means "use the course's", which
is what every existing batch does and keeps doing: nothing is assigned here.

Revision ID: c6a9e2d4f1b7
Revises: b5f8d3c2e7a4
Create Date: 2026-11-01 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c6a9e2d4f1b7"
down_revision: Union[str, None] = "b5f8d3c2e7a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("batches", sa.Column("grading_scheme_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_batches_grading_scheme_id",
        "batches",
        "grading_schemes",
        ["grading_scheme_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_batches_grading_scheme_id", "batches", ["grading_scheme_id"])


def downgrade() -> None:
    op.drop_index("ix_batches_grading_scheme_id", table_name="batches")
    op.drop_constraint("fk_batches_grading_scheme_id", "batches", type_="foreignkey")
    op.drop_column("batches", "grading_scheme_id")

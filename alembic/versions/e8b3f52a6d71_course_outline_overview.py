"""Course outline and overview, from the institution's own course page.

The LMS has no lesson or module tables. What a course covers was published
only on its public page ("Course Content", "Course Overview"), which the
academic sync already fetches and parsed for level, duration, price and
prerequisites -- and discarded the content itself. These two columns keep it,
so the teaching assistant can answer "what should I teach?" from the course's
own published content rather than from nothing.

Additive and nullable: existing rows simply have no outline until the next
academic sync fills it (the assistant reads the page directly meanwhile).

Revision ID: e8b3f52a6d71
Revises: d4e8a17b3c52
Create Date: 2026-10-28 20:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8b3f52a6d71"
down_revision: Union[str, None] = "d4e8a17b3c52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("courses", sa.Column("outline", sa.Text(), nullable=True))
    op.add_column("courses", sa.Column("overview", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("courses", "overview")
    op.drop_column("courses", "outline")

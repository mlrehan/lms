"""Make a transcript an official record rather than two numbers.

`transcripts` carried a GPA, a letter and a flag. §5 asks an official document
to state the marks, the percentage, the attendance, whether the student passed,
when it was issued and by whom -- and, once challenged, to be able to show the
arithmetic that produced it.

**These columns are stored rather than recomputed, and that is deliberate.**
Everywhere else in this system a figure is derived on read, because a stored
copy falls out of step (§23). A transcript is the exception and for the
opposite reason: it is a statement about what was true when it was issued.
Recomputing it later would silently restate a document somebody has already
relied on -- a reference, an appeal, an immigration application.

`scheme_name` is part of that. Grading schemes change; a transcript that cannot
say which policy produced its figures cannot be defended.

All nullable, so every existing row stays valid and simply has nothing to say
about the new fields until it is regenerated.

Revision ID: d82b4f0c17ae
Revises: c40a6e2b91d7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d82b4f0c17ae"
down_revision = "c40a6e2b91d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        sa.Column("final_percentage", sa.Numeric(5, 2), nullable=True),
        sa.Column("total_marks_earned", sa.Numeric(8, 2), nullable=True),
        sa.Column("total_marks_possible", sa.Numeric(8, 2), nullable=True),
        sa.Column("is_pass", sa.Boolean(), nullable=True),
        sa.Column("scheme_name", sa.String(120), nullable=True),
        sa.Column("sessions_total", sa.Integer(), nullable=True),
        sa.Column("sessions_attended", sa.Integer(), nullable=True),
        sa.Column("attendance_percentage", sa.Numeric(5, 2), nullable=True),
        sa.Column("breakdown", sa.JSON(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_by", sa.Integer(), nullable=True),
    ):
        op.add_column("transcripts", column)

    op.create_foreign_key(
        "fk_transcripts_issued_by", "transcripts", "users", ["issued_by"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_transcripts_issued_by", "transcripts", type_="foreignkey")
    for name in (
        "issued_by", "issued_at", "breakdown", "attendance_percentage",
        "sessions_attended", "sessions_total", "scheme_name", "is_pass",
        "total_marks_possible", "total_marks_earned", "final_percentage",
    ):
        op.drop_column("transcripts", name)

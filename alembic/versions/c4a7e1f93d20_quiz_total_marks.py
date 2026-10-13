"""Give a quiz a paper total to write questions against.

Revision ID: c4a7e1f93d20
Revises: b2f9d4c7a1e8

A quiz had `passing_score` (the pass mark) and a derived `total_points` (the
sum of whatever questions happened to exist). There was no way to say "this
paper is out of 50" before writing it, so nothing could tell a tutor they had
written 60 marks of questions into a 50-mark paper -- the paper simply became
whatever the questions added up to, and the pass mark silently meant something
different from what was intended.

`total_marks` is the stated total. **Nullable on purpose**: every quiz that
already exists was written without one, and defaulting them to the sum of
their current questions would invent a decision nobody made -- and would then
refuse the next question added to any of them. A null total means "no stated
ceiling", which is exactly the behaviour those quizzes have today.

Numeric(6, 2) rather than Integer, to match `questions.points`
(Numeric(5, 2)): half marks are ordinary, and a paper total that cannot
express the sum of its own questions would be a new way to be wrong.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c4a7e1f93d20"
down_revision = "b2f9d4c7a1e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "quizzes",
        sa.Column(
            "total_marks",
            sa.Numeric(6, 2),
            nullable=True,
            comment="The paper's stated total. Null means no stated ceiling.",
        ),
    )
    # A total of zero would make every question refusable and is never what
    # anybody means; a negative one is nonsense. Checked in the database as
    # well as the schema, because the API is not the only writer -- the LAIT
    # sync and any future import write here too.
    op.create_check_constraint(
        "ck_quizzes_total_marks_positive",
        "quizzes",
        "total_marks IS NULL OR total_marks > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_quizzes_total_marks_positive", "quizzes", type_="check")
    op.drop_column("quizzes", "total_marks")

"""Give the quiz settings that were stored but never read something to read.

Revision ID: f17c4a9b0e23
Revises: e93a5c17b204

Five columns on `quizzes` were written at creation and read by nothing:
`questions_per_attempt`, `auto_submit_on_expiry`, `show_result_immediately`,
`show_correct_answers` and `show_explanations`. A switch that does nothing is
worse than an absent one -- somebody sets it and believes the paper is a
random draw, or that marks are withheld until release, and neither was true.

Three of them could not have been implemented as the schema stood, which is
presumably why they were not:

* `show_result_immediately` had nothing to wait *for*. Marking and releasing
  are separate acts for assignments (`SubmissionState.PUBLISHED`) and for
  exams (`exam_results.is_published`); quizzes had no equivalent, so
  "immediately" had no opposite. `quizzes.results_released_at` is it.
  **Nullable, meaning not released** -- so every existing quiz behaves
  exactly as it does today, because every existing quiz has
  `show_result_immediately = true` and is unaffected by the gate.
* `show_explanations` had nothing to show: no question carried one.
  `questions.explanation` is it.
* `auto_submit_on_expiry` had nowhere to record that an attempt was closed by
  the clock rather than by the student. `quiz_attempts.auto_submitted` is
  that, and it is deliberately **not** `submitted_late`: late means the timer
  was advisory and the student submitted by hand afterwards, which is the
  opposite case. Both exist, and a tutor needs to tell them apart.

`question_options.match_text` belongs to the same pass for a different
reason: the four question types §9 asks for (fill in the blank, matching,
ordering, numeric) need somewhere to keep an answer key. Three of the four
need no schema at all -- fill-in-the-blank and numeric keys live in the
existing `questions.settings` JSON (their shapes differ per type, so a column
each would be null for every other question), and ordering reuses
`question_options.order`. Matching is the one that does: a pair is stored as
one row with both sides, so a half-deleted pair cannot exist.

Every column is nullable or carries a default that reproduces today's
behaviour, so this revision is safe to apply to a live database with students
mid-attempt: an attempt in flight gets `auto_submitted = false`, which is
what it is.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f17c4a9b0e23"
down_revision = "e93a5c17b204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "quizzes",
        sa.Column("results_released_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("questions", sa.Column("explanation", sa.Text(), nullable=True))
    op.add_column("question_options", sa.Column("match_text", sa.Text(), nullable=True))
    # NOT NULL with a server default rather than nullable: "was this closed by
    # the clock?" always has an answer, and a null would invite every reader
    # to decide for itself what a null means.
    op.add_column(
        "quiz_attempts",
        sa.Column(
            "auto_submitted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # `question_type` is a VARCHAR with no CHECK constraint
    # (`native_enum=False`, and SQLAlchemy 2.0 does not create one by
    # default), so the four new types need no DDL here. Verified against the
    # live database rather than assumed from the model.


def downgrade() -> None:
    op.drop_column("quiz_attempts", "auto_submitted")
    op.drop_column("question_options", "match_text")
    op.drop_column("questions", "explanation")
    op.drop_column("quizzes", "results_released_at")

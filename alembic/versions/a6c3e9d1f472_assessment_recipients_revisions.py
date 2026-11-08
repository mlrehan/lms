"""Assessments for chosen students, reuse lineage, and revision history

Revision ID: a6c3e9d1f472
Revises: f9d2a6c3e815
Create Date: 2026-11-08 12:00:00.000000

Three additions, all additive:

* **`scope = 'STUDENTS'`** -- an assessment set for named students rather than
  a whole course, batch or session. Who they are lives in
  `assessment_recipients`, one row per student, with a real foreign key per
  assessment kind so deleting a student or an assessment cannot leave a row
  pointing at nothing. The scope column was `VARCHAR(7)` (the longest old
  value, "SESSION"), so it widens; the CHECK that ties a scope to its ids
  gains the new branch.
* **`copied_from_id`** -- an assessment reused for another batch or set of
  students is a new row with its own deadline, state, submissions and marks,
  pointing back at the one it was made from. Each copy owns its content on
  purpose: editing one batch's paper after its students sat it must not
  change what another batch is about to sit.
* **`assessment_revisions`** -- what changed after publication, from what to
  what, by whom. The audit log records only *which* fields changed; this
  keeps the values, so "the deadline was moved after I submitted" can be
  answered.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a6c3e9d1f472"
down_revision: Union[str, None] = "f9d2a6c3e815"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("assignments", "quizzes", "exams")
KINDS = (("assignment_id", "assignments"), ("quiz_id", "quizzes"), ("exam_id", "exams"))

OLD_CHECK = (
    "((scope)::text = 'COURSE'::text) OR (((scope)::text = 'BATCH'::text) AND (batch_id IS NOT NULL)) "
    "OR (((scope)::text = 'SESSION'::text) AND (session_id IS NOT NULL))"
)
NEW_CHECK = (
    "scope = 'COURSE' OR (scope = 'BATCH' AND batch_id IS NOT NULL) "
    "OR (scope = 'SESSION' AND session_id IS NOT NULL) "
    "OR (scope = 'STUDENTS' AND batch_id IS NULL AND session_id IS NULL)"
)


def upgrade() -> None:
    for table in TABLES:
        op.alter_column(table, "scope", type_=sa.String(16), existing_type=sa.String(7),
                        existing_nullable=False)
        op.drop_constraint(op.f(f"ck_{table}_ck_{table}_scope_coherent"), table, type_="check")
        op.create_check_constraint(op.f(f"ck_{table}_scope_coherent"), table, NEW_CHECK)
        op.add_column(table, sa.Column(
            "copied_from_id", sa.Integer(),
            sa.ForeignKey(f"{table}.id", ondelete="SET NULL"), nullable=True,
        ))
        op.create_index(f"ix_{table}_copied_from_id", table, ["copied_from_id"])

    def kind_columns() -> list[sa.Column]:
        return [
            sa.Column(col, sa.Integer(), sa.ForeignKey(f"{tbl}.id", ondelete="CASCADE"), nullable=True)
            for col, tbl in KINDS
        ]

    exactly_one = "num_nonnulls(assignment_id, quiz_id, exam_id) = 1"

    op.create_table(
        "assessment_recipients",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        *kind_columns(),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("added_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint(exactly_one, name=op.f("ck_assessment_recipients_one_assessment")),
    )
    op.create_index("ix_assessment_recipients_student_id", "assessment_recipients", ["student_id"])
    for col, _ in KINDS:
        op.create_index(
            f"uq_assessment_recipients_{col}_student", "assessment_recipients", [col, "student_id"],
            unique=True, postgresql_where=sa.text(f"{col} IS NOT NULL"),
        )

    op.create_table(
        "assessment_revisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        *kind_columns(),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("changed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("changes", postgresql.JSONB(), nullable=False),
        sa.Column("material", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notified", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint(exactly_one, name=op.f("ck_assessment_revisions_one_assessment")),
    )
    for col, _ in KINDS:
        op.create_index(
            f"uq_assessment_revisions_{col}_no", "assessment_revisions", [col, "revision_no"],
            unique=True, postgresql_where=sa.text(f"{col} IS NOT NULL"),
        )


def downgrade() -> None:
    op.drop_table("assessment_revisions")
    op.drop_table("assessment_recipients")
    for table in TABLES:
        op.drop_index(f"ix_{table}_copied_from_id", table_name=table)
        op.drop_column(table, "copied_from_id")
        # Anything set for named students has no equivalent in the old scheme;
        # refuse rather than silently re-target it to a whole course.
        op.execute(
            f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM {table} WHERE scope = 'STUDENTS') THEN "
            f"RAISE EXCEPTION '{table} has assessments set for named students; "
            f"re-target them before downgrading'; END IF; END $$;"
        )
        op.drop_constraint(op.f(f"ck_{table}_scope_coherent"), table, type_="check")
        op.create_check_constraint(op.f(f"ck_{table}_ck_{table}_scope_coherent"), table, OLD_CHECK)
        op.alter_column(table, "scope", type_=sa.String(7), existing_type=sa.String(16),
                        existing_nullable=False)

"""The academic assessment foundation: scoping, weighting, lifecycle.

Three gaps, all of which made the modules above them unbuildable:

1. **Assessments could not be scoped.** `assignments` and `quizzes` carried a
   NOT NULL `course_id` and nothing else, so every assessment was course-wide
   and a tutor could not set work for one batch. Exams had course/batch by a
   hand-rolled shape of their own -- a fourth convention where there should be
   one. All three now carry `batch_id` + `session_id` + `scope`.

2. **There was no weighting policy anywhere.** `gradebook_entries.weight`
   existed and every synced row was written with `1`, so the "weighted average"
   was a straight average. `grading_schemes` + `grading_scheme_components` is
   where "Examinations are 45%" now lives.

3. **A mark had no lifecycle.** `assignment_submissions` had no status column
   at all, so *absent*, *exempted*, *not yet assessed* and *scored zero* were
   indistinguishable -- the exact confusion spec §38 forbids.

**Every change is additive and every backfill preserves current behaviour.**
No column is dropped, no NOT NULL is added to an existing column, and the
defaults are chosen so that rows written before this migration keep meaning
what they meant:

* `scope` defaults to COURSE -- which is what every existing assessment is.
* `Assignment.state` defaults to PUBLISHED, not DRAFT. Defaulting to DRAFT
  would hide every piece of live coursework the moment this ran.
* `AssignmentSubmission.state` is backfilled from the data already present:
  GRADED where a mark exists, SUBMITTED where it does not.
* `grade_bands` rows are adopted by the new default scheme, so every course
  keeps the scale it had.

One constraint *is* relaxed: `grade_bands.letter_grade` loses its global
UNIQUE. Two schemes may each define an "A", and under the old constraint the
second scheme could not be created at all.

Revision ID: b71f2c8ea940
Revises: a93e17c0d5b8
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b71f2c8ea940"
down_revision = "a93e17c0d5b8"
branch_labels = None
depends_on = None

_SCOPE = sa.Enum("COURSE", "BATCH", "SESSION", name="assessment_scope", native_enum=False)
_ASSESSMENT_STATE = sa.Enum(
    "DRAFT", "SCHEDULED", "PUBLISHED", "CLOSED", "ARCHIVED",
    name="assessment_state", native_enum=False,
)
_SUBMISSION_STATE = sa.Enum(
    "NOT_STARTED", "PENDING", "SUBMITTED", "LATE", "UNDER_REVIEW", "GRADED",
    "PUBLISHED", "ABSENT", "EXEMPTED", "RESUBMISSION_REQUIRED", "REASSESSED",
    name="submission_state", native_enum=False,
)
_RESULT_STATE = sa.Enum(
    "DRAFT", "UNDER_REVIEW", "FINALIZED", "PUBLISHED",
    name="result_state", native_enum=False,
)


def _add_scope(table: str) -> None:
    """The same three columns on each assessment type.

    Written once rather than three times, because §3's whole point is that
    these are one concept -- and three copies is how they drift.
    """
    op.add_column(table, sa.Column("batch_id", sa.Integer(), nullable=True))
    op.add_column(table, sa.Column("session_id", sa.Integer(), nullable=True))
    op.add_column(
        table,
        sa.Column("scope", _SCOPE, nullable=False, server_default="COURSE"),
    )
    op.create_foreign_key(
        f"fk_{table}_batch", table, "batches", ["batch_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        f"fk_{table}_session", table, "batch_sessions", ["session_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_index(f"ix_{table}_batch", table, ["batch_id"])
    op.create_index(f"ix_{table}_session", table, ["session_id"])
    # The scope column and the ids must agree. Without this a row could claim
    # BATCH scope with no batch, and the eligibility resolver would silently
    # fall back to the whole course -- handing work to students who were never
    # meant to receive it.
    op.create_check_constraint(
        f"ck_{table}_scope_coherent",
        table,
        "(scope = 'COURSE') "
        "OR (scope = 'BATCH' AND batch_id IS NOT NULL) "
        "OR (scope = 'SESSION' AND session_id IS NOT NULL)",
    )


def upgrade() -> None:
    # ---------------------------------------------------------------- scoping
    for table in ("assignments", "quizzes"):
        _add_scope(table)

    # Exams already have `batch_id`; they only need the other two.
    op.add_column("exams", sa.Column("session_id", sa.Integer(), nullable=True))
    op.add_column("exams", sa.Column("scope", _SCOPE, nullable=False, server_default="COURSE"))
    op.add_column("exams", sa.Column("is_online", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("exams", sa.Column("weight", sa.Numeric(6, 3), nullable=False, server_default="1"))
    op.create_foreign_key(
        "fk_exams_session", "exams", "batch_sessions", ["session_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_exams_session", "exams", ["session_id"])
    # An exam whose `batch_id` is already set is a batch-scoped exam; saying so
    # is what lets the shared resolver treat it like the other two.
    op.execute("UPDATE exams SET scope = 'BATCH' WHERE batch_id IS NOT NULL")
    op.create_check_constraint(
        "ck_exams_scope_coherent",
        "exams",
        "(scope = 'COURSE') "
        "OR (scope = 'BATCH' AND batch_id IS NOT NULL) "
        "OR (scope = 'SESSION' AND session_id IS NOT NULL)",
    )

    # -------------------------------------------------- assignment rules (§8)
    op.add_column("assignments", sa.Column("state", _ASSESSMENT_STATE, nullable=False, server_default="PUBLISHED"))
    op.add_column("assignments", sa.Column("publish_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("assignments", sa.Column("available_from", sa.DateTime(timezone=True), nullable=True))
    op.add_column("assignments", sa.Column("passing_score", sa.Numeric(5, 2), nullable=True))
    op.add_column("assignments", sa.Column("weight", sa.Numeric(6, 3), nullable=False, server_default="1"))
    op.add_column("assignments", sa.Column("allowed_file_types", sa.String(255), nullable=True))
    op.add_column("assignments", sa.Column("max_upload_mb", sa.Integer(), nullable=True))
    op.add_column("assignments", sa.Column("allow_multiple_submissions", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("assignments", sa.Column("allow_resubmission", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("assignments", sa.Column("late_penalty_percent_per_day", sa.Numeric(5, 2), nullable=True))

    # ------------------------------------------------------ quiz rules (§9)
    op.add_column("quizzes", sa.Column("available_from", sa.DateTime(timezone=True), nullable=True))
    op.add_column("quizzes", sa.Column("available_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("quizzes", sa.Column("shuffle_answers", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("quizzes", sa.Column("questions_per_attempt", sa.Integer(), nullable=True))
    op.add_column("quizzes", sa.Column("show_result_immediately", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("quizzes", sa.Column("show_correct_answers", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("quizzes", sa.Column("show_explanations", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("quizzes", sa.Column("auto_submit_on_expiry", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("quizzes", sa.Column("weight", sa.Numeric(6, 3), nullable=False, server_default="1"))

    # ------------------------------------------------ submission lifecycle
    op.add_column("assignment_submissions", sa.Column("state", _SUBMISSION_STATE, nullable=False, server_default="SUBMITTED"))
    op.add_column("assignment_submissions", sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("assignment_submissions", sa.Column("raw_grade", sa.Numeric(5, 2), nullable=True))
    op.add_column("assignment_submissions", sa.Column("late_penalty_applied", sa.Numeric(5, 2), nullable=True))
    op.add_column("assignment_submissions", sa.Column("override_reason", sa.Text(), nullable=True))
    op.add_column("assignment_submissions", sa.Column("overridden_by_id", sa.Integer(), nullable=True))
    op.add_column("assignment_submissions", sa.Column("overridden_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("assignment_submissions", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_assignment_submissions_overridden_by", "assignment_submissions", "users",
        ["overridden_by_id"], ["id"], ondelete="SET NULL",
    )
    # Backfilled from what the row already says, so nothing changes meaning.
    # A graded submission was already visible to its student, which is why it
    # becomes PUBLISHED rather than GRADED -- the alternative would retract
    # marks that students can currently see.
    op.execute("UPDATE assignment_submissions SET state = 'PUBLISHED' WHERE grade IS NOT NULL")
    op.execute("UPDATE assignment_submissions SET raw_grade = grade WHERE grade IS NOT NULL")

    op.add_column("exam_results", sa.Column("state", _SUBMISSION_STATE, nullable=False, server_default="GRADED"))
    op.add_column("exam_results", sa.Column("override_reason", sa.Text(), nullable=True))
    op.add_column("exam_results", sa.Column("overridden_by_id", sa.Integer(), nullable=True))
    op.add_column("exam_results", sa.Column("overridden_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_exam_results_overridden_by", "exam_results", "users",
        ["overridden_by_id"], ["id"], ondelete="SET NULL",
    )
    op.execute("UPDATE exam_results SET state = 'PUBLISHED' WHERE is_published")
    op.execute("UPDATE exam_results SET state = 'NOT_STARTED' WHERE marks_obtained IS NULL AND NOT is_published")

    # ------------------------------------------------------- grading schemes
    op.create_table(
        "grading_schemes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scale_type", sa.Enum("PERCENTAGE", "LETTER", "GPA", "PASS_FAIL", "NUMERIC", "COMPETENCY", name="grade_scale_type", native_enum=False), nullable=False, server_default="PERCENTAGE"),
        sa.Column("missing_mark_policy", sa.Enum("EXCLUDE", "ZERO", "CARRY_FORWARD", name="missing_mark_policy", native_enum=False), nullable=False, server_default="EXCLUDE"),
        sa.Column("passing_percentage", sa.Numeric(5, 2), nullable=False, server_default="50"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_grading_schemes_public_id", "grading_schemes", ["public_id"], unique=True)
    op.create_index("ix_grading_schemes_active", "grading_schemes", ["is_active"])
    # Exactly one default, enforced rather than assumed: two defaults is a
    # state in which no code can say which scheme a course falls back to.
    op.create_index(
        "uq_grading_schemes_one_default", "grading_schemes", ["is_default"],
        unique=True, postgresql_where=sa.text("is_default"),
    )

    op.create_table(
        "grading_scheme_components",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("scheme_id", sa.Integer(), sa.ForeignKey("grading_schemes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("component_type", sa.Enum("ASSIGNMENT", "QUIZ", "ATTENDANCE", "PRACTICAL", "FINAL_EXAM", name="grade_component_type", native_enum=False), nullable=False),
        sa.Column("label", sa.String(80), nullable=True),
        sa.Column("weight_percentage", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("passing_percentage", sa.Numeric(5, 2), nullable=True),
        sa.UniqueConstraint("scheme_id", "component_type", name="uq_scheme_component"),
        sa.CheckConstraint("weight_percentage >= 0 AND weight_percentage <= 100", name="ck_scheme_component_weight_range"),
    )
    op.create_index("ix_grading_scheme_components_public_id", "grading_scheme_components", ["public_id"], unique=True)

    # `grade_bands` joins a scheme. The global unique on `letter_grade` has to
    # go: two schemes may each define an "A", and the constraint would make the
    # second scheme impossible to create.
    op.add_column("grade_bands", sa.Column("scheme_id", sa.Integer(), nullable=True))
    op.add_column("grade_bands", sa.Column("is_pass", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_foreign_key("fk_grade_bands_scheme", "grade_bands", "grading_schemes", ["scheme_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_grade_bands_scheme", "grade_bands", ["scheme_id"])
    op.execute("ALTER TABLE grade_bands DROP CONSTRAINT IF EXISTS grade_bands_letter_grade_key")
    op.create_unique_constraint("uq_grade_band_scheme_letter", "grade_bands", ["scheme_id", "letter_grade"])

    # The institution's default scheme, so nothing has to cope with there being
    # none. Weights are left at zero deliberately: inventing "examinations are
    # 45%" on an institution's behalf would silently re-grade every student.
    # An empty scheme makes the engine report "not yet configured", which is
    # true and actionable, rather than a confident wrong number.
    op.execute(
        """
        INSERT INTO grading_schemes (public_id, name, description, is_default, is_active)
        VALUES (gen_random_uuid(), 'Institution default',
                'Created automatically. Set component weightings before relying on overall performance.',
                true, true)
        """
    )
    op.execute("UPDATE grade_bands SET scheme_id = (SELECT id FROM grading_schemes WHERE is_default)")

    op.add_column("courses", sa.Column("grading_scheme_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_courses_grading_scheme", "courses", "grading_schemes", ["grading_scheme_id"], ["id"], ondelete="SET NULL")

    # ------------------------------------------------- class performance (§11)
    op.create_table(
        "class_performance_marks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("batch_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        *[sa.Column(c, sa.Numeric(5, 2), nullable=True) for c in (
            "participation", "interaction", "preparation", "practical",
            "presentation", "teamwork", "communication", "professionalism",
        )],
        sa.Column("custom_scores", sa.JSON(), nullable=True),
        sa.Column("max_score", sa.Numeric(5, 2), nullable=False, server_default="10"),
        sa.Column("overall_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("state", _RESULT_STATE, nullable=False, server_default="DRAFT"),
        sa.Column("recorded_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        # One assessment per student per session. A second row would double
        # that student's class-performance contribution.
        sa.UniqueConstraint("session_id", "student_id", name="uq_class_perf_session_student"),
        sa.CheckConstraint("max_score > 0", name="ck_class_perf_max_positive"),
    )
    op.create_index("ix_class_performance_marks_public_id", "class_performance_marks", ["public_id"], unique=True)
    op.create_index("ix_class_perf_student", "class_performance_marks", ["student_id"])
    op.create_index("ix_class_perf_session", "class_performance_marks", ["session_id"])


def downgrade() -> None:
    op.drop_table("class_performance_marks")

    op.drop_constraint("fk_courses_grading_scheme", "courses", type_="foreignkey")
    op.drop_column("courses", "grading_scheme_id")

    op.drop_constraint("uq_grade_band_scheme_letter", "grade_bands", type_="unique")
    op.drop_index("ix_grade_bands_scheme", table_name="grade_bands")
    op.drop_constraint("fk_grade_bands_scheme", "grade_bands", type_="foreignkey")
    op.drop_column("grade_bands", "is_pass")
    op.drop_column("grade_bands", "scheme_id")
    op.create_unique_constraint("grade_bands_letter_grade_key", "grade_bands", ["letter_grade"])

    op.drop_table("grading_scheme_components")
    op.drop_table("grading_schemes")

    for col in ("override_reason", "overridden_by_id", "overridden_at", "state"):
        if col == "overridden_by_id":
            op.drop_constraint("fk_exam_results_overridden_by", "exam_results", type_="foreignkey")
        op.drop_column("exam_results", col)

    op.drop_constraint("fk_assignment_submissions_overridden_by", "assignment_submissions", type_="foreignkey")
    for col in ("published_at", "overridden_at", "overridden_by_id", "override_reason",
                "late_penalty_applied", "raw_grade", "attempt_number", "state"):
        op.drop_column("assignment_submissions", col)

    for col in ("weight", "auto_submit_on_expiry", "show_explanations", "show_correct_answers",
                "show_result_immediately", "questions_per_attempt", "shuffle_answers",
                "available_until", "available_from"):
        op.drop_column("quizzes", col)

    for col in ("late_penalty_percent_per_day", "allow_resubmission", "allow_multiple_submissions",
                "max_upload_mb", "allowed_file_types", "weight", "passing_score",
                "available_from", "publish_at", "state"):
        op.drop_column("assignments", col)

    op.drop_constraint("ck_exams_scope_coherent", "exams", type_="check")
    op.drop_index("ix_exams_session", table_name="exams")
    op.drop_constraint("fk_exams_session", "exams", type_="foreignkey")
    for col in ("weight", "is_online", "scope", "session_id"):
        op.drop_column("exams", col)

    for table in ("quizzes", "assignments"):
        op.drop_constraint(f"ck_{table}_scope_coherent", table, type_="check")
        op.drop_index(f"ix_{table}_session", table_name=table)
        op.drop_index(f"ix_{table}_batch", table_name=table)
        op.drop_constraint(f"fk_{table}_session", table, type_="foreignkey")
        op.drop_constraint(f"fk_{table}_batch", table, type_="foreignkey")
        for col in ("scope", "session_id", "batch_id"):
            op.drop_column(table, col)

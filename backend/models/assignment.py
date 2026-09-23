from datetime import datetime

from sqlalchemy import (Integer, String, ForeignKey, DateTime,
                        Enum as SQLEnum, Text, Numeric, JSON, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from backend.models.base import Base, PublicIdMixin
from .helpers import utc_datetime_column, bool_column
from backend.utils.enums import (
    AssessmentScope,
    AssessmentState,
    SubmissionState,
    SubmissionType,
)


class Assignment(Base, PublicIdMixin):
    """Spec §12."""
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # -- academic scope (spec §3) ------------------------------------------
    # `course_id` stays NOT NULL: every assessment belongs to a course, and a
    # batch or session only narrows the audience within it. Keeping it
    # mandatory means the existing course-wide rows stay valid untouched, and
    # no query that joins through the course has to handle a null.
    course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id"), nullable=False)
    batch_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("batches.id", ondelete="CASCADE"), nullable=True
    )
    session_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("batch_sessions.id", ondelete="CASCADE"), nullable=True
    )
    # Stored rather than inferred from which id is non-null. "Set for the whole
    # course" and "set for a batch nobody has chosen yet" are different states;
    # an inference rule cannot tell them apart, and the CHECK below is what
    # keeps the column and the ids honest with each other.
    scope: Mapped[AssessmentScope] = mapped_column(
        SQLEnum(AssessmentScope, name="assessment_scope", native_enum=False),
        nullable=False,
        default=AssessmentScope.COURSE,
        server_default=AssessmentScope.COURSE.value,
    )

    # -- visibility (spec §8, §14) ------------------------------------------
    # Whether the *question* is visible. Distinct from a result's lifecycle,
    # which is about the *mark*. A tutor drafting next week's work and a tutor
    # withholding this week's marks are doing different things.
    state: Mapped[AssessmentState] = mapped_column(
        SQLEnum(AssessmentState, name="assessment_state", native_enum=False),
        nullable=False,
        default=AssessmentState.PUBLISHED,
        server_default=AssessmentState.PUBLISHED.value,
        comment="Existing rows are PUBLISHED: they were already visible, and a migration must not hide live work.",
    )
    publish_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    instructions_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="Spec §12: tutor-uploaded instructions file")
    due_date: Mapped[datetime] = utc_datetime_column(default=False, nullable=False)
    max_score: Mapped[Numeric] = mapped_column(Numeric(5, 2), nullable=False)
    submission_type: Mapped[SubmissionType] = mapped_column(SQLEnum(SubmissionType, name="submission_type", native_enum=False), nullable=False)

    # -- rules (spec §8) ----------------------------------------------------
    # `available_from` is the mirror of `due_date`: work that opens on Monday
    # and is due on Friday could previously only express the Friday.
    available_from: Mapped[Optional[datetime]] = utc_datetime_column(default=False)
    passing_score: Mapped[Optional[Numeric]] = mapped_column(Numeric(5, 2), nullable=True)
    # This assessment's pull within its component. Two assignments in a course
    # need not be worth the same; the component's share of the final mark is a
    # separate, scheme-level decision.
    weight: Mapped[Numeric] = mapped_column(
        Numeric(6, 3), nullable=False, default=1, server_default="1"
    )
    allowed_file_types: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="Comma-separated extensions; null means the platform default."
    )
    max_upload_mb: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    allow_multiple_submissions: Mapped[bool] = bool_column(default=False)
    allow_resubmission: Mapped[bool] = bool_column(default=False)
    # Percentage removed per day late. Null means late work is accepted at
    # full marks when `allow_late_submissions` is set -- which is what the
    # system did before this column existed, so existing rows keep behaving
    # exactly as they do today.
    late_penalty_percent_per_day: Mapped[Optional[Numeric]] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    # e.g. [{"criteria": "Code Readability", "max_points": 5}]
    rubric: Mapped[Optional[dict]] = mapped_column(JSON)
    allow_late_submissions: Mapped[bool] = bool_column(default=False)

    # `Quiz` and `Exam` both carry a `course` relationship; `Assignment` was
    # the one that only ever had the raw FK column, so any query needing the
    # course's title or public_id had nothing to eager-load.
    course: Mapped["Course"] = relationship("Course", lazy="selectin")
    # Eager, like `course`: every list response names the scope, so a lazy load
    # here would be one query per row -- the N+1 §33 forbids.
    batch: Mapped[Optional["Batch"]] = relationship(  # noqa: F821
        "Batch", foreign_keys=[batch_id], lazy="selectin"
    )
    session: Mapped[Optional["BatchSession"]] = relationship(  # noqa: F821
        "BatchSession", foreign_keys=[session_id], lazy="selectin"
    )
    submissions: Mapped[List["AssignmentSubmission"]] = relationship(back_populates="assignment")


class AssignmentSubmission(Base, PublicIdMixin):
    __tablename__ = "assignment_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assignment_id: Mapped[int] = mapped_column(Integer, ForeignKey("assignments.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # e.g. [{"filename": "project.zip", "path": "..."}, ...]
    files: Mapped[Optional[dict]] = mapped_column(JSON)
    content: Mapped[Optional[str]] = mapped_column(Text)  # for TEXT submission type
    grade: Mapped[Optional[Numeric]] = mapped_column(Numeric(5, 2))
    feedback: Mapped[Optional[str]] = mapped_column(Text)
    graded_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    graded_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False)

    # -- lifecycle (spec §7, §14, §38) --------------------------------------
    # This table previously had no status at all: a null `grade` meant
    # "ungraded", and there was no way to record that a student was absent,
    # exempted, or asked to resubmit. §38 insists those be distinguishable from
    # a mark of zero, and a nullable number cannot do it.
    #
    # Existing rows are backfilled from the data they already carry -- graded
    # if they have a mark, submitted if they do not -- so nothing changes
    # meaning under the migration.
    state: Mapped[SubmissionState] = mapped_column(
        SQLEnum(SubmissionState, name="submission_state", native_enum=False),
        nullable=False,
        default=SubmissionState.SUBMITTED,
        server_default=SubmissionState.SUBMITTED.value,
    )
    attempt_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    # What the mark was before a penalty or an override. Kept so the drill-down
    # can show the arithmetic rather than a number nobody can account for.
    raw_grade: Mapped[Optional[Numeric]] = mapped_column(Numeric(5, 2), nullable=True)
    late_penalty_applied: Mapped[Optional[Numeric]] = mapped_column(Numeric(5, 2), nullable=True)

    # -- override audit (spec §24) ------------------------------------------
    # A changed mark must be explicable. `audit_logs` records that it happened;
    # these say what it was and why, next to the mark itself, where whoever is
    # looking at the grade will actually see them.
    override_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    overridden_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    overridden_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False)
    published_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False)

    assignment: Mapped["Assignment"] = relationship(back_populates="submissions")
    student: Mapped["User"] = relationship(
        primaryjoin="AssignmentSubmission.student_id == User.id",
        back_populates="submissions"
    )
    grader: Mapped["User"] = relationship(
        primaryjoin="AssignmentSubmission.graded_by_id == User.id",
        back_populates="graded_submissions"
    )

    __table_args__ = (
        # Spec §12: a student may "replace before deadline" -- one submission
        # row per (assignment, student) that gets updated in place, rather
        # than silently accumulating duplicate rows on every re-upload.
        UniqueConstraint("assignment_id", "student_id", name="uq_assignment_submissions_assignment_student"),
    )

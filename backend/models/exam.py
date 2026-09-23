"""Examination (spec §14) -- deliberately not a copy of the Quiz question-bank
machinery in quiz.py. The spec frames Examination as scheduling, invigilator
assignment, and result publication: a formal, scheduled event, evaluated by a
person, not a bank of auto-graded questions. Quiz already owns that shape."""

from datetime import datetime

from sqlalchemy import (CheckConstraint, Integer, String, ForeignKey, DateTime, Text,
                        Enum as SQLEnum, Numeric, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from backend.models.base import Base, PublicIdMixin
from .helpers import bool_column, utc_datetime_column
from backend.utils.enums import AssessmentScope, ExamType, SubmissionState


class Exam(Base, PublicIdMixin):
    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    course_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=True)
    batch_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("batches.id", ondelete="CASCADE"), nullable=True)
    # Exams already had course/batch by a hand-rolled shape of their own. They
    # now carry the same `session_id` + `scope` the other two do, so one
    # eligibility resolver serves all three rather than exams keeping a fourth
    # convention.
    session_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("batch_sessions.id", ondelete="CASCADE"), nullable=True
    )
    scope: Mapped[AssessmentScope] = mapped_column(
        SQLEnum(AssessmentScope, name="assessment_scope", native_enum=False),
        nullable=False,
        default=AssessmentScope.COURSE,
        server_default=AssessmentScope.COURSE.value,
    )
    # Online exams are answered in the LMS; offline ones have their marks
    # entered afterwards. Both feed the same grade book (§10), and this is what
    # lets a screen know which workflow to offer.
    is_online: Mapped[bool] = bool_column(default=False)
    weight: Mapped[Numeric] = mapped_column(
        Numeric(6, 3), nullable=False, default=1, server_default="1"
    )
    exam_type: Mapped[ExamType] = mapped_column(
        SQLEnum(ExamType, name="exam_type", native_enum=False), nullable=False,
        comment="MIDTERM, FINAL, PRACTICAL, MOCK, CUSTOM",
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    venue_or_link: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="Physical venue or online meeting link")
    total_marks: Mapped[Numeric] = mapped_column(Numeric(6, 2), nullable=False)
    passing_marks: Mapped[Numeric] = mapped_column(Numeric(6, 2), nullable=False)
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Whether the *schedule* is visible to students -- independent of whether
    # results have been published (see ExamResult.is_published below).
    is_published: Mapped[bool] = bool_column(default=False)

    course: Mapped[Optional["Course"]] = relationship("Course", lazy="selectin")
    batch: Mapped[Optional["Batch"]] = relationship("Batch", lazy="selectin")
    invigilators: Mapped[List["ExamInvigilator"]] = relationship(back_populates="exam", cascade="all, delete-orphan", passive_deletes=True, lazy="selectin")
    results: Mapped[List["ExamResult"]] = relationship(back_populates="exam", cascade="all, delete-orphan", passive_deletes=True, lazy="selectin")

    __table_args__ = (
        # Both FKs are individually nullable (an exam may be scheduled for a
        # whole course, or for one specific batch), but an exam anchored to
        # *neither* is unreachable by every scoping query in
        # `services/scope.py` -- invisible to every role except an
        # unrestricted admin, and meaningless besides. The constraint says
        # "at least one", which the two nullable columns alone cannot.
        CheckConstraint(
            "course_id IS NOT NULL OR batch_id IS NOT NULL",
            name="anchored_to_course_or_batch",
        ),
    )


class ExamInvigilator(Base):
    """Spec §14's invigilator assignment."""
    __tablename__ = "exam_invigilators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exam_id: Mapped[int] = mapped_column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    tutor_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    exam: Mapped["Exam"] = relationship(back_populates="invigilators")
    tutor: Mapped["User"] = relationship("User", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("exam_id", "tutor_id", name="uq_exam_invigilators_exam_tutor"),
    )


class ExamResult(Base, PublicIdMixin):
    """Spec §14: grades and result publication -- a separate flag from the
    exam's own `is_published`, since a schedule can be public well before
    results are ready to release."""
    __tablename__ = "exam_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exam_id: Mapped[int] = mapped_column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    marks_obtained: Mapped[Optional[Numeric]] = mapped_column(Numeric(6, 2), nullable=True)
    grade: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_published: Mapped[bool] = bool_column(default=False)
    # The lifecycle §14 asks for. `is_published` is kept and maintained in
    # step: it is read by existing queries and API responses, and breaking
    # those to avoid one redundant column would be a worse trade.
    state: Mapped[SubmissionState] = mapped_column(
        SQLEnum(SubmissionState, name="submission_state", native_enum=False),
        nullable=False,
        default=SubmissionState.GRADED,
        server_default=SubmissionState.GRADED.value,
    )
    override_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    overridden_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    overridden_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False)

    exam: Mapped["Exam"] = relationship(back_populates="results")
    # `foreign_keys` is now required: this table gained `overridden_by_id`, so
    # there are two paths to `users` and SQLAlchemy cannot pick one for us.
    student: Mapped["User"] = relationship(
        "User", foreign_keys=[student_id], lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("exam_id", "student_id", name="uq_exam_results_exam_student"),
    )

"""Grade book (spec §15): "Stores Assignments, Quizzes, Attendance, Practical,
Final exam, Overall GPA, Transcript generation." `GradeBookEntry` is one row
per contribution matching that exact list; `Transcript` is the aggregated,
publishable record. Computing the aggregation is a service-layer concern for
a later pass -- this pass only makes the data representable and correct."""

from datetime import datetime

from sqlalchemy import (Index, Integer, String, ForeignKey, Numeric, text,
                        Enum as SQLEnum, Boolean, UniqueConstraint, CheckConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from backend.models.base import Base, PublicIdMixin
from .helpers import utc_datetime_column
from backend.utils.enums import GradeComponentType


class GradeBand(Base):
    """Institution-wide grading scale -- the minimum needed to make "Overall
    GPA" (spec §15) computable rather than hand-waved."""
    __tablename__ = "grade_bands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    min_score: Mapped[Numeric] = mapped_column(Numeric(5, 2), nullable=False)
    max_score: Mapped[Numeric] = mapped_column(Numeric(5, 2), nullable=False)
    letter_grade: Mapped[str] = mapped_column(String(5), unique=True, nullable=False)
    gpa_points: Mapped[Numeric] = mapped_column(Numeric(3, 2), nullable=False)

    __table_args__ = (
        CheckConstraint("min_score <= max_score", name="min_le_max"),
    )


class GradeBookEntry(Base, PublicIdMixin):
    """One row per assignment/quiz/attendance/practical/final-exam
    contribution to a student's grade in a batch."""
    __tablename__ = "gradebook_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey("batches.id", ondelete="CASCADE"), nullable=False)
    component_type: Mapped[GradeComponentType] = mapped_column(
        SQLEnum(GradeComponentType, name="grade_component_type", native_enum=False), nullable=False,
        comment="ASSIGNMENT, QUIZ, ATTENDANCE, PRACTICAL, FINAL_EXAM",
    )
    # Points to the specific assignment_submissions/quiz_attempts/exam_results
    # row this entry summarizes, when the component type has one. Left as a
    # plain nullable id (no FK) since the referenced table varies by
    # component_type -- a single polymorphic FK isn't expressible in SQL.
    reference_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    score: Mapped[Numeric] = mapped_column(Numeric(6, 2), nullable=False)
    max_score: Mapped[Numeric] = mapped_column(Numeric(6, 2), nullable=False)
    weight: Mapped[Numeric] = mapped_column(Numeric(4, 3), nullable=False, default=1, server_default="1")
    recorded_at: Mapped[datetime] = utc_datetime_column(nullable=False)

    student: Mapped["User"] = relationship("User", lazy="selectin")
    batch: Mapped["Batch"] = relationship("Batch", lazy="selectin")

    __table_args__ = (
        # One entry per source row. Re-syncing the grade book must correct
        # the existing entry rather than append a second one -- otherwise
        # every re-sync doubles a student's marks and the computed GPA drifts
        # further from reality on each run.
        #
        # Two partial indexes rather than one constraint, because
        # `reference_id` is nullable and Postgres treats NULLs as distinct:
        # a plain UNIQUE over four columns would happily allow unlimited
        # duplicate ATTENDANCE rows, which are exactly the ones with no
        # source row to point at.
        Index(
            "uq_gradebook_entry_sourced",
            "student_id", "batch_id", "component_type", "reference_id",
            unique=True,
            postgresql_where=text("reference_id IS NOT NULL"),
        ),
        Index(
            "uq_gradebook_entry_unsourced",
            "student_id", "batch_id", "component_type",
            unique=True,
            postgresql_where=text("reference_id IS NULL"),
        ),
    )


class Transcript(Base, PublicIdMixin):
    """The aggregated, publishable grade record (spec §15's "Transcript
    generation"). Populating `gpa`/`overall_grade` from `GradeBookEntry` rows
    is a service-layer computation, not modelled here."""
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey("batches.id", ondelete="CASCADE"), nullable=False)
    gpa: Mapped[Optional[Numeric]] = mapped_column(Numeric(3, 2), nullable=True)
    overall_grade: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    generated_at: Mapped[datetime] = utc_datetime_column(nullable=False)
    is_final: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    student: Mapped["User"] = relationship("User", lazy="selectin")
    course: Mapped["Course"] = relationship("Course", lazy="selectin")
    batch: Mapped["Batch"] = relationship("Batch", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("student_id", "batch_id", name="uq_transcripts_student_batch"),
    )

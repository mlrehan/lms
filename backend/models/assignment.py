from datetime import datetime

from sqlalchemy import (Integer, String, ForeignKey, DateTime,
                        Enum as SQLEnum, Text, Numeric, JSON, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from backend.models.base import Base, PublicIdMixin
from .helpers import utc_datetime_column, bool_column
from backend.utils.enums import SubmissionType


class Assignment(Base, PublicIdMixin):
    """Spec §12."""
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    instructions_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="Spec §12: tutor-uploaded instructions file")
    due_date: Mapped[datetime] = utc_datetime_column(default=False, nullable=False)
    max_score: Mapped[Numeric] = mapped_column(Numeric(5, 2), nullable=False)
    submission_type: Mapped[SubmissionType] = mapped_column(SQLEnum(SubmissionType, name="submission_type", native_enum=False), nullable=False)
    # e.g. [{"criteria": "Code Readability", "max_points": 5}]
    rubric: Mapped[Optional[dict]] = mapped_column(JSON)
    allow_late_submissions: Mapped[bool] = bool_column(default=False)

    # `Quiz` and `Exam` both carry a `course` relationship; `Assignment` was
    # the one that only ever had the raw FK column, so any query needing the
    # course's title or public_id had nothing to eager-load.
    course: Mapped["Course"] = relationship("Course", lazy="selectin")
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

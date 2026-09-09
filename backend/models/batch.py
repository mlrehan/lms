from datetime import date, datetime

from sqlalchemy import (Integer, String, ForeignKey, Date,
                        Enum as SQLEnum, text, Text, Index)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from backend.models.base import Base, PublicIdMixin
from .helpers import utc_datetime_column, bool_column, utc_date_column
from backend.utils.enums import Platforms


class Batch(Base, PublicIdMixin):
    """Spec §6: a course may run multiple batches."""
    __tablename__ = 'batches'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    batch_code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False, comment="Spec §6 batch code, e.g. 'MATH101-A'")
    course_id: Mapped[int] = mapped_column(Integer, ForeignKey('courses.id'), nullable=False)
    academic_year_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("academic_years.id", ondelete="SET NULL"), nullable=True)
    semester_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("semesters.id", ondelete="SET NULL"), nullable=True)

    duration_hours: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    number_of_sessions: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    capacity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="Spec §6 batch capacity")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    start_date: Mapped[Optional[date]] = utc_date_column(default=False)
    end_date: Mapped[Optional[date]] = utc_date_column(default=False)
    is_active: Mapped[bool] = bool_column(default=True)

    course: Mapped["Course"] = relationship("Course", back_populates='batches', lazy="selectin")
    academic_year: Mapped[Optional["AcademicYear"]] = relationship("AcademicYear", back_populates="batches", lazy="selectin")
    semester: Mapped[Optional["Semester"]] = relationship("Semester", back_populates="batches", lazy="selectin")
    student_reviews: Mapped[List["TutorReview"]] = relationship("TutorReview", back_populates="batch", lazy="selectin")
    sessions: Mapped[List["BatchSession"]] = relationship("BatchSession", back_populates="batch", lazy="selectin")
    enrollments: Mapped[List["Enrollments"]] = relationship(
        "Enrollments",
        back_populates="batch",
        lazy="selectin"
    )

    __table_args__ = (
        Index(
            "idx_batches_active",
            "is_active",
            "id",
        ),
    )


class BatchSession(Base, PublicIdMixin):
    """Spec §8: each batch contains sessions."""
    __tablename__ = "batch_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey("batches.id"), nullable=False)
    tutor_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)

    session_start_time: Mapped[datetime] = utc_datetime_column(default=False)
    session_end_time: Mapped[datetime] = utc_datetime_column(default=False)
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    classroom: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Spec §8 physical classroom, when not online")

    platform: Mapped[Platforms] = mapped_column(
        SQLEnum(Platforms, name="platforms_enum", native_enum=False),
        server_default=text(f"'{Platforms.Zoom.name}'"),
        nullable=False,
    )
    # Moved here from Batch: a link is only meaningful in the context of a
    # platform, and platform was already per-session -- a batch-level link
    # would silently be wrong for any session run on a different platform
    # (a substitute tutor, a guest lecture, a mid-course switch). Lives next
    # to `platform` and `recording_link`, which were already per-session for
    # the same reason.
    meeting_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    tutor_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    student_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recording_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    batch: Mapped[Batch] = relationship(Batch, back_populates="sessions", lazy="selectin")
    tutor: Mapped["User"] = relationship("User", back_populates="sessions", lazy="selectin")

    attendances: Mapped[list["Attendance"]] = relationship(
        "Attendance",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    __table_args__ = (
        Index(
            "idx_batch_sessions_batch",
            "batch_id",
        ),
    )

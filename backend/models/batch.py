from datetime import date, datetime, time

import sqlalchemy as sa

from sqlalchemy import (Integer, String, ForeignKey, Date,
                        Enum as SQLEnum, text, Text, Index, Time, Numeric)
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
    # When the row was inserted. NULL for batches that existed before the
    # column did: their creation time was never recorded, and "unknown" is the
    # truth -- backfilling the migration's own timestamp would claim every old
    # batch was created the day it ran.
    created_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()
    )

    # How the batch is scheduled. These say on which weekdays classes are held and when, so sessions can be generated
    # (services/session_planner.py) instead of typed in one by one. `schedule_timezone` is the zone the clock times
    # are written in; the sessions themselves are stored in UTC like everything else.
    training_days: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment='e.g. "Monday & Friday"')
    training_start_day: Mapped[Optional[str]] = mapped_column(String(12), nullable=True, comment="Weekday of the first class")
    training_end_day: Mapped[Optional[str]] = mapped_column(String(12), nullable=True, comment="Weekday of the last class")
    training_start_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    training_end_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    class_duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    training_method: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment='Delivery method as named by the source, e.g. "Classroom Training"')
    batch_fee: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    schedule_timezone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Google Calendar mirror. The calendar id is the mapping; the hash is the digest of what was
    # last pushed, so an unchanged batch costs no API call.
    google_calendar_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    google_synced_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    google_admins_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, comment="Admin emails the calendar was last shared with")
    google_synced_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False)
    google_pulled_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False)
    total_enrollments: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"),
        comment="Seeded from LAIT's total_admission, then recounted from enrollments by the sync",
    )

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
    cancelled_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False)
    cancelled_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    origin: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, comment="LAIT | MANUAL | GOOGLE; NULL = legacy, treated as LAIT")
    google_event_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    google_synced_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    google_synced_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False)

    tutor_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    student_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # The provider's own URL (Zoom, Meet). Reachable by anyone holding the
    # string, so it is never returned to a caller who cannot edit the session.
    recording_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # A recording uploaded *into* the LMS. Playback streams through the API,
    # permission checked per request, with no link that works outside it.
    recording_resource_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("resources.id", ondelete="SET NULL"), nullable=True
    )

    batch: Mapped[Batch] = relationship(Batch, back_populates="sessions", lazy="selectin")
    tutor: Mapped["User"] = relationship("User", back_populates="sessions", lazy="selectin")
    # Deliberately no `recording` relationship. `Resource` eager-loads six
    # relationships of its own, so a `selectin` here would pull all of them for
    # every session on a 3000-row calendar window to answer a question almost no
    # caller asks. The one place that needs the row loads it by id.

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
        Index("ux_batch_sessions_batch_start", "batch_id", "session_start_time", unique=True, postgresql_where=text("cancelled_at IS NULL")),
    )

from datetime import datetime

from sqlalchemy import (Integer, ForeignKey, Index, Text, UniqueConstraint,
                        Enum as SQLEnum, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from backend.models.base import Base, PublicIdMixin
from .helpers import utc_datetime_column
from backend.utils.enums import AttendanceStatus


class Attendance(Base, PublicIdMixin):
    """Spec §9: attendance per session, one of four states."""
    __tablename__ = "attendances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)

    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("batch_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    recorded_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)

    status: Mapped[AttendanceStatus] = mapped_column(
        SQLEnum(AttendanceStatus, name="attendance_status", native_enum=False),
        server_default=text(f"'{AttendanceStatus.ABSENT.value}'"),
        nullable=False,
        comment="PRESENT, LATE, ABSENT, EXCUSED",
    )
    remarks: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Reason, esp. for EXCUSED")
    recorded_at: Mapped[datetime] = utc_datetime_column(default=True, nullable=False)

    # Relationships
    session: Mapped["BatchSession"] = relationship(
        "BatchSession",
        back_populates="attendances",
        lazy="selectin",
    )

    student: Mapped["User"] = relationship(
        "User",
        back_populates="attendances",
        foreign_keys=[student_id],
        lazy="selectin",
    )

    tutor: Mapped["User"] = relationship(
        "User",
        back_populates="recorded_attendances",
        foreign_keys=[recorded_by],
        lazy="selectin",
    )

    __table_args__ = (
        # One record per student per session. Without this, re-marking a
        # register inserts a second row instead of correcting the first, and
        # a student ends up simultaneously PRESENT and ABSENT for the same
        # class -- with every attendance percentage silently wrong. The
        # service upserts against this constraint.
        UniqueConstraint("session_id", "student_id", name="uq_attendances_session_student"),
        Index(
            "idx_attendances_student",
            "student_id",
        ),
        Index(
            "idx_attendances_student_status",
            "student_id",
            "status",
        ),
    )

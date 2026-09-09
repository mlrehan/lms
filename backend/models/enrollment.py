from datetime import datetime

from sqlalchemy import (Integer, ForeignKey,
                        Enum as SQLEnum, text, Text, Index)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from backend.models.base import Base, PublicIdMixin
from .helpers import utc_datetime_column, bool_column
from backend.utils.enums import EnrollmentStatus, PerformanceLevel


class Enrollments(Base, PublicIdMixin):
    """Spec §7: student enrollment for one or more courses."""
    __tablename__ = 'enrollments'

    enrollment_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    admission_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey('batches.id'))
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'))
    enrollment_date: Mapped[datetime] = utc_datetime_column(default=True)

    status: Mapped[EnrollmentStatus] = mapped_column(
        SQLEnum(EnrollmentStatus, name="enrollment_status", native_enum=False),
        server_default=text(f"'{EnrollmentStatus.PENDING.value}'"),
        nullable=False,
        comment="PENDING, CONFIRMED, COMPLETED, DROPPED, CANCELLED",
    )

    # Spec §7's "transfer batches" / "re-enroll" -- a linked chain of
    # enrollment rows rather than silently overwriting one row's batch_id,
    # so the history of where a student has actually been enrolled survives.
    previous_enrollment_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("enrollments.enrollment_id", ondelete="SET NULL"), nullable=True
    )
    is_transfer: Mapped[bool] = bool_column(default=False, nullable=False)

    is_manager: Mapped[bool] = bool_column(default=False)
    performance_level: Mapped[Optional[PerformanceLevel]] = mapped_column(
        SQLEnum(PerformanceLevel, name="performance_level", native_enum=False),
        nullable=True,
        comment="poor, below_average, average, good, excellent",
    )
    can_download_certificate: Mapped[bool] = bool_column(default=False)
    certificate_url: Mapped[Optional[str]] = mapped_column(Text)
    enrolled_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"))

    # Which organization sponsored *this* enrollment, independent of the
    # student's current organization_memberships row -- a student who later
    # changes employer must not rewrite who paid for/initiated an enrollment
    # made under their previous employer.
    organization_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )

    student: Mapped["User"] = relationship("User", back_populates="enrollments", lazy="selectin", foreign_keys=[student_id])
    batch: Mapped["Batch"] = relationship("Batch", back_populates="enrollments", lazy="selectin")
    enrolled_by_user: Mapped["User"] = relationship("User", back_populates="given_enrollments", lazy="selectin", foreign_keys=[enrolled_by])
    previous_enrollment: Mapped[Optional["Enrollments"]] = relationship("Enrollments", remote_side=[enrollment_id])
    organization: Mapped[Optional["Organization"]] = relationship("Organization", lazy="selectin")

    __table_args__ = (
        # A plain UniqueConstraint(batch_id, student_id) would make spec §7's
        # "re-enroll" impossible -- once a student's first enrollment in a
        # batch was DROPPED, no second row could ever be inserted for that
        # pair again. Scoping the uniqueness to only the "currently active"
        # statuses allows a fresh enrollment row once the old one reaches a
        # terminal state, while still stopping two *simultaneous* active
        # enrollments of the same student in the same batch.
        Index(
            "uq_enrollments_active_batch_student",
            "batch_id",
            "student_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'CONFIRMED')"),
        ),
        Index("idx_enrollments_student_status", "student_id", "status"),
        Index("idx_enrollments_batch", "batch_id"),
        Index("idx_enrollments_organization", "organization_id"),
    )

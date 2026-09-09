"""A student may have more than one guardian, and a guardian may have more
than one ward -- a genuine many-to-many, not a `guardian_id` column on the
student (which could only ever express one guardian per student).

Fine-grained visibility ("which of attendance/grades/certificates is this
guardian allowed to see") is an authorization-policy question answered by
the same role/permission machinery as everywhere else, not a set of boolean
columns on this table -- a boolean per data category here would need a new
column every time a new category of student data is added.
"""

from datetime import datetime

from sqlalchemy import Integer, String, ForeignKey, UniqueConstraint, Boolean, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from backend.models.base import Base, PublicIdMixin
from .helpers import utc_datetime_column


class StudentGuardian(Base, PublicIdMixin):
    __tablename__ = "student_guardians"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guardian_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    relationship_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="e.g. 'Parent', 'Legal Guardian'")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
    created_at: Mapped[datetime] = utc_datetime_column(nullable=False)

    guardian: Mapped["User"] = relationship("User", foreign_keys=[guardian_id], back_populates="wards", lazy="selectin")
    student: Mapped["User"] = relationship("User", foreign_keys=[student_id], back_populates="guardians", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("guardian_id", "student_id", name="uq_student_guardians_guardian_student"),
    )

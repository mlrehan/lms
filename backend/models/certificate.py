from datetime import datetime

from sqlalchemy import Integer, String, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from backend.models.base import Base, PublicIdMixin
from .helpers import utc_datetime_column


class Certificate(Base, PublicIdMixin):
    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    template: Mapped[Optional[dict]] = mapped_column(JSON, comment="Template reference or full data for rendering")
    # e.g. {"min_final_score": 80, "modules_completed": 5}
    criteria: Mapped[Optional[dict]] = mapped_column(JSON)
    issued_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), comment="Tutor/Admin who created the certificate definition")

    issuer: Mapped["User"] = relationship("User", foreign_keys=[issued_by_id], lazy="selectin")
    issued: Mapped[List["CertificateIssued"]] = relationship(back_populates="certificate_template")


class CertificateIssued(Base, PublicIdMixin):
    __tablename__ = "certificates_issued"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    certificate_id: Mapped[int] = mapped_column(ForeignKey("certificates.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    issued_at: Mapped[datetime] = utc_datetime_column(nullable=False)
    certificate_url: Mapped[Optional[str]] = mapped_column(String(512))
    serial_number: Mapped[Optional[str]] = mapped_column(String(100), unique=True)

    certificate_template: Mapped["Certificate"] = relationship(back_populates="issued")
    student: Mapped["User"] = relationship(back_populates="issued_certificates")

"""Administration (spec §23): academic years, semesters, departments,
categories, tags, settings. None of these existed before this pass --
`Course.category` was a free-text string with nothing behind it."""

from datetime import date

from sqlalchemy import (Integer, String, ForeignKey, Date, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from backend.models.base import Base, PublicIdMixin
from .helpers import bool_column


# Reference data every course and batch form reads, and the one part of the
# schema where the *usage* counts matter more than the rows themselves: "can
# I delete this department?" is answered by how many courses point at it.
#
# `lazy="raise"` on all five back-reference collections is deliberate. They
# exist so the foreign keys have a name on this side, not so anybody walks
# them: listing 40 tags would otherwise load every course on every tag, and
# under asyncio a plain lazy load surfaces as `MissingGreenlet` rather than
# as "you asked for too much". The counts the API actually needs are one
# GROUP BY in `repositories/administration.py`.


class AcademicYear(Base, PublicIdMixin):
    __tablename__ = "academic_years"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    label: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, comment="e.g. '2025-2026'")
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_current: Mapped[bool] = bool_column(default=False)

    semesters: Mapped[List["Semester"]] = relationship(back_populates="academic_year", lazy="selectin")
    batches: Mapped[List["Batch"]] = relationship(back_populates="academic_year", lazy="raise")


class Semester(Base, PublicIdMixin):
    __tablename__ = "semesters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    academic_year_id: Mapped[int] = mapped_column(Integer, ForeignKey("academic_years.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="e.g. 'Fall', 'Spring'")
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    academic_year: Mapped["AcademicYear"] = relationship(back_populates="semesters")
    batches: Mapped[List["Batch"]] = relationship(back_populates="semester", lazy="raise")

    __table_args__ = (
        UniqueConstraint("academic_year_id", "name", name="uq_semesters_year_name"),
    )


class Department(Base, PublicIdMixin):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    code: Mapped[Optional[str]] = mapped_column(String(20), unique=True, nullable=True)
    head_tutor_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    head_tutor: Mapped[Optional["User"]] = relationship("User", lazy="selectin")
    courses: Mapped[List["Course"]] = relationship(back_populates="department", lazy="raise")


class Category(Base, PublicIdMixin):
    """Replaces `Course.category`'s previous free-text column."""
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)

    parent: Mapped[Optional["Category"]] = relationship("Category", remote_side=[id], back_populates="children")
    children: Mapped[List["Category"]] = relationship("Category", back_populates="parent", lazy="selectin")
    courses: Mapped[List["Course"]] = relationship(back_populates="category", lazy="raise")

    __table_args__ = (
        UniqueConstraint("parent_id", "name", name="uq_categories_parent_name"),
    )


class Tag(Base, PublicIdMixin):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    courses: Mapped[List["Course"]] = relationship("Course", secondary="course_tags", back_populates="tags", lazy="raise")


class CourseTag(Base):
    __tablename__ = "course_tags"

    course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)


class SystemSetting(Base):
    """Minimal key/value settings store (spec §23)."""
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

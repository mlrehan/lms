from datetime import datetime

from sqlalchemy import (Integer, String, Float, ForeignKey,
                        Enum as SQLEnum, text, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from backend.models.base import Base, PublicIdMixin, SoftDeleteMixin
from .helpers import utc_datetime_column
from backend.utils.enums import Levels, CourseStatus


class Course(Base, PublicIdMixin, SoftDeleteMixin):
    """Course table structure (spec §5)."""
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    category_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    department_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    # §13: a course may override the institution's default grading scheme.
    # Null means "use the default", which is what every existing course does
    # and continues to do -- the migration adds no scheme to anything.
    grading_scheme_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("grading_schemes.id", ondelete="SET NULL"), nullable=True
    )

    # Spec §5's exact lifecycle: Draft -> Published -> Running -> Completed
    # -> Archived. There was previously no status column at all here.
    status: Mapped[CourseStatus] = mapped_column(
        SQLEnum(CourseStatus, name="course_status", native_enum=False),
        server_default=text(f"'{CourseStatus.DRAFT.value}'"),
        nullable=False,
        comment="DRAFT, PUBLISHED, RUNNING, COMPLETED, ARCHIVED",
    )

    level: Mapped[Levels] = mapped_column(
        SQLEnum(Levels, name="levels", native_enum=False),
        server_default=text(f"'{Levels.BEGINNER.value}'"),
        nullable=False,
        comment="BEGINNER, INTERMEDIATE, ADVANCED",
    )
    title: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    code: Mapped[Optional[str]] = mapped_column(String(30), unique=True, nullable=True, comment="Spec §5 course code")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_hours: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    course_link: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    course_image: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="Full-size course image URL")
    small_course_image: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="Thumbnail image URL")
    prerequisites: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = utc_datetime_column(nullable=False, default=True)
    updated_at: Mapped[Optional[datetime]] = utc_datetime_column(onupdate=True, default=False)

    def _image_url(self, kind: str, value: Optional[str]) -> Optional[str]:
        """An external URL is passed through; an uploaded image (a storage key, which must
        never leave the server) becomes the API path that serves it, versioned by the key's
        file name so a replaced picture is fetched again and an unchanged one is cached."""
        if not value:
            return None
        if value.lower().startswith(("http://", "https://")):
            return value
        version = value.rsplit("/", 1)[-1].split(".")[0][:12]
        return f"/courses/{self.public_id}/image/{kind}?v={version}"

    @property
    def course_image_url(self) -> Optional[str]:
        return self._image_url("full", self.course_image)

    @property
    def small_course_image_url(self) -> Optional[str]:
        return self._image_url("small", self.small_course_image)

    category: Mapped[Optional["Category"]] = relationship("Category", back_populates="courses", lazy="selectin")
    department: Mapped[Optional["Department"]] = relationship("Department", back_populates="courses", lazy="selectin")
    batches: Mapped[List['Batch']] = relationship('Batch', back_populates="course", lazy="selectin")
    resources: Mapped[List['Resource']] = relationship('Resource', back_populates="course", lazy="selectin")
    tags: Mapped[List["Tag"]] = relationship("Tag", secondary="course_tags", back_populates="courses", lazy="selectin")
    tutors: Mapped[List["User"]] = relationship(
        "User",
        secondary="tutor_courses",
        back_populates="courses",
        lazy="selectin"
    )


class TutorCourse(Base):
    """Tutor <-> Course association table."""
    __tablename__ = "tutor_courses"
    tutor_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), primary_key=True)
    course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id"), primary_key=True)

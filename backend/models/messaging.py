from datetime import datetime

from sqlalchemy import (Integer, String, ForeignKey, Text, CheckConstraint, Index, Numeric)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from backend.models.base import Base, PublicIdMixin
from .helpers import utc_datetime_column, bool_column


class TutorReview(Base, PublicIdMixin):
    """Student feedback on tutors with rating & course/batch context."""
    __tablename__ = "tutor_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tutor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[Optional[int]] = mapped_column(ForeignKey("courses.id", ondelete="SET NULL"), nullable=True)
    batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("batches.id", ondelete="SET NULL"), nullable=True)

    headline: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    rating: Mapped[float] = mapped_column(
        Numeric(2, 1),
        CheckConstraint("rating >= 0 AND rating <= 5", name="rating_range"),
        nullable=False,
        comment="Rating range: 0.0 to 5.0"
    )

    comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    is_anonymous: Mapped[bool] = bool_column(default=False)
    is_visible: Mapped[bool] = bool_column(default=True)

    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = utc_datetime_column(nullable=False)
    updated_at: Mapped[Optional[datetime]] = utc_datetime_column(onupdate=True, nullable=True)

    student: Mapped["User"] = relationship(
        "User",
        foreign_keys=[student_id],
        back_populates="reviews_written",
        lazy="selectin"
    )

    tutor: Mapped["User"] = relationship(
        "User",
        foreign_keys=[tutor_id],
        back_populates="reviews_received",
        lazy="selectin"
    )

    course: Mapped[Optional["Course"]] = relationship("Course", foreign_keys=[course_id], lazy="selectin")

    batch: Mapped[Optional["Batch"]] = relationship(
        "Batch",
        foreign_keys=[batch_id],
        back_populates="student_reviews",
        lazy="selectin"
    )


class CourseDiscussion(Base, PublicIdMixin):
    """Spec §16's "Course discussions" -- a public, course-scoped thread,
    distinct from a private message (`models/mail.py`)."""
    __tablename__ = "course_discussions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_pinned: Mapped[bool] = bool_column(default=False)
    is_locked: Mapped[bool] = bool_column(default=False, comment="Locked threads accept no new replies")
    created_at: Mapped[datetime] = utc_datetime_column(nullable=False)

    __table_args__ = (
        Index("ix_course_discussions_course_created", "course_id", "created_at"),
    )

    course: Mapped["Course"] = relationship("Course", lazy="selectin")
    author: Mapped["User"] = relationship("User", lazy="selectin")
    # `lazy="raise"`, not `selectin`: a thread with 300 replies would
    # otherwise load all 300 on every row of a *list* of threads, where the
    # only thing being rendered is a reply count. Replies are read through
    # their own paged endpoint. `passive_deletes=True` means deleting a
    # thread still cascades in the database without loading the collection.
    replies: Mapped[List["DiscussionReply"]] = relationship(
        back_populates="discussion", cascade="all, delete-orphan", passive_deletes=True,
        order_by="DiscussionReply.created_at", lazy="raise",
    )


class DiscussionReply(Base, PublicIdMixin):
    __tablename__ = "discussion_replies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discussion_id: Mapped[int] = mapped_column(Integer, ForeignKey("course_discussions.id", ondelete="CASCADE"), nullable=False)
    author_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = utc_datetime_column(nullable=False)

    # `lazy="raise"`: the parent thread is always already in hand wherever a
    # reply is loaded, and a default lazy load here would surface under
    # asyncio as `MissingGreenlet` rather than as a missing eager option.
    discussion: Mapped["CourseDiscussion"] = relationship(back_populates="replies", lazy="raise")
    author: Mapped["User"] = relationship("User", lazy="selectin")

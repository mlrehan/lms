from datetime import datetime

from sqlalchemy import (Integer, String, ForeignKey, Text, Index, JSON, text,
                        UniqueConstraint, Enum as SQLEnum)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from backend.models.base import Base, PublicIdMixin
from .helpers import utc_datetime_column, bool_column
from backend.utils.enums import NotificationChannel, Roles


class Notification(Base, PublicIdMixin):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(
        SQLEnum(NotificationChannel, name="notification_channel", native_enum=False), nullable=False,
        comment="SYSTEM, EMAIL, SMS, PUSH (spec §16/§21)",
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False, comment="e.g. assignment_due, exam_scheduled, attendance_alert")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # e.g. {"course_id": "...", "assignment_id": "..."} for deep linking
    meta: Mapped[Optional[dict]] = mapped_column(JSON)
    is_read: Mapped[bool] = bool_column(default=False)
    sent_at: Mapped[datetime] = utc_datetime_column(nullable=False)

    # Every read of this table is "mine, newest first" or "mine, unread"; the
    # unread badge runs on every page load, so it gets its own partial index
    # rather than scanning a user's whole notification history to count.
    __table_args__ = (
        Index("ix_notifications_user_sent", "user_id", "sent_at"),
        Index(
            "ix_notifications_user_unread",
            "user_id",
            postgresql_where=text("is_read = false"),
        ),
    )

    user: Mapped["User"] = relationship(back_populates="notifications")


class NotificationPreference(Base):
    """One row per (user, notification type) the user has turned **off**.

    Storing only the exceptions, not a row per user per type: a full matrix
    would be 12 rows per account created at registration, and would then need
    a backfill migration every time a type is added -- with the accounts
    missed by that backfill silently defaulting to whatever the join produced.
    Absence means "on", which is also the right default for somebody who has
    never opened the preferences screen.

    Mandatory types (see `core/notification_types.py`) are refused at write
    time rather than represented here: a row that exists and is ignored is the
    decorative-field pattern, and on a security notice it would be actively
    misleading.
    """

    __tablename__ = "notification_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled: Mapped[bool] = bool_column(default=True, nullable=False)
    updated_at: Mapped[datetime] = utc_datetime_column(onupdate=True, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "notification_type", name="uq_notification_pref"),
        Index("ix_notification_preferences_user", "user_id"),
    )


class Announcement(Base, PublicIdMixin):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Targeted announcements need to be queried and indexed -- a JSON
    # audience blob can't be. Any of these left NULL means "everyone".
    course_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=True)
    batch_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("batches.id", ondelete="CASCADE"), nullable=True)
    role_scope: Mapped[Optional[Roles]] = mapped_column(SQLEnum(Roles, name="announcement_role_scope", native_enum=False), nullable=True)

    start_at: Mapped[datetime] = utc_datetime_column(nullable=False)
    # `default=False` is load-bearing, not tidiness. `utc_datetime_column`
    # defaults to `default=True`, which attaches `server_default=
    # CURRENT_TIMESTAMP` -- and SQLAlchemy treats an attribute set to `None`
    # as "unset" when a default exists, so passing `end_at=None` for "never
    # expires" fired the default instead. Every announcement was stored
    # already expired, and the feed was empty for every reader while the
    # rows sat plainly visible in the table.
    end_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False, nullable=True)
    pinned: Mapped[bool] = bool_column(default=False)

    # The feed query is "currently live, newest first", filtered by audience.
    __table_args__ = (
        Index("ix_announcements_window", "start_at", "end_at"),
        Index("ix_announcements_course", "course_id"),
        Index("ix_announcements_batch", "batch_id"),
    )

    course: Mapped[Optional["Course"]] = relationship("Course", lazy="selectin")
    batch: Mapped[Optional["Batch"]] = relationship("Batch", lazy="selectin")
    author: Mapped[Optional["User"]] = relationship("User", lazy="selectin")


class AnnouncementRead(Base):
    """One person has read one announcement.

    A notification carries its own `is_read`, because a notification belongs to
    exactly one person. An announcement is one row read by many, so the read
    state belongs to the pair rather than to either side.

    Rows appear only when somebody reads something, so an announcement nobody
    opened costs nothing and the unread count is a LEFT JOIN that finds no row.
    """

    __tablename__ = "announcement_reads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    announcement_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("announcements.id", ondelete="CASCADE"), nullable=False
    )
    read_at: Mapped[datetime] = utc_datetime_column(nullable=False)

    __table_args__ = (
        # Reading twice is not an event: the upsert on this constraint is what
        # makes "mark read" idempotent across several open tabs.
        UniqueConstraint(
            "user_id", "announcement_id", name="uq_announcement_reads_user_announcement"
        ),
        Index("ix_announcement_reads_user", "user_id"),
    )

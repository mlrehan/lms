"""The video library: links to recordings a provider hosts, shared with people or batches.

A video here is a *pointer*, not bytes. YouTube, Vimeo, Zoom and the rest keep
the file; this table keeps what the provider was, the address it was found at
(never sent to a viewer -- see `api/v1/videos.py`), who added it, and who it
was shared with. Watching goes through a route that re-checks access every
time and then hands the browser to the provider's own player.

A file the institution must keep entirely under its own control belongs in the
resource library instead, where `/resources/{id}/preview` streams the bytes
from our storage with no provider in between.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, PublicIdMixin

from .helpers import utc_datetime_column


class Video(Base, PublicIdMixin):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    #: `core.video_links` provider code: youtube, vimeo, wistia, zoom, ...
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    #: The canonical link as the owner gave it. Withheld from every viewer who
    #: cannot edit the video; they watch through `/videos/{id}/player`.
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)

    #: Optional context, for filtering and for the batch audience below.
    course_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    batch_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("batches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )

    owner_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = utc_datetime_column(nullable=False)
    updated_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False, onupdate=True)
    #: Deleting withdraws the video; shares and the audit trail of who watched stay.
    deleted_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False)

    shares: Mapped[list["VideoShare"]] = relationship(
        back_populates="video", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )

    __table_args__ = (
        Index("ix_videos_live", "id", postgresql_where=text("deleted_at IS NULL")),
    )


class VideoShare(Base):
    """One recipient of a video: a person, or every student of a batch."""

    __tablename__ = "video_shares"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    batch_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("batches.id", ondelete="CASCADE"), nullable=True, index=True
    )
    shared_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = utc_datetime_column(nullable=False)

    video: Mapped[Video] = relationship(back_populates="shares", lazy="raise")

    __table_args__ = (
        # Exactly one of the two: a share names a person or a batch, never both
        # and never neither (a row reaching nobody would read as a share that
        # silently failed).
        CheckConstraint(
            "(user_id IS NULL) <> (batch_id IS NULL)", name="one_recipient"
        ),
        Index("uq_video_shares_user", "video_id", "user_id", unique=True,
              postgresql_where=text("user_id IS NOT NULL")),
        Index("uq_video_shares_batch", "video_id", "batch_id", unique=True,
              postgresql_where=text("batch_id IS NOT NULL")),
    )

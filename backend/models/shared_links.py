from datetime import datetime

from sqlalchemy import (Integer, String, ForeignKey,
                        Enum as SQLEnum, UniqueConstraint, text, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from backend.models.base import Base, PublicIdMixin
from .helpers import utc_datetime_column, bool_column
from backend.utils.enums import ResourceType, FileStatus

class SharedLink(Base, PublicIdMixin):
    __tablename__ = "shared_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    url: Mapped[str] = mapped_column(String(2048), nullable=False)

    provider: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="youtube, vimeo, google_drive, medium, custom"
    )

    link_type: Mapped[ResourceType] = mapped_column(
        SQLEnum(ResourceType, name="resource_type", native_enum=False),
        nullable=False,
        comment="video, article, document, recording, announcement, etc."
    )

    is_embeddable: Mapped[bool] = bool_column(
        default=True,
        nullable=False,
        comment="Whether this link can be embedded in iframe"
    )

    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    shared_by: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )

    # `native_enum=False` (VARCHAR + CHECK) for consistency with every other
    # enum column in the codebase; this was previously the one exception,
    # creating a native Postgres enum type instead. `server_default` must be
    # a real DDL clause, not a bare Python string -- fixed to `text(...)`.
    status: Mapped[FileStatus] = mapped_column(
        SQLEnum(FileStatus, name="shared_link_status", native_enum=False),
        server_default=text(f"'{FileStatus.active.value}'"),
        nullable=False
    )

    visible_from: Mapped[Optional[datetime]] = utc_datetime_column(nullable=True)
    visible_until: Mapped[Optional[datetime]] = utc_datetime_column(default=False, nullable=True)

    click_count: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), nullable=False
    )

    created_at: Mapped[datetime] = utc_datetime_column(nullable=False)
    updated_at: Mapped[Optional[datetime]] = utc_datetime_column(onupdate=True)

    shared_by_user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[shared_by],
        back_populates="shared_links_sent",
        lazy="selectin"
    )
    shared_targets: Mapped[List["SharedLinkTarget"]] = relationship(
        "SharedLinkTarget",
        back_populates="shared_link", lazy="selectin",
        foreign_keys="[SharedLinkTarget.shared_link_id]"
    )

class SharedLinkTarget(Base):
    __tablename__ = "shared_link_targets"
    __table_args__ = (
        UniqueConstraint(
            "shared_link_id",
            "user_id",
            name="uq_shared_link_target_user"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    shared_link_id: Mapped[int] = mapped_column(
        ForeignKey("shared_links.id"), nullable=False
    )

    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id")
    )

    shared_link: Mapped[SharedLink] = relationship(
        "SharedLink",
        foreign_keys=[shared_link_id],
        back_populates="shared_targets",
        lazy="selectin"
    )

    shared_with_user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="shared_links_received",
        lazy="selectin"
    )

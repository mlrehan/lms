from datetime import datetime

from sqlalchemy import Integer, String, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from backend.models.base import Base, PublicIdMixin
from .helpers import utc_datetime_column


class Badge(Base, PublicIdMixin):
    __tablename__ = "badges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    # e.g. {"type": "quiz_success", "quiz_id": "..."}
    criteria: Mapped[Optional[dict]] = mapped_column(JSON)
    image_url: Mapped[Optional[str]] = mapped_column(String(255))

    users: Mapped[List["UserBadge"]] = relationship(back_populates="badge")


class UserBadge(Base):
    __tablename__ = "user_badges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    badge_id: Mapped[int] = mapped_column(ForeignKey("badges.id"), nullable=False)
    awarded_at: Mapped[datetime] = utc_datetime_column(nullable=False)

    user: Mapped["User"] = relationship(back_populates="user_badges")
    badge: Mapped["Badge"] = relationship(back_populates="users")

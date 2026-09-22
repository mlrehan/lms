"""A device that has agreed to be interrupted.

One row per browser-and-profile, not per person: the same account on a laptop
and a phone are two subscriptions, and pushing to one is not pushing to the
other. The endpoint URL is the address the push service gave that browser, and
it is what identifies the row -- a person who clears site data and re-subscribes
gets a new endpoint, and the old one starts returning 410, which is the only
reliable signal that a subscription is dead.

`p256dh` and `auth` are the browser's own public key material. They are not
secrets of ours and are useless without the corresponding private key, which
never leaves the device -- payload encryption happens against them so that the
push service (Google, Mozilla, Apple) relays a message it cannot read.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, PublicIdMixin

from .helpers import utc_datetime_column


class PushSubscription(Base, PublicIdMixin):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Unique across the table, not per user: a shared or re-assigned device
    # must not end up delivering one person's notifications to another's
    # subscription. Re-registering an endpoint moves it to the new owner.
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(String(255), nullable=False)
    auth: Mapped[str] = mapped_column(String(255), nullable=False)

    user_agent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = utc_datetime_column(nullable=False)
    # Touched on every successful send, so a stale-device cleanup has something
    # to work from other than "created a long time ago", which is also true of
    # the phone somebody uses every day.
    last_used_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False)

    user: Mapped["User"] = relationship("User", lazy="selectin")  # noqa: F821

    __table_args__ = (Index("ix_push_subscriptions_user", "user_id"),)

"""Outbound integrations (spec §25): webhooks and calendar feeds.

Both tables describe places institution data **leaves** the platform, which
is what makes them different from everything else in this schema. Every other
model answers "who may read this row"; these answer "where does this row get
sent, and who can make the server send it".

Two consequences visible in the columns:

* `secret` and `token_hash` are credentials the platform issues, not ones a
  caller supplies. The webhook secret is shown once at creation and never
  echoed again; the calendar token is stored **hashed**, exactly like a
  refresh token, because a leaked `calendar_feeds` row must not itself be a
  usable feed URL.
* `failure_count` / `last_failure_reason` exist so a dead endpoint is
  visible rather than silently retried for ever. An integration that has
  been failing for a month should look different from one that has never
  fired.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    JSON,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, PublicIdMixin

from .helpers import bool_column, utc_datetime_column


class WebhookEndpoint(Base, PublicIdMixin):
    """A URL the platform POSTs events to."""

    __tablename__ = "webhook_endpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    target_url: Mapped[str] = mapped_column(String(500), nullable=False)

    # Shown once, at creation. Every delivery is signed with it so a receiver
    # can tell a genuine call from anybody who guessed the URL -- the URL
    # alone authenticates nothing.
    secret: Mapped[str] = mapped_column(String(128), nullable=False)

    # Which event codes this endpoint wants. A JSON array rather than a join
    # table: the set is small, always read whole, and never queried *by*
    # event -- a table would add a join to every dispatch to answer a
    # question the row already answers.
    events: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    is_active: Mapped[bool] = bool_column(default=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_success_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False, nullable=True)
    last_failure_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False, nullable=True)
    last_failure_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = utc_datetime_column(default=True, nullable=False)
    updated_at: Mapped[Optional[datetime]] = utc_datetime_column(
        default=False, onupdate=True, nullable=True
    )

    deliveries: Mapped[List["WebhookDelivery"]] = relationship(
        back_populates="endpoint",
        cascade="all, delete-orphan",
        passive_deletes=True,
        # Never walked as a collection: the delivery log is paged through its
        # own endpoint, and a webhook with 50,000 attempts would otherwise be
        # loaded whole to render a name.
        lazy="raise",
    )

    __table_args__ = (
        UniqueConstraint("name", name="uq_webhook_endpoints_name"),
        Index("ix_webhook_endpoints_active", "is_active"),
    )


class WebhookDelivery(Base, PublicIdMixin):
    """One attempt to deliver one event to one endpoint.

    Kept even when it succeeds: "did the grade reach the finance system?" is
    asked far more often than it is planned for, and an attempt log that
    records only failures cannot answer it.
    """

    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    endpoint_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False
    )
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued",
        comment="queued, delivered, failed",
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    response_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Truncated, and deliberately not the whole body: a receiver's error page
    # can be a megabyte of HTML, and storing it turns a diagnostic column
    # into a storage problem.
    error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = utc_datetime_column(default=True, nullable=False)
    delivered_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False, nullable=True)
    next_attempt_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False, nullable=True)

    endpoint: Mapped["WebhookEndpoint"] = relationship(back_populates="deliveries", lazy="selectin")

    __table_args__ = (
        Index("ix_webhook_deliveries_endpoint_created", "endpoint_id", "created_at"),
        # The dispatcher's only query: what is due now.
        Index("ix_webhook_deliveries_pending", "status", "next_attempt_at"),
    )


class CalendarFeed(Base, PublicIdMixin):
    """A tokenised iCalendar subscription for one person's timetable.

    **A capability URL, and that is a deliberate trade.** Calendar clients
    cannot send an `Authorization` header, so the only way to serve a
    subscribable feed is to put the credential in the URL. That means the
    link *is* the credential: anyone holding it reads that person's
    timetable. Mitigated rather than pretended away -- the token is 32 random
    bytes, stored hashed so the table is not a list of working URLs, revocable
    in one click, and the feed exposes only session times and titles, never
    grades, messages or anything else the person can see in the product.
    """

    __tablename__ = "calendar_feeds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)

    is_active: Mapped[bool] = bool_column(default=True, nullable=False)
    created_at: Mapped[datetime] = utc_datetime_column(default=True, nullable=False)
    last_accessed_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False, nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    user: Mapped["User"] = relationship("User", lazy="selectin")

    __table_args__ = (
        Index("ix_calendar_feeds_user", "user_id"),
    )

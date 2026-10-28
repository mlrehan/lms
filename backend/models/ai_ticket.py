"""Confirmation tickets for consequential AI actions.

A ticket is the record that a person was shown a specific action -- composed by
the server, with its targets bound -- and may now confirm it. It lives in
Postgres rather than process memory for three reasons, each of which the
in-memory version failed:

* a restart discarded every pending confirmation;
* a second API process could not see a ticket the first had issued, so
  "yes" worked or failed depending on which process answered;
* "used exactly once" could only be enforced within one process. Here it is a
  row lock: two confirmations of one ticket serialise on the row, and the
  second finds it already consumed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, PublicIdMixin, TimestampMixin
from backend.models.helpers import bool_column


class AIConfirmationTicket(Base, TimestampMixin, PublicIdMixin):
    __tablename__ = "ai_confirmation_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # The opaque value handed to the client. Not secret on its own -- only the
    # actor who created a ticket may confirm it -- but unguessable regardless.
    ticket_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    action_name: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    actor_public_id: Mapped[str] = mapped_column(String(36), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    parameters_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    affected_records_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    preview_summary: Mapped[str] = mapped_column(Text, nullable=False)
    via_registry: Mapped[bool] = bool_column(default=False)
    # PENDING / CONFIRMED / CANCELLED. EXPIRED is derived from expires_at on
    # read, never written: a sweep that has to run for a ticket to expire is a
    # ticket that stays valid whenever the sweep does not.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED', 'CANCELLED')",
            name="status",
        ),
        Index("idx_ai_tickets_actor_status", "actor_user_id", "status"),
        Index("idx_ai_tickets_expires_at", "expires_at"),
    )

"""The institution's connection to Google Calendar.

One row per connection attempt that succeeded; at most one is `ACTIVE`, enforced by a
partial unique index rather than by remembering to deactivate the previous one. The refresh
token is stored encrypted (`security/token_cipher.py`) and is not exposed by any schema.
History is kept (a disconnected row becomes `REVOKED`, not deleted) so "who connected which
account, and when" stays answerable after the fact.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, PublicIdMixin

from .helpers import utc_datetime_column


class GoogleConnection(Base, PublicIdMixin):
    __tablename__ = "google_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_email: Mapped[str] = mapped_column(String(255), nullable=False)
    refresh_token_enc: Mapped[str] = mapped_column(Text, nullable=False, comment="AES-GCM; never serialised")
    scopes: Mapped[str] = mapped_column(Text, nullable=False, comment="Space-separated scopes actually granted")
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'ACTIVE'"), comment="ACTIVE | REVOKED | ERROR")
    connected_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    connected_at: Mapped[datetime] = utc_datetime_column(nullable=False)
    disconnected_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False)
    last_error: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    __table_args__ = (
        Index("ux_google_connections_one_active", text("(true)"), unique=True, postgresql_where=text("status = 'ACTIVE'")),
    )


class GoogleChangeRequest(Base, PublicIdMixin):
    """An enrolment change someone made in Google Calendar, waiting for a person to decide.

    A guest list edited in Google is a *proposal*. Google does not say who made the edit, and an
    enrolment carries a fee, a certificate and a grade book, so nothing is applied until an
    administrator approves it in the LMS -- where the ordinary enrolment rules (capacity, batch
    open, permissions, audit) apply exactly as if they had clicked Enrol themselves.
    """

    __tablename__ = "google_change_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey("batches.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False, comment="ENROL_ADD | ENROL_REMOVE")
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'PENDING'"))
    note: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    detected_at: Mapped[datetime] = utc_datetime_column(nullable=False)
    decided_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False)
    decided_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    __table_args__ = (
        Index("ux_google_change_requests_open", "batch_id", "email", "kind", unique=True, postgresql_where=text("status = 'PENDING'")),
    )

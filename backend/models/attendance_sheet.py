"""The register for one session, as a piece of work with a state -- and the trail of who did what to it.

`attendances` holds the truth (one row per student per session) and is what every report reads. A *sheet* is the
workflow around it:

* **DRAFT** -- a tutor has started marking. What they have marked so far lives on the sheet (`draft`), **not** in
  `attendances`, so an unfinished register can never skew an attendance percentage;
* **FINALIZED** -- submitted. The marks are written to `attendances` and the draft is cleared.

Every step that matters is an *event*: who started it, who submitted it, whether that was on behalf of the assigned
tutor, and every later edit with exactly which students changed from what to what. Events are only ever added.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, PublicIdMixin
from backend.models.helpers import bool_column, utc_datetime_column


class AttendanceSheet(Base, PublicIdMixin):
    __tablename__ = "attendance_sheets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("batch_sessions.id", ondelete="CASCADE"), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="DRAFT", comment="DRAFT or FINALIZED")

    # The tutor the session was assigned to when the register was started, kept even if the session is reassigned later.
    assigned_tutor_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    draft: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, comment="[{student_id, status, remarks}] while DRAFT")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = utc_datetime_column(default=True, nullable=False)
    updated_by_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False, onupdate=False, nullable=True)

    finalized_by_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    finalized_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False, onupdate=False, nullable=True)
    submitted_on_behalf: Mapped[bool] = bool_column(default=False, nullable=False)

    events: Mapped[List["AttendanceSheetEvent"]] = relationship(
        back_populates="sheet", cascade="all, delete-orphan", passive_deletes=True, lazy="raise", order_by="AttendanceSheetEvent.id"
    )

    __table_args__ = (CheckConstraint("status IN ('DRAFT', 'FINALIZED')", name="ck_attendance_sheets_status"),)


class AttendanceSheetEvent(Base):
    """One thing that happened to a sheet. Append-only."""

    __tablename__ = "attendance_sheet_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sheet_id: Mapped[int] = mapped_column(Integer, ForeignKey("attendance_sheets.id", ondelete="CASCADE"), nullable=False)
    action: Mapped[str] = mapped_column(String(12), nullable=False, comment="STARTED, FINALIZED or EDITED")
    actor_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    # Snapshotted at the time: who the session was assigned to, and whether the actor was somebody else.
    assigned_tutor_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    on_behalf: Mapped[bool] = bool_column(default=False, nullable=False)
    at: Mapped[datetime] = utc_datetime_column(default=True, nullable=False)
    changes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="counts, and for EDITED the students who changed")

    sheet: Mapped[AttendanceSheet] = relationship(back_populates="events")

    __table_args__ = (
        CheckConstraint("action IN ('STARTED', 'FINALIZED', 'EDITED')", name="ck_attendance_sheet_events_action"),
        Index("ix_attendance_sheet_events_sheet", "sheet_id", "id"),
    )

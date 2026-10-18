"""Today's classes, as the dashboard draws them."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field

from backend.schemas.base import APIModel


class TodayClass(APIModel):
    """One scheduled class, with everything the card shows and nothing more."""

    public_id: uuid.UUID
    course_title: str
    batch_code: str
    session_number: int | None = Field(
        default=None,
        description="Its position in its batch's own order, not a stored number.",
    )
    tutor_name: str | None = None
    enrolled: int = Field(default=0, description="Confirmed enrolments on the batch.")

    starts_at: datetime | None = None
    ends_at: datetime | None = None
    duration_minutes: int | None = None

    platform: str | None = Field(default=None, description="Zoom, Teams, a room, and so on.")
    classroom: str | None = None
    status: Literal["upcoming", "live", "ended", "cancelled"]

    has_meeting_link: bool = Field(
        description=(
            "Whether a door exists. The link itself is never in this payload: a "
            "listing is drawn for everyone who can see the class, and a link here "
            "would outlive the join window. Opening it is POST /sessions/{id}/join."
        )
    )
    join_opens_at: datetime | None = None
    join_closes_at: datetime | None = None
    can_join_now: bool = False


class TodayClasses(APIModel):
    """The day, named, so the reader can tell which day was meant."""

    timezone: str = Field(
        description=(
            "The zone the day was computed in -- the caller's own, or UTC when "
            "their profile has none or an unknown one."
        )
    )
    date: date
    classes: list[TodayClass] = Field(default_factory=list)

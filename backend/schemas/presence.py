"""What the active-users view returns."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from backend.schemas.base import APIModel, Page


class ActiveUserRow(APIModel):
    """One person, and when they were last actually here."""

    public_id: uuid.UUID
    name: str
    roles: list[str] = Field(default_factory=list)
    online: bool = Field(description="A browser is holding its realtime connection open now.")
    location: str | None = Field(
        default=None,
        description=(
            "From the person's own profile, where they have filled it in. Never "
            "derived from an IP address: that would tell an administrator where a "
            "colleague is sitting, which nobody consented to."
        ),
    )
    last_seen_at: datetime | None = Field(
        default=None, description="Last heartbeat. Absent when they are not online."
    )
    last_login_at: datetime | None = None


class PresenceSummary(APIModel):
    """The counts, and a page of the people behind them."""

    online: int = Field(description="How many people are connected right now.")
    total: int = Field(description="How many rows match the requested filter.")
    window_seconds: int = Field(
        description=(
            "How long after its last heartbeat an entry still counts as online. "
            "Somebody who closed their laptop drops out after this, without "
            "anything having to notice they left."
        )
    )
    realtime_enabled: bool = Field(
        description=(
            "False when the realtime stream is switched off for this deployment, "
            "in which case nobody can be reported online and the figure is not a "
            "claim that nobody is working."
        )
    )
    users: Page[ActiveUserRow]

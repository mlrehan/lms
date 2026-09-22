"""When a class may be joined.

The rule is simple -- the door opens thirty minutes before the start and closes
at the end -- but *where* it is enforced is the whole design. Sending the meeting
link to the browser and greying out a button enforces nothing: the link is in the
network response, and anyone who opens devtools is in the room early, or in a room
they never attended. So the link is withheld by the API until the window is open,
and this module is the single place that decides whether it is.

Pure functions over explicit times, so the window can be tested without freezing
a clock and every caller asks the same question in the same words.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

#: How early the door opens. Long enough to arrive, settle and fix a headset;
#: short enough that "the link works" is not a synonym for "the link is public".
JOIN_OPENS_BEFORE = timedelta(minutes=30)

#: Used only when a session records no end time and no duration. A class with no
#: stated length still has to stop being joinable at some point, and two hours is
#: longer than any session this platform schedules.
FALLBACK_DURATION = timedelta(hours=2)


@dataclass(frozen=True)
class JoinWindow:
    """The interval during which a session's meeting link may be handed out."""

    opens_at: datetime
    closes_at: datetime

    def contains(self, moment: datetime) -> bool:
        return self.opens_at <= moment <= self.closes_at


def join_window(
    start: datetime | None,
    end: datetime | None = None,
    *,
    duration_minutes: int | None = None,
) -> JoinWindow | None:
    """The window for a session, or `None` when it has no start time at all.

    `end` wins over `duration_minutes` when both are present: a stored end time is
    what the calendar and the tutor agreed on, whereas a duration is a property of
    the batch that may not match this particular session.
    """
    if start is None:
        return None

    if end is not None:
        closes = end
    elif duration_minutes:
        closes = start + timedelta(minutes=duration_minutes)
    else:
        closes = start + FALLBACK_DURATION

    # A session whose end is recorded before its start is bad data, not a reason
    # to leave the door open forever.
    if closes < start:
        closes = start + FALLBACK_DURATION

    return JoinWindow(opens_at=start - JOIN_OPENS_BEFORE, closes_at=closes)


def is_open(
    now: datetime,
    start: datetime | None,
    end: datetime | None = None,
    *,
    duration_minutes: int | None = None,
) -> bool:
    window = join_window(start, end, duration_minutes=duration_minutes)
    return window is not None and window.contains(now)

"""Working out a batch's sessions from how it is scheduled -- pure functions, no database.

Given weekdays, a start time, a duration, a date range, a session count and *a time zone*, produce the sessions
(as UTC instants) so an administrator reviews and adjusts a proposal instead of typing each class in.

The time zone matters more than it looks. "Monday 10:00" means a different instant in London than in Dhaka, and a
weekday can itself differ (a Monday 23:00 London class is Tuesday 04:00 in Dhaka). So the plan is built entirely
in the *chosen* zone -- dates, weekdays and clock times are all read there -- and only converted to UTC at the end.
A batch that stores its clock time in another zone has that time carried across for the first class, so the same
instant is proposed rather than the same number on the clock.

Daylight saving: a local time that does not exist (the hour skipped in spring) resolves to the offset before the
change, and one that occurs twice (autumn) to its first occurrence -- deterministic, never an error. The preview
shows every session's local time, so a shifted one is visible before anything is saved.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.integrations.lait_academic import parse_training_days

MAX_SESSIONS = 200
MIN_MINUTES, MAX_MINUTES = 5, 24 * 60
_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class PlanError(ValueError):
    """The inputs cannot make a plan at all (an unknown zone, say). Anything merely odd is a warning instead."""


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise PlanError(f"Unknown time zone: {name!r}.") from None


def local_to_utc(day: date, clock: time, tz: str) -> datetime:
    return datetime.combine(day, clock).replace(tzinfo=zone(tz)).astimezone(timezone.utc)


def utc_to_local(instant: datetime, tz: str) -> datetime:
    aware = instant if instant.tzinfo else instant.replace(tzinfo=timezone.utc)
    return aware.astimezone(zone(tz))


def weekday_name(index: int) -> str:
    return _WEEKDAY_NAMES[index % 7]


def weekdays_from_text(text: str | None) -> tuple[list[int], int | None]:
    """`"Monday & Friday"` -> ([0, 4], None); `"5 Thursdays"` -> ([3], 5). Empty when it cannot be understood."""
    pattern = parse_training_days(text)
    return list(pattern.weekdays), pattern.weekly_count


def weekdays_to_text(weekdays: Sequence[int]) -> str:
    names = [weekday_name(d) for d in sorted(set(weekdays))]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " & " + names[-1] if names else ""


@dataclass(frozen=True)
class Carried:
    clock: time
    weekdays: list[int]
    day_shift: int


def carry_schedule(clock: time, weekdays: Sequence[int], *, from_tz: str, to_tz: str, on: date) -> Carried:
    """The same classes, read in another zone: the wall-clock time, and the weekdays, as they are in `to_tz`.

    A Monday 23:00 class in London is Tuesday 04:00 in Dhaka, so carrying only the clock would propose Monday 04:00,
    a different instant entirely. `on` is the reference date (the first class); the day shift found there is applied
    to every weekday.
    """
    local = utc_to_local(local_to_utc(on, clock, from_tz), to_tz)
    shift = (local.date() - on).days
    return Carried(local.time().replace(second=0, microsecond=0), sorted({(d + shift) % 7 for d in weekdays}), shift)


@dataclass
class PlanSettings:
    timezone: str
    weekdays: list[int]
    start_time: time | None
    duration_minutes: int | None
    start_date: date | None
    end_date: date | None
    sessions: int | None = None
    weekly_count: int | None = None  # "5 Thursdays": that many weekly classes, whatever the end date says


@dataclass
class PlannedSession:
    index: int
    start_utc: datetime
    end_utc: datetime
    duration_minutes: int
    start_local: datetime | None = None


def plan_sessions(s: PlanSettings) -> tuple[list[PlannedSession], list[str]]:
    """The proposed sessions, in date order, and a warning for anything that did not add up."""
    warnings: list[str] = []
    tz = zone(s.timezone)

    if s.start_time is None:
        return [], ["Set a start time to generate sessions."]
    if not s.duration_minutes or not (MIN_MINUTES <= s.duration_minutes <= MAX_MINUTES):
        return [], ["Set a class duration between 5 minutes and 24 hours to generate sessions."]
    if s.start_date is None:
        return [], ["Set a start date to generate sessions."]
    if not s.weekdays:
        return [], ["Choose the days classes are held on to generate sessions."]

    wanted = s.sessions if s.sessions and s.sessions > 0 else None
    # "5 Thursdays" states the count itself, so the end date does not cut it short.
    weekly = bool(s.weekly_count and len(s.weekdays) == 1)
    if weekly:
        wanted = s.weekly_count
    end_date = None if weekly else s.end_date
    if wanted and wanted > MAX_SESSIONS:
        warnings.append(f"Only the first {MAX_SESSIONS} sessions are generated.")
        wanted = MAX_SESSIONS

    if end_date is not None and end_date < s.start_date:
        return [], ["The end date is before the start date."]

    horizon = end_date
    # With a count but no end date, walk forward until the count is met (a year at most, so it always stops).
    if horizon is None:
        if wanted is None:
            return [], ["Set an end date or a number of sessions to generate sessions."]
        horizon = s.start_date + timedelta(days=366)

    dates: list[date] = []
    day = s.start_date
    while day <= horizon and len(dates) < MAX_SESSIONS:
        if day.weekday() in s.weekdays:
            dates.append(day)
            if wanted and len(dates) >= wanted and end_date is None:
                break
        day += timedelta(days=1)

    if wanted:
        if len(dates) > wanted:
            dates = dates[:wanted]
        elif len(dates) < wanted:
            warnings.append(
                f"The dates give {len(dates)} session{'s' if len(dates) != 1 else ''} but {wanted} were asked for. "
                "Extend the end date, or add the rest by hand."
            )

    planned: list[PlannedSession] = []
    for i, d in enumerate(dates, start=1):
        start_local = datetime.combine(d, s.start_time).replace(tzinfo=tz)
        start_utc = start_local.astimezone(timezone.utc)
        # A wall-clock time that did not exist (spring forward) is shifted by the conversion; say so.
        if start_utc.astimezone(tz).replace(tzinfo=None) != start_local.replace(tzinfo=None):
            warnings.append(f"{d.isoformat()}: {s.start_time.strftime('%H:%M')} does not exist in {s.timezone} that day (clocks change); it was moved.")
        planned.append(PlannedSession(i, start_utc, start_utc + timedelta(minutes=s.duration_minutes), s.duration_minutes, start_utc.astimezone(tz)))
    return planned, warnings


@dataclass
class Inferred:
    weekdays: list[int]
    start_time: time | None
    duration_minutes: int | None
    count: int


def infer_from_sessions(sessions: Sequence[tuple[datetime, datetime | None]], tz: str) -> Inferred:
    """What existing sessions imply about the schedule, read in `tz`: their weekdays, most common start and length."""
    local = [(utc_to_local(a, tz), b) for a, b in sessions]
    weekdays = sorted({a.weekday() for a, _ in local})
    starts = Counter(a.time().replace(second=0, microsecond=0) for a, _ in local)
    lengths = Counter(int((b - a.astimezone(timezone.utc)).total_seconds() // 60) for a, b in local if b is not None)
    return Inferred(
        weekdays=weekdays,
        start_time=starts.most_common(1)[0][0] if starts else None,
        duration_minutes=lengths.most_common(1)[0][0] if lengths else None,
        count=len(local),
    )

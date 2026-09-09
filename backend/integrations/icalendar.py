"""Minimal RFC 5545 output for timetable feeds.

Hand-written rather than pulled from a library, because the requirement is
one VEVENT shape with no recurrence, no timezones beyond UTC and no
attachments — and the two things that actually break calendar clients are
line folding and escaping, both of which are twenty lines.

**Everything here is about what a client will silently refuse.** A `.ics`
that Google Calendar rejects gives the user no error at all; the subscription
simply stays empty. So: CRLF line endings (not LF), 75-octet folding, the
five escaped characters, and a `UID` that is stable across polls — an unstable
UID makes every refresh delete and recreate every event, which clients show
as a wall of notifications.
"""

from __future__ import annotations

from datetime import datetime, timezone

PRODID = "-//LMS Platform//Timetable//EN"
MAX_LINE_OCTETS = 75


def _escape(text: str) -> str:
    """RFC 5545 §3.3.11. Backslash first, or it re-escapes its own output."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
        .replace("\r", "")
    )


def _fold(line: str) -> list[str]:
    """Fold to 75 **octets**, not characters.

    The distinction is the whole point: a course title with an accented
    letter is two octets in UTF-8, so folding on character count produces
    lines that are over the limit — and a split landing mid-sequence emits
    invalid UTF-8, which some clients reject outright.
    """
    raw = line.encode("utf-8")
    if len(raw) <= MAX_LINE_OCTETS:
        return [line]

    chunks: list[str] = []
    start = 0
    limit = MAX_LINE_OCTETS
    while start < len(raw):
        end = min(start + limit, len(raw))
        # Back off until the slice is a whole character.
        while end > start:
            try:
                chunk = raw[start:end].decode("utf-8")
                break
            except UnicodeDecodeError:
                end -= 1
        else:  # pragma: no cover - unreachable for valid input
            raise ValueError("Cannot fold line")
        chunks.append(chunk if not chunks else " " + chunk)
        start = end
        limit = MAX_LINE_OCTETS - 1  # continuation lines carry a leading space
    return chunks


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_calendar(
    *,
    name: str,
    events: list[dict],
    generated_at: datetime | None = None,
) -> str:
    """Serialise a timetable. Each event needs uid/start/end/summary."""
    now = generated_at or datetime.now(timezone.utc)
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
    ]

    for event in events:
        lines.extend(
            [
                "BEGIN:VEVENT",
                # Stable across polls: derived from the session's own public
                # id, so a refresh updates events instead of replacing them.
                f"UID:{event['uid']}",
                f"DTSTAMP:{_stamp(now)}",
                f"DTSTART:{_stamp(event['start'])}",
                f"DTEND:{_stamp(event['end'])}",
                f"SUMMARY:{_escape(event['summary'])}",
            ]
        )
        if event.get("description"):
            lines.append(f"DESCRIPTION:{_escape(event['description'])}")
        if event.get("location"):
            lines.append(f"LOCATION:{_escape(event['location'])}")
        if event.get("url"):
            lines.append(f"URL:{_escape(event['url'])}")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")

    folded: list[str] = []
    for line in lines:
        folded.extend(_fold(line))
    # CRLF, per the spec. Some clients tolerate bare LF; the ones that do not
    # fail with an empty calendar and no message.
    return "\r\n".join(folded) + "\r\n"

"""What the LMS writes to Google Calendar. Pure: no I/O, no database, no HTTP.

Every choice about what a guest can see or do is made here, in one place, so it is testable:

* **Guests cannot see each other** (`guestsCanSeeOtherGuests=False`). A batch calendar lists
  students, their guardians and their employers' managers; letting each of them read that
  list would publish everyone's email address to everyone else.
* **Guests cannot edit the event or invite others.** The LMS is the source of truth for the
  schedule; a guest who could move a class or add a stranger would be a back door around it.
* **Reminders are popups only.** Email reminders would send mail to real people on the LMS's
  behalf from the moment the first event is created.
* **Internal notes never leave the LMS.** `tutor_notes` is not an input to any function here.
* **Times are UTC**, converted from what the LMS stores, so an event is unambiguous whatever
  timezone the viewer's calendar uses.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

MANAGED_KEY = "lms_managed"
SESSION_KEY = "lms_session_id"
BATCH_KEY = "lms_batch_code"

_EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
_ROLE_ORDER = {"tutor": 0, "student": 1, "guardian": 2, "manager": 3}


@dataclass(frozen=True)
class Guest:
    email: str
    name: str | None
    role: str  # tutor | student | guardian | manager


@dataclass(frozen=True)
class BatchView:
    code: str
    course_title: str
    is_active: bool
    start_date: date | None
    end_date: date | None
    delivery: str | None = None


@dataclass(frozen=True)
class SessionView:
    public_id: str
    number: int
    total: int
    start_utc: datetime
    end_utc: datetime
    tutor_name: str | None
    platform: str | None
    meeting_link: str | None
    classroom: str | None
    student_notes: str | None


# ------------------------------------------------- how the institution writes it

_PLATFORM_LABELS = {
    "Zoom": "Zoom Video Conferencing",
    "Google_Meet": "Google Meet",
    "Microsoft_Teams": "Microsoft Teams",
    "Zoho": "Zoho Meeting",
    "Classroom": "Classroom",
}


def platform_label(platform: str | None) -> str:
    return _PLATFORM_LABELS.get(platform or "", "Online")


def parse_location(location: str | None) -> tuple[str | None, str | None]:
    """The inverse of the above, for an event an administrator typed in Google.

    Returns `(platform, classroom)`. A recognised online label gives the platform and no
    classroom; any other text is a physical address, so the session is a `Classroom` one and the
    text is kept as its classroom. Nothing typed is thrown away.
    """
    text = (location or "").strip()
    lowered = text.lower()
    if not text:
        return None, None
    for platform, label in _PLATFORM_LABELS.items():
        if platform != "Classroom" and label.lower() in lowered:
            return platform, None
    for needle, platform in (("zoom", "Zoom"), ("teams", "Microsoft_Teams"), ("google meet", "Google_Meet"), ("meet.google", "Google_Meet"), ("zoho", "Zoho")):
        if needle in lowered:
            return platform, None
    return "Classroom", text[:500]


_CANCEL_RE = re.compile(r"^\s*[\[(]?\s*(cancel(?:l?ed)?)\b", re.IGNORECASE)


def is_cancel_title(summary: str | None) -> bool:
    """`CANCEL`, `Cancelled - ...`, `[CANCELED] ...`: an explicit request to cancel the class."""
    return bool(_CANCEL_RE.match(summary or ""))


REJECTED_KEY = "lms_rejected"


def event_signature(event: dict[str, Any]) -> str:
    """What a person typed into an event (title, place, time). A rejected event is left alone
    until this changes, so a fixed event is reconsidered and an unfixed one is not re-reported
    on every run."""
    material = json.dumps([event.get("summary"), event.get("location"), event.get("start"), event.get("end")], sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ guests


def valid_email(value: str | None) -> bool:
    return bool(value) and len(value or "") <= 254 and bool(_EMAIL_RE.match(value or ""))


def dedupe_guests(guests: list[Guest], cap: int) -> tuple[list[Guest], int]:
    """One entry per email (case-insensitive), invalid addresses dropped, tutors first.

    A person can be several things at once -- a tutor who is also a guardian -- and Google
    rejects a repeated guest, so the most senior role wins. Returns the kept guests and how
    many were dropped for exceeding `cap` (Google's limit), so the caller can report it
    rather than silently leaving people off a class.
    """
    best: dict[str, Guest] = {}
    for g in guests:
        if not valid_email(g.email):
            continue
        key = g.email.strip().lower()
        current = best.get(key)
        if current is None or _ROLE_ORDER.get(g.role, 9) < _ROLE_ORDER.get(current.role, 9):
            best[key] = Guest(email=key, name=g.name, role=g.role)
    ordered = sorted(best.values(), key=lambda g: (_ROLE_ORDER.get(g.role, 9), g.email))
    return ordered[:cap], max(0, len(ordered) - cap)


# ---------------------------------------------------------------- calendars


def calendar_title(batch: BatchView) -> str:
    return f"{batch.course_title} ({batch.code})" + ("" if batch.is_active else " [Closed]")


def build_calendar_body(batch: BatchView, timezone_name: str) -> dict[str, Any]:
    def fmt(d: date | None) -> str:
        return d.strftime("%d %b %Y") if d else "TBC"

    lines = [f"Batch {batch.code} of {batch.course_title}.", f"{fmt(batch.start_date)} to {fmt(batch.end_date)}."]
    if batch.delivery:
        lines.append(f"Delivery: {batch.delivery}.")
    lines.append("Managed by the LMS. Edit session times here or in the LMS; enrolments are managed in the LMS.")
    return {"summary": calendar_title(batch)[:255], "description": "\n".join(lines), "timeZone": timezone_name}


# ------------------------------------------------------------------- events


def iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_google_datetime(node: dict[str, Any] | None) -> datetime | None:
    """A Google `start`/`end` node -> aware UTC datetime. All-day events (`date`) are not sessions."""
    if not node or "dateTime" not in node:
        return None
    try:
        parsed = datetime.fromisoformat(str(node["dateTime"]).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def build_event_body(session: SessionView, batch: BatchView, guests: list[Guest], *, invite: bool) -> dict[str, Any]:
    lines = [f"Session {session.number} of {session.total}", f"Batch {batch.code}"]
    if session.tutor_name:
        lines.append(f"Tutor: {session.tutor_name}")
    if session.platform:
        lines.append(f"Delivery: {session.platform.replace('_', ' ')}")
    if session.meeting_link:
        lines.append(f"Join: {session.meeting_link}")
    if session.student_notes:
        lines += ["", session.student_notes.strip()]
    lines += ["", "Managed by the LMS."]

    location = session.classroom or platform_label(session.platform)

    body: dict[str, Any] = {
        "summary": f"{batch.course_title} ({batch.code})"[:1024],
        "description": "\n".join(lines),
        "location": location[:1024],
        "start": {"dateTime": iso_utc(session.start_utc), "timeZone": "UTC"},
        "end": {"dateTime": iso_utc(session.end_utc), "timeZone": "UTC"},
        "guestsCanModify": False,
        "guestsCanInviteOthers": False,
        "guestsCanSeeOtherGuests": False,
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 30}]},
        "extendedProperties": {"private": {MANAGED_KEY: "1", SESSION_KEY: session.public_id, BATCH_KEY: batch.code}},
    }
    if invite:
        body["attendees"] = [
            {"email": g.email, **({"displayName": g.name[:100]} if g.name else {})} for g in guests
        ]
    return body


def body_hash(body: dict[str, Any]) -> str:
    """A digest of what would be sent: equal digests mean there is nothing to push."""
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def guest_emails(event: dict[str, Any]) -> set[str]:
    """Guests on a fetched event, excluding the organiser's own entry."""
    return {
        str(a.get("email", "")).lower()
        for a in event.get("attendees", []) or []
        if a.get("email") and not a.get("organizer") and not a.get("self")
    }


def calendar_url(calendar_id: str) -> str:
    import base64

    token = base64.urlsafe_b64encode(calendar_id.encode()).decode().rstrip("=")
    return f"https://calendar.google.com/calendar/u/0/r?cid={token}"

"""Pure mapping from LAIT payloads to LMS user fields.

No I/O and no database: everything here takes a dict and returns a value, so
every rule can be tested directly. What needs a database (matching a country,
finding an existing account) lives in `lait_geo.py` and the sync service.

Rules that are easy to get subtly wrong, and why they are written as they are:

* **Roles come from an allowlist, and `ADMIN` / `SUPER_ADMIN` are not in it.**
  The sync is driven by an external system's payload. Whatever that payload
  says, the most it can ever grant is `SYNC_GRANTABLE_ROLES`; an unrecognised
  role string is recorded and skipped, never guessed at. The service asserts
  this again immediately before assigning, so the guarantee does not depend on
  this module being the only caller.
* **`RegistrationDate` is naive UK local time** and is converted to UTC.
  Autumn's repeated hour resolves to its first occurrence (`fold=0`) and
  spring's skipped hour to the offset before the change -- both deterministic,
  neither an error.
* **Nothing is truncated silently.** A value that does not fit its column is
  shortened *and* reported, so a mangled name is a visible warning on the run
  rather than a surprise on a certificate.
* **`web` is sanitised to http(s).** It is rendered as a link in places, and a
  stored `javascript:` URL is a script-execution vector on a page that shows
  someone else's profile.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from slugify import slugify

# =============================================================================
# LIMITS -- mirror the `users` column widths (see models/identity/user.py)
# =============================================================================
LIMITS = {
    "username": 50,
    "email": 255,
    "first_name": 50,
    "last_name": 50,
    "title": 20,
    "phone_number": 75,
    "company": 255,
    "web": 255,
    "postcode": 35,
    "ip_address": 45,
}

# What the sync is capable of granting. Deliberately excludes ADMIN and
# SUPER_ADMIN -- see the module docstring.
SYNC_GRANTABLE_ROLES = frozenset({"STUDENT", "TUTOR", "CORPORATE_MANAGER", "GUARDIAN"})

_ROLE_ALLOWLIST = {
    "student": "STUDENT",
    "tutor": "TUTOR",
    "corporatemanager": "CORPORATE_MANAGER",
    "guardian": "GUARDIAN",
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SPACE_RE = re.compile(r"\s+")


class MappingError(Exception):
    """A payload cannot be turned into a usable account. The message is safe to
    store and show: it never contains a value from the payload."""


@dataclass
class MappedUser:
    guid: uuid.UUID
    source: str  # "student" | "tutor"

    username: str | None = None
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    phone_number: str | None = None
    company: str | None = None
    address: str | None = None
    postcode: str | None = None
    web: str | None = None
    ip_address: str | None = None

    # Raw geography, resolved against the reference tables later.
    country_name: str | None = None
    city_name: str | None = None

    registered_at: datetime | None = None  # UTC
    roles: list[str] = field(default_factory=list)
    is_public: bool | None = None
    external_student_id: int | None = None
    external_tutor_id: int | None = None

    warnings: list[str] = field(default_factory=list)
    unknown_roles: list[str] = field(default_factory=list)


# =============================================================================
# PRIMITIVES
# =============================================================================


def clean(value: Any) -> str | None:
    """Trim, drop control characters, collapse runs of whitespace; empty -> None."""
    if value is None:
        return None
    text = _SPACE_RE.sub(" ", _CONTROL_RE.sub(" ", str(value))).strip()
    return text or None


def fit(value: str | None, field_name: str, warnings: list[str]) -> str | None:
    """Shorten to the column width, reporting that it happened."""
    if value is None:
        return None
    limit = LIMITS[field_name]
    if len(value) <= limit:
        return value
    warnings.append(f"{field_name} truncated from {len(value)} to {limit} characters")
    return value[:limit].rstrip()


def join_address(*parts: Any) -> str | None:
    """AddressLine1 + AddressLine2 + AddressLine3, skipping empty lines."""
    lines = [c for c in (clean(p) for p in parts) if c]
    return ", ".join(lines) if lines else None


def normalise_email(value: Any) -> str | None:
    """Lower-cased and shape-checked. Lenient on purpose: this is real-world
    data, and a stricter check would reject addresses the mail system accepts."""
    text = clean(value)
    if text is None:
        return None
    text = text.lower()
    return text if _EMAIL_RE.match(text) and len(text) <= LIMITS["email"] else None


def safe_web(value: Any, warnings: list[str]) -> str | None:
    text = clean(value)
    if text is None:
        return None
    lowered = text.lower()
    if lowered.startswith(("http://", "https://")):
        return fit(text, "web", warnings)
    # "example.com" -> "https://example.com"; anything with another scheme
    # (javascript:, data:, ftp:) or that is not domain-shaped is dropped.
    if re.match(r"^[a-z0-9.-]+\.[a-z]{2,}(/\S*)?$", lowered):
        return fit("https://" + text, "web", warnings)
    warnings.append("web dropped: not an http(s) URL")
    return None


def parse_guid(value: Any) -> uuid.UUID:
    try:
        return uuid.UUID(str(value).strip())
    except (ValueError, AttributeError, TypeError):
        raise MappingError("missing or invalid GUID") from None


def parse_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and str(value).strip() != "" else None
    except (ValueError, TypeError):
        return None


def parse_registered_at(value: Any, source_timezone: str) -> datetime | None:
    """LAIT's naive local timestamp -> an aware UTC datetime.

    A value that already carries an offset is trusted and converted directly.
    """
    text = clean(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(source_timezone))
    return parsed.astimezone(timezone.utc)


def map_roles(names: Iterable[Any] | None) -> tuple[list[str], list[str]]:
    """LAIT role names -> (LMS role names, unrecognised names).

    Matching ignores case, spaces and underscores, so `CorporateManager`,
    `corporate_manager` and `Corporate Manager` are one role. Anything outside
    the allowlist -- including any spelling of an administrator -- is returned
    in the second list and granted nothing.
    """
    granted: list[str] = []
    unknown: list[str] = []
    for raw in names or []:
        key = re.sub(r"[\s_\-]", "", str(raw)).lower()
        role = _ROLE_ALLOWLIST.get(key)
        if role is None:
            unknown.append(str(raw)[:40])
        elif role not in granted:
            granted.append(role)
    assert set(granted) <= SYNC_GRANTABLE_ROLES  # the allowlist itself must never widen
    return granted, unknown


# =============================================================================
# SLUGS AND USERNAMES
# =============================================================================


def slug_base(first: str | None, last: str | None, username: str | None) -> str:
    """The readable part of a slug: the person's name, not their email.

    The previous generator slugified the username, which for these accounts is
    an email address -- `katie-suleiman-gmail-com` in every profile URL.
    """
    name = " ".join(p for p in (first, last) if p)
    base = slugify(name, max_length=80, lowercase=True, separator="-")
    if not base and username:
        base = slugify(username.split("@")[0], max_length=80, lowercase=True, separator="-")
    return base or "user"


def slug_with_suffix(base: str, guid: uuid.UUID) -> str:
    """Disambiguation that needs no lookup: six hex characters of the GUID.

    Deterministic and independent of insertion order, and free of the
    check-then-insert race a counter suffix has -- two workers picking `-2`
    at once is exactly what a unique index then has to catch.
    """
    return f"{base[:80]}-{guid.hex[:6]}"


def fallback_username(first: str | None, last: str | None) -> str | None:
    """`first.last`, for a tutor whose payload carries no email at all."""
    parts = [slugify(p, lowercase=True, separator="") for p in (first, last) if p]
    parts = [p for p in parts if p]
    if not parts:
        return None
    return ".".join(parts)[: LIMITS["username"] - 8]


def username_problem(username: str | None) -> str | None:
    if not username:
        return "no username or email available"
    if len(username) > LIMITS["username"]:
        return f"username is {len(username)} characters; the limit is {LIMITS['username']}"
    if re.search(r"\s", username):
        return "username contains whitespace"
    return None


# =============================================================================
# PAYLOAD MAPPERS
# =============================================================================


def map_student(payload: dict[str, Any], *, source_timezone: str) -> MappedUser:
    guid = parse_guid(payload.get("UserID"))
    mapped = MappedUser(guid=guid, source="student")
    warnings = mapped.warnings

    mapped.external_student_id = parse_int(payload.get("StudentID"))

    email = normalise_email(payload.get("Email"))
    if email is None and clean(payload.get("Email")):
        warnings.append("email is not a valid address and was ignored")
    mapped.email = email

    # LAIT's UserName is the email address in every record observed; either
    # is accepted so a record carrying only one is still usable.
    username = clean(payload.get("UserName")) or email
    mapped.username = username.lower() if username else None

    mapped.title = fit(clean(payload.get("Title")), "title", warnings)
    mapped.first_name = fit(clean(payload.get("FirstName")), "first_name", warnings)
    mapped.last_name = fit(clean(payload.get("LastName")), "last_name", warnings)
    mapped.company = fit(clean(payload.get("CompanyName")), "company", warnings)
    mapped.address = join_address(
        payload.get("AddressLine1"), payload.get("AddressLine2"), payload.get("AddressLine3")
    )
    mapped.postcode = fit(clean(payload.get("PostCode")), "postcode", warnings)
    mapped.phone_number = fit(clean(payload.get("ContactNumber")), "phone_number", warnings)
    mapped.ip_address = fit(clean(payload.get("UserIP")), "ip_address", warnings)
    mapped.web = safe_web(payload.get("Website"), warnings)

    mapped.country_name = clean(payload.get("CountryName"))
    mapped.city_name = clean(payload.get("City"))
    # StateProvinceCounty and CountryID are deliberately not read.

    mapped.registered_at = parse_registered_at(payload.get("RegistrationDate"), source_timezone)
    if clean(payload.get("RegistrationDate")) and mapped.registered_at is None:
        warnings.append("RegistrationDate could not be parsed and was ignored")

    mapped.roles, mapped.unknown_roles = map_roles(payload.get("Roles"))
    return mapped


def map_tutor(payload: dict[str, Any]) -> MappedUser:
    guid = parse_guid(payload.get("user_id"))
    mapped = MappedUser(guid=guid, source="tutor")
    warnings = mapped.warnings

    mapped.external_tutor_id = parse_int(payload.get("tutor_id"))
    mapped.title = fit(clean(payload.get("title")), "title", warnings)
    mapped.first_name = fit(clean(payload.get("first_name")), "first_name", warnings)

    # LAIT keeps the middle name separately; we have no column for it, so it
    # is placed in front of the surname ("Abul Bashar Sardar"-style names).
    last = " ".join(p for p in (clean(payload.get("middle_name")), clean(payload.get("last_name"))) if p)
    mapped.last_name = fit(last or None, "last_name", warnings)

    is_public = payload.get("is_public")
    mapped.is_public = is_public if isinstance(is_public, bool) else None

    # Presence in the tutor feed is what makes someone a TUTOR; the payload has no roles.
    mapped.roles = ["TUTOR"]
    return mapped


def apply_tutor_detail(mapped: MappedUser, detail: dict[str, Any] | None) -> None:
    """The tutor list carries no email; the per-tutor endpoint does (`email_id`).

    LAIT uses the email as the username for students, so a tutor gets the same
    treatment when one is available.
    """
    if not detail:
        return
    email = normalise_email(detail.get("email_id"))
    if email:
        mapped.email = email
        mapped.username = email

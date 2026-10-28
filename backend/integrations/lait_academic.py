"""Pure logic for the LAIT course / batch / session / enrolment sync.

No I/O and no database, so every rule here is testable directly.

Time: the LAIT API sends *naive UK local time* (`2026-09-21T10:00:00`, "10:00 AM").
Everything is converted to UTC before it is stored. The conversion goes through
`zoneinfo`, so British Summer Time is honoured: 10:00 on 21 September is 09:00
UTC, while 10:00 on 21 January is 10:00 UTC. A fixed "-1 hour" would be right for
half the year.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from backend.integrations.lait_mapping import MappingError, clean, fit, parse_guid, parse_int

# =============================================================================
# TIME
# =============================================================================

_CLOCK_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*([AaPp][Mm])?\s*$")


def parse_clock(value: Any) -> time | None:
    """`"10:00 AM"` / `"04:00 PM"` / `"16:00"` -> a time, or None."""
    m = _CLOCK_RE.match(str(value or ""))
    if not m:
        return None
    hour, minute, meridiem = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower()
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def uk_to_utc(local: datetime, source_timezone: str) -> datetime:
    """A naive UK wall-clock datetime -> aware UTC.

    The repeated hour when clocks go back resolves to its first occurrence
    (`fold=0`) and the skipped hour when they go forward to the offset before
    the change: deterministic, and neither an error.
    """
    if local.tzinfo is not None:
        return local.astimezone(timezone.utc)
    return local.replace(tzinfo=ZoneInfo(source_timezone)).astimezone(timezone.utc)


def parse_money(value: Any) -> float | None:
    """A fee as a non-negative number, or None."""
    try:
        amount = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return amount if amount >= 0 else None


def parse_local_datetime(value: Any) -> datetime | None:
    text = clean(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError:
        return None


# =============================================================================
# TRAINING DAYS  ->  SESSION DATES
# =============================================================================

_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_WORD_RE = re.compile(r"[A-Za-z]+")


@dataclass
class DayPattern:
    weekdays: list[int] = field(default_factory=list)  # 0 = Monday
    weekly_count: int | None = None  # "5 Thursdays" -> 5 sessions, a week apart


_DAY_WORDS: dict[str, int] = {}
for _i, _names in enumerate([
    ("mon", "monday"), ("tue", "tues", "tuesday"), ("wed", "weds", "wednesday"),
    ("thu", "thur", "thurs", "thursday"), ("fri", "friday"), ("sat", "saturday"), ("sun", "sunday"),
]):
    for _n in _names:
        _DAY_WORDS[_n] = _i
        _DAY_WORDS[_n + "s"] = _i  # "Sundays"


def _weekday_of(word: str) -> int | None:
    return _DAY_WORDS.get(word.lower())


def parse_training_days(text: Any) -> DayPattern:
    """Understands the forms LAIT actually emits:

    `Monday & Friday`, `Mon, Wed & Fri (2 wks)`, `Thursday`, `2 Sundays`,
    `5 Thursdays`, `Thursday to Friday` (an inclusive range), plus `weekdays`
    and `weekend`. Anything else yields an empty pattern; the caller reports it.
    """
    raw = clean(text) or ""
    lowered = raw.lower()
    pattern = DayPattern()

    if "weekend" in lowered:
        pattern.weekdays = [5, 6]
        return pattern
    if re.search(r"\bweekdays?\b", lowered):
        pattern.weekdays = [0, 1, 2, 3, 4]
        return pattern

    # "(2 wks)" is a duration hint, not a session count; strip it before looking for a leading count.
    without_hint = re.sub(r"\(\s*\d+\s*w(?:ee)?ks?\s*\)", " ", lowered)
    count = re.match(r"^\s*(\d+)\s+[a-z]", without_hint)

    tokens: list[tuple[str, int]] = []
    for word in _WORD_RE.findall(without_hint):
        day = _weekday_of(word)
        if day is not None:
            tokens.append((word, day))
    if not tokens:
        return pattern

    if re.search(r"\bto\b|\bthrough\b|\bthru\b", without_hint) and len(tokens) == 2:
        first, last = tokens[0][1], tokens[1][1]
        span = (last - first) % 7
        pattern.weekdays = [(first + i) % 7 for i in range(span + 1)]
        return pattern

    seen: list[int] = []
    for _word, day in tokens:
        if day not in seen:
            seen.append(day)
    pattern.weekdays = seen
    if count and len(seen) == 1:
        pattern.weekly_count = int(count.group(1))
    return pattern


@dataclass
class GeneratedSession:
    start_utc: datetime
    end_utc: datetime
    duration_minutes: int


def generate_sessions(
    *,
    start_date: date,
    end_date: date,
    training_days: Any,
    sessions: int | None,
    start_clock: time,
    duration_minutes: int,
    source_timezone: str,
) -> tuple[list[GeneratedSession], list[str]]:
    """Every session of a batch, in UTC, with a note for anything that did not add up.

    The dates come from the days text within `[start_date, end_date]`; the count
    LAIT reports (`training_sessions`) is authoritative for how many to keep, and
    a disagreement is *reported* rather than silently resolved either way.
    """
    warnings: list[str] = []
    pattern = parse_training_days(training_days)
    dates: list[date] = []

    if pattern.weekly_count and pattern.weekdays:
        d = start_date
        while d.weekday() != pattern.weekdays[0]:
            d += timedelta(days=1)
        dates = [d + timedelta(days=7 * i) for i in range(pattern.weekly_count)]
    elif pattern.weekdays:
        d = start_date
        while d <= end_date:
            if d.weekday() in pattern.weekdays:
                dates.append(d)
            d += timedelta(days=1)
    elif sessions == 1:
        dates = [start_date]  # one session: it can only be the start date
    else:
        warnings.append("training days could not be understood; no sessions generated")
        return [], warnings

    if sessions is not None and sessions > 0:
        if len(dates) > sessions:
            dates = dates[:sessions]
        elif len(dates) < sessions:
            warnings.append(f"the schedule yields {len(dates)} session(s) but LAIT reports {sessions}")

    if duration_minutes <= 0:
        warnings.append("session duration is zero; no sessions generated")
        return [], warnings

    out: list[GeneratedSession] = []
    for d in dates:
        start = uk_to_utc(datetime.combine(d, start_clock), source_timezone)
        out.append(GeneratedSession(start, start + timedelta(minutes=duration_minutes), duration_minutes))
    return out, warnings


# =============================================================================
# PLATFORM
# =============================================================================


def platform_for(method_name: Any) -> tuple[str | None, bool]:
    """LAIT's delivery method -> our `Platforms` name. Returns (name, recognised)."""
    text = (clean(method_name) or "").lower()
    for needle, name in (
        ("zoom", "Zoom"), ("zoho", "Zoho"), ("teams", "Microsoft_Teams"),
        ("meet", "Google_Meet"), ("classroom", "Classroom"), ("in person", "Classroom"),
    ):
        if needle in text:
            return name, True
    return None, False


# =============================================================================
# COURSE PAGE
# =============================================================================


class _Capture(HTMLParser):
    """Collects the text of the element with a given id, as a list of blocks.

    Block boundaries are `p`, `li`, headings and `br`, so a bulleted list stays a
    list instead of collapsing into one run-on sentence.
    """

    _BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "div", "tr"}
    _VOID = {"br", "img", "hr", "input", "meta", "link"}

    def __init__(self, target_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.target_id = target_id
        self.depth = 0
        self.active = False
        self.done = False
        self.blocks: list[str] = [""]
        self.list_item: list[bool] = [False]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.done:
            return
        if not self.active:
            if dict(attrs).get("id") == self.target_id:
                self.active = True
                self.depth = 1
            return
        if tag not in self._VOID:
            self.depth += 1
        if tag in self._BLOCK:
            self.blocks.append("")
            self.list_item.append(tag == "li")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.active and not self.done and tag in self._BLOCK:
            self.blocks.append("")
            self.list_item.append(False)

    def handle_endtag(self, tag: str) -> None:
        if not self.active or self.done or tag in self._VOID:
            return
        self.depth -= 1
        if tag in self._BLOCK:
            self.blocks.append("")
            self.list_item.append(False)
        if self.depth <= 0:
            self.done = True

    def handle_data(self, data: str) -> None:
        if self.active and not self.done:
            self.blocks[-1] += data

    def lines(self) -> list[str]:
        out = []
        for text, is_item in zip(self.blocks, self.list_item, strict=True):
            t = re.sub(r"\s+", " ", text).strip()
            if t:
                out.append(f"- {t}" if is_item else t)
        return out


def _element_lines(html: str, element_id: str) -> list[str]:
    parser = _Capture(element_id)
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - malformed markup must not abort a sync
        return []
    return parser.lines()


_LEVELS = (("beginner", "BEGINNER"), ("intermediate", "INTERMEDIATE"), ("advanced", "ADVANCED"))


def level_from_text(text: Any) -> str | None:
    """`Intermediate to Advanced` -> INTERMEDIATE.

    The enum has three values and LAIT sometimes states a range. The *entry*
    level is the one a learner needs to decide whether to enrol, so a range
    resolves to its lower bound: whichever level word appears first.
    """
    lowered = (clean(text) or "").lower()
    best: tuple[int, str] | None = None
    for word, value in _LEVELS:
        i = lowered.find(word)
        if i >= 0 and (best is None or i < best[0]):
            best = (i, value)
    return best[1] if best else None


@dataclass
class CoursePage:
    level: str | None = None
    duration_hours: int | None = None
    prerequisites: str | None = None
    price: float | None = None  # the "Regular Price", not the cheaper batch/group prices
    outline: str | None = None  # "Course Content": the topics the course covers, one per line
    overview: str | None = None  # "Course Overview": what the course is and who it is for


# A page is text somebody else wrote; keep what is stored bounded.
_MAX_PAGE_TEXT = 20_000


def _page_text(html: str, element_id: str) -> str | None:
    text = "\n".join(line for line in _element_lines(html, element_id) if line.strip()).strip()
    return text[:_MAX_PAGE_TEXT] or None


_PREREQ_STOP = re.compile(r"^(software|hardware)\s+requirements?\b", re.I)


def parse_course_page(html: str) -> CoursePage:
    page = CoursePage()

    duration = " ".join(_element_lines(html, "MainContent_lblCourseDuration"))
    m = re.search(r"(\d+(?:\.\d+)?)", duration)
    if m:
        page.duration_hours = round(float(m.group(1)))

    # "Regular Price: £540" -- the list price. The page also shows a lower per-batch and a
    # per-person group price; those are offers on this price, not the course's price.
    price_text = " ".join(_element_lines(html, "MainContent_lblPrice"))
    m = re.search(r"[£$€]\s*(\d[\d,]*(?:\.\d{1,2})?)", price_text)
    if m:
        try:
            page.price = float(m.group(1).replace(",", ""))
        except ValueError:
            page.price = None

    page.level = level_from_text(" ".join(_element_lines(html, "MainContent_lblCourseLevel")))

    lines = _element_lines(html, "MainContent_lblPrerequisitesHTML")
    kept: list[str] = []
    for line in lines:
        # The same block continues into software/hardware requirements, which
        # are not prerequisites: stop at the first of those headings.
        if _PREREQ_STOP.match(line.lstrip("- ")):
            break
        kept.append(line)
    text = "\n".join(kept).strip()
    page.prerequisites = text or None
    page.outline = _page_text(html, "MainContent_lblCourseOutlineHTML")
    page.overview = _page_text(html, "MainContent_lblCourseOverview")
    return page


# =============================================================================
# CATEGORIES (from the site's own navigation menu)
# =============================================================================


@dataclass
class MenuCategory:
    name: str
    course_urls: list[str] = field(default_factory=list)


class _Menu(HTMLParser):
    """`<li class="dropdown-item hs-has-sub-menu"><a href=".../courses/slug">Category</a><ul>...<a href=".../training-course/x">`.

    A category's courses are the links inside *its own* `<ul>` only. Scoping to
    that list matters: the same page carries other `/training-course/` links (a
    footer, a featured block), and without the scope they all leaked into
    whichever category happened to be listed last.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.categories: list[MenuCategory] = []
        self._current: MenuCategory | None = None
        self._link_text: str | None = None
        self._awaiting_list = False  # a category link was just closed; its <ul> comes next
        self._ul_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "ul":
            if self._awaiting_list:
                self._awaiting_list, self._ul_depth = False, 1
            elif self._ul_depth:
                self._ul_depth += 1
            return
        if tag != "a":
            return
        href = (dict(attrs).get("href") or "").strip()
        path = urlparse(href).path.rstrip("/")
        if re.fullmatch(r"/courses/[^/]+", path) and not self._ul_depth:
            self._link_text = ""
        elif path.startswith("/training-course/") and self._current is not None and self._ul_depth:
            self._current.course_urls.append(href)

    def handle_data(self, data: str) -> None:
        if self._link_text is not None:
            self._link_text += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._link_text is not None:
            name = re.sub(r"\s+", " ", self._link_text).strip()
            self._link_text = None
            if name:
                self._current = MenuCategory(name=name)
                self.categories.append(self._current)
                self._awaiting_list = True
        elif tag == "ul" and self._ul_depth:
            self._ul_depth -= 1
            if self._ul_depth == 0:
                self._current = None  # this category's list is over


def parse_category_menu(html: str) -> list[MenuCategory]:
    parser = _Menu()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001
        return []
    # A category with no course links is a menu heading, not a category.
    return [c for c in parser.categories if c.course_urls]


def _canonical_url(url: str) -> str:
    p = urlparse(url.strip())
    return f"{p.netloc.lower()}{p.path.rstrip('/').lower()}"


def choose_category(course_url: str, menu: list[MenuCategory]) -> str | None:
    """The most specific category the site files this course under.

    A course is listed under several headings (SQL for Beginners sits under both
    "Data & AI Technologies" and "Database and SQL"). `courses.category_id` holds
    one, so the choice is the category with the *fewest* courses -- the narrowest
    grouping -- and the earliest listed on a tie. Nothing is invented: a course the
    menu does not list gets no category.
    """
    target = _canonical_url(course_url)
    containing = [c for c in menu if any(_canonical_url(u) == target for u in c.course_urls)]
    if not containing:
        return None
    return min(containing, key=lambda c: (len(c.course_urls), menu.index(c))).name


def host_allowed(url: str, allowed: tuple[str, ...]) -> bool:
    p = urlparse(url)
    host = (p.hostname or "").lower()
    return p.scheme == "https" and any(host == h or host.endswith("." + h) for h in allowed)


# =============================================================================
# COURSE / BATCH PAYLOADS
# =============================================================================


@dataclass
class MappedCourse:
    external_id: str
    title: str
    description: str | None
    course_link: str | None
    small_course_image: str | None
    course_image: str | None
    api_duration_hours: int | None
    is_live: bool
    warnings: list[str] = field(default_factory=list)


def _https_url(value: Any, name: str, warnings: list[str], limit: int = 500) -> str | None:
    text = clean(value)
    if text is None:
        return None
    if not text.lower().startswith(("https://", "http://")):
        warnings.append(f"{name} dropped: not an http(s) URL")
        return None
    if len(text) > limit:
        warnings.append(f"{name} dropped: longer than {limit} characters")
        return None
    return text


def map_course(payload: dict[str, Any]) -> MappedCourse:
    cid = parse_int(payload.get("course_id"))
    if cid is None:
        raise MappingError("missing course_id")
    title = clean(payload.get("course_title"))
    if not title:
        raise MappingError("missing course title")
    warnings: list[str] = []
    title = fit_len(title, 255, "title", warnings)
    details = payload.get("course_details")
    description = re.sub(r"\r\n?", "\n", str(details)).strip() if details else None
    return MappedCourse(
        external_id=str(cid),
        title=title,
        description=description or None,
        course_link=_https_url(payload.get("course_url"), "course_url", warnings, 255),
        small_course_image=_https_url(payload.get("small_course_image"), "small_course_image", warnings),
        course_image=_https_url(payload.get("course_image"), "course_image", warnings),
        api_duration_hours=parse_int(payload.get("course_duration")),
        is_live=bool(payload.get("is_live")),
        warnings=warnings,
    )


def fit_len(value: str, limit: int, name: str, warnings: list[str]) -> str:
    if len(value) <= limit:
        return value
    warnings.append(f"{name} truncated from {len(value)} to {limit} characters")
    return value[:limit].rstrip()


@dataclass
class MappedBatch:
    batch_code: str
    external_course_id: str
    course_title: str
    start_date: date | None
    end_date: date | None
    duration_hours: int | None
    number_of_sessions: int | None
    is_active: bool
    total_admission: int
    tutor_guid: uuid.UUID | None
    tutor_external_id: int | None
    tutor_name: str | None
    method_name: str | None
    platform: str | None
    sessions: list[GeneratedSession]
    notes: str
    warnings: list[str] = field(default_factory=list)
    # The schedule as LAIT states it, kept so sessions can be re-generated later.
    training_days: str | None = None
    training_start_day: str | None = None
    training_end_day: str | None = None
    start_time: time | None = None
    end_time: time | None = None
    class_duration_minutes: int | None = None
    batch_fee: float | None = None
    schedule_timezone: str | None = None


AUTO_NOTE_PREFIX = "Auto: "


def batch_notes(
    *, batch_code: str, course_title: str, sessions: int | None, session_minutes: int,
    students: int, start: date | None, end: date | None,
) -> str:
    def when(d: date | None) -> str:
        return d.strftime("%a %d %b %Y") if d else "an unknown date"

    length = f"{session_minutes // 60}h" + (f"{session_minutes % 60:02d}m" if session_minutes % 60 else "") if session_minutes else "unknown length"
    plural = "" if students == 1 else "s"
    return (
        f"{AUTO_NOTE_PREFIX}Batch {batch_code} of \"{course_title}\": {sessions or 0} class(es) of {length}, "
        f"{students} student{plural} enrolled, starts {when(start)} and ends {when(end)}."
    )


def map_batch(payload: dict[str, Any], *, source_timezone: str) -> MappedBatch:
    bid = parse_int(payload.get("batch_id"))
    if bid is None:
        raise MappingError("missing batch_id")
    cid = parse_int(payload.get("course_id"))
    if cid is None:
        raise MappingError("missing course_id")

    warnings: list[str] = []
    start_local = parse_local_datetime(payload.get("training_start_date"))
    end_local = parse_local_datetime(payload.get("training_end_date"))
    if start_local is None:
        raise MappingError("missing or invalid training_start_date")
    start_utc = uk_to_utc(start_local, source_timezone)
    end_utc = uk_to_utc(end_local, source_timezone) if end_local else None

    hours = parse_int(payload.get("class_duration_h")) or 0
    minutes = parse_int(payload.get("class_duration_m")) or 0
    session_minutes = hours * 60 + minutes

    start_clock = parse_clock(payload.get("training_start_time")) or start_local.time()
    if session_minutes <= 0:
        end_clock = parse_clock(payload.get("training_end_time"))
        if end_clock is not None:
            session_minutes = (end_clock.hour * 60 + end_clock.minute) - (start_clock.hour * 60 + start_clock.minute)

    sessions_reported = parse_int(payload.get("training_sessions"))
    generated, gen_warnings = generate_sessions(
        start_date=start_local.date(),
        end_date=(end_local or start_local).date(),
        training_days=payload.get("training_days"),
        sessions=sessions_reported,
        start_clock=start_clock,
        duration_minutes=session_minutes,
        source_timezone=source_timezone,
    )
    warnings.extend(gen_warnings)

    method = clean(payload.get("method_name"))
    platform, recognised = platform_for(method)
    if method and not recognised:
        warnings.append("delivery method not recognised; platform left to the default")

    tutor_guid: uuid.UUID | None
    try:
        tutor_guid = parse_guid(payload.get("tutor_user_id")) if payload.get("tutor_user_id") else None
    except MappingError:
        tutor_guid = None
        warnings.append("tutor_user_id is not a valid GUID")

    title = clean(payload.get("Course_title")) or clean(payload.get("course_title")) or f"Course {cid}"
    admissions = parse_int(payload.get("total_admission")) or 0
    code = str(bid)
    start_date, end_date = start_utc.date(), (end_utc.date() if end_utc else None)

    return MappedBatch(
        batch_code=code,
        external_course_id=str(cid),
        course_title=title,
        start_date=start_date,
        end_date=end_date,
        duration_hours=round(session_minutes / 60) if session_minutes else None,
        number_of_sessions=sessions_reported,
        is_active=bool(payload.get("batch_is_active", True)),
        total_admission=admissions,
        tutor_guid=tutor_guid,
        tutor_external_id=parse_int(payload.get("tutor_id")),
        tutor_name=clean(payload.get("tutor_name")),
        method_name=method,
        platform=platform,
        sessions=generated,
        notes=batch_notes(
            batch_code=code, course_title=title, sessions=sessions_reported,
            session_minutes=session_minutes, students=admissions, start=start_date, end=end_date,
        ),
        warnings=warnings,
        training_days=clean(payload.get("training_days")),
        training_start_day=clean(payload.get("training_start_day")),
        training_end_day=clean(payload.get("training_end_day")),
        start_time=start_clock,
        end_time=parse_clock(payload.get("training_end_time")),
        class_duration_minutes=session_minutes or None,
        batch_fee=parse_money(payload.get("batch_fee")),
        schedule_timezone=source_timezone,
    )


# =============================================================================
# ORGANISATIONS (from a student's company)
# =============================================================================

_COMPANY_PLACEHOLDERS = {
    "n/a", "na", "none", "nil", "null", "-", "--", "no", "not applicable", "not working", "unemployed",
    "self employed", "self-employed", "selfemployed", "freelance", "freelancer", "student", "test",
    "tbc", "unknown", "home", "personal", "private", "retired", "looking for job", "jobseeker",
}


def company_junk_reason(name: Any) -> str | None:
    """Whether a `company` value is a real organisation worth a row of its own.

    Free-text company fields hold "N/A", "Self employed" and "student" as often as
    an employer, and each of those becoming an organisation would fill the table
    with entries that group nobody together.
    """
    text = clean(name)
    if not text:
        return "empty"
    lowered = text.lower().strip(" .")
    if lowered in _COMPANY_PLACEHOLDERS:
        return "placeholder"
    if len(text) < 2 or len(text) > 150:
        return "length"
    if not re.search(r"[A-Za-z]", text):
        return "no letters"
    if "@" in text or text.lower().startswith(("http://", "https://", "www.")):
        return "not a name"
    return None


def company_key(name: str) -> str:
    """Case, spacing and trailing-punctuation-insensitive: `ACME  Ltd.` == `acme ltd`."""
    return re.sub(r"\s+", " ", name.lower()).strip(" .,")

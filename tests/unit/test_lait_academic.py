"""backend/integrations/lait_academic.py -- schedule, page, menu and payload rules."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest

from backend.integrations import lait_academic as a
from backend.integrations.lait_mapping import MappingError

TZ = "Europe/London"


# ------------------------------------------------------------------- time


@pytest.mark.parametrize("raw,expected", [
    ("10:00 AM", time(10, 0)), ("04:00 PM", time(16, 0)), ("12:00 AM", time(0, 0)),
    ("12:30 PM", time(12, 30)), ("16:45", time(16, 45)), ("6:00 pm", time(18, 0)),
])
def test_clock_parsing(raw: str, expected: time) -> None:
    assert a.parse_clock(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "noon", "25:00", "13:00 PM", "10:99", "0:30 AM"])
def test_bad_clocks_are_none(raw) -> None:  # noqa: ANN001
    assert a.parse_clock(raw) is None


def test_uk_summer_time_is_one_hour_ahead_of_utc_and_winter_is_not() -> None:
    summer = a.uk_to_utc(datetime(2026, 9, 21, 10, 0), TZ)
    winter = a.uk_to_utc(datetime(2026, 1, 21, 10, 0), TZ)
    assert summer == datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)
    assert winter == datetime(2026, 1, 21, 10, 0, tzinfo=timezone.utc)


def test_the_clock_change_days_are_deterministic() -> None:
    assert a.uk_to_utc(datetime(2026, 3, 29, 1, 30), TZ).tzinfo is not None  # skipped hour
    # Repeated hour resolves to its first occurrence.
    assert a.uk_to_utc(datetime(2026, 10, 25, 1, 30), TZ) == datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)


def test_a_late_evening_session_can_change_the_utc_date() -> None:
    # 00:30 BST is 23:30 UTC the day before.
    assert a.uk_to_utc(datetime(2026, 9, 22, 0, 30), TZ).date() == date(2026, 9, 21)


# ---------------------------------------------------------- training days


@pytest.mark.parametrize("text,weekdays,count", [
    ("Monday & Friday", [0, 4], None),
    ("Mon, Wed & Fri (2 wks)", [0, 2, 4], None),
    ("Wed & Fri (3 wks)", [2, 4], None),
    ("Thursday", [3], None),
    ("Saturday", [5], None),
    ("2 Sundays", [6], 2),
    ("5 Thursdays", [3], 5),
    ("Thursday to Friday", [3, 4], None),
    ("Monday to Tuesday", [0, 1], None),
    ("Friday to Monday", [4, 5, 6, 0], None),
    ("Weekend", [5, 6], None),
    ("Weekdays", [0, 1, 2, 3, 4], None),
])
def test_every_form_lait_emits_is_understood(text: str, weekdays: list[int], count) -> None:  # noqa: ANN001
    p = a.parse_training_days(text)
    assert p.weekdays == weekdays and p.weekly_count == count


@pytest.mark.parametrize("text", ["", None, "TBC", "Various dates", "monster truck"])
def test_unrecognised_days_yield_an_empty_pattern(text) -> None:  # noqa: ANN001
    assert a.parse_training_days(text).weekdays == []


def _gen(days: str, start: date, end: date, n: int | None, clock=time(10, 0), minutes=360):  # noqa: ANN001, ANN202
    return a.generate_sessions(start_date=start, end_date=end, training_days=days, sessions=n,
                               start_clock=clock, duration_minutes=minutes, source_timezone=TZ)


def test_the_sample_batch_yields_exactly_two_sessions_on_the_right_days_in_utc() -> None:
    sessions, warnings = _gen("Monday & Friday", date(2026, 9, 21), date(2026, 9, 25), 2)
    assert warnings == []
    assert [s.start_utc for s in sessions] == [
        datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc), datetime(2026, 9, 25, 9, 0, tzinfo=timezone.utc)]
    assert all(s.duration_minutes == 360 for s in sessions)
    assert sessions[0].end_utc == datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)  # 10:00-16:00 UK


def test_a_weekly_count_starts_on_the_first_matching_weekday() -> None:
    sessions, _ = _gen("2 Sundays", date(2026, 9, 20), date(2026, 9, 27), 2, minutes=240)
    assert [s.start_utc.date() for s in sessions] == [date(2026, 9, 20), date(2026, 9, 27)]


def test_five_thursdays_are_a_week_apart() -> None:
    sessions, _ = _gen("5 Thursdays", date(2026, 10, 1), date(2026, 10, 29), 5)
    days = [s.start_utc.date() for s in sessions]
    assert len(days) == 5 and all((days[i + 1] - days[i]).days == 7 for i in range(4))


def test_the_reported_session_count_caps_the_schedule() -> None:
    sessions, _ = _gen("Mon, Wed & Fri (2 wks)", date(2026, 9, 21), date(2026, 10, 2), 6)
    assert len(sessions) == 6


def test_a_disagreement_with_lait_is_reported_not_hidden() -> None:
    sessions, warnings = _gen("Monday & Friday", date(2026, 9, 21), date(2026, 9, 25), 3)
    assert len(sessions) == 2 and any("3" in w for w in warnings)


def test_unparseable_days_generate_nothing_unless_it_is_a_single_session() -> None:
    assert _gen("TBC", date(2026, 9, 21), date(2026, 9, 25), 2)[0] == []
    single, _ = _gen("TBC", date(2026, 9, 21), date(2026, 9, 21), 1)
    assert [s.start_utc.date() for s in single] == [date(2026, 9, 21)]


def test_a_zero_duration_generates_nothing() -> None:
    assert _gen("Monday", date(2026, 9, 21), date(2026, 9, 21), 1, minutes=0)[0] == []


# ---------------------------------------------------------------- platform


@pytest.mark.parametrize("method,name", [
    ("Online Training using Zoom", "Zoom"), ("Classroom Training", "Classroom"),
    ("Microsoft Teams", "Microsoft_Teams"), ("Google Meet", "Google_Meet"),
])
def test_platform_mapping(method: str, name: str) -> None:
    assert a.platform_for(method) == (name, True)


def test_an_unknown_method_is_flagged() -> None:
    assert a.platform_for("Carrier pigeon") == (None, False)


# ------------------------------------------------------------- course page

PAGE = """
<li><span>Duration: </span><span><span id="MainContent_lblCourseDuration">12 Hours</span></span></li>
<li><span>Level: </span><span><span id="MainContent_lblCourseLevel">Intermediate to Advanced</span></span></li>
<h2>Requirements</h2>
<p><span id="MainContent_lblPrerequisitesHTML"><p>Participants should have</p>
<ul><li>Basic to intermediate Python skills</li>
<li>Familiarity with the <b>Generative AI</b> course, especially RAG.</li></ul>
<p>Software Requirements</p><ul><li>Python 3.12</li></ul>
<p>Hardware Requirements</p><ul><li>8GB RAM</li></ul></span></p>
"""


def test_the_page_yields_duration_level_and_prerequisites() -> None:
    p = a.parse_course_page(PAGE)
    assert p.duration_hours == 12
    assert p.level == "INTERMEDIATE"  # the lower bound of "Intermediate to Advanced"
    assert p.prerequisites == (
        "Participants should have\n- Basic to intermediate Python skills\n- Familiarity with the Generative AI course, especially RAG."
    )


def test_software_and_hardware_requirements_are_not_prerequisites() -> None:
    text = a.parse_course_page(PAGE).prerequisites or ""
    assert "Python 3.12" not in text and "8GB" not in text and "Software" not in text


def test_a_page_without_the_fields_yields_nones_not_errors() -> None:
    p = a.parse_course_page("<html><body>nothing here</body></html>")
    assert (p.duration_hours, p.level, p.prerequisites) == (None, None, None)


def test_broken_markup_does_not_raise() -> None:
    a.parse_course_page('<span id="MainContent_lblCourseDuration"><p><li>12 Hours')


@pytest.mark.parametrize("text,level", [
    ("Beginner", "BEGINNER"), ("Beginners", "BEGINNER"), ("Intermediate", "INTERMEDIATE"),
    ("Intermediate to Advanced", "INTERMEDIATE"), ("Beginner to Intermediate", "BEGINNER"),
    ("Advanced", "ADVANCED"), ("All levels", None), ("", None),
])
def test_level_mapping(text: str, level) -> None:  # noqa: ANN001
    assert a.level_from_text(text) == level


# ----------------------------------------------------------------- menu

MENU = """
<li class='dropdown-item hs-has-sub-menu'><a href='https://x.test/courses/data-ai-tech'>Data &amp; AI Technologies</a><ul>
 <li><a href='https://x.test/training-course/sql-beginners'>SQL for Beginners</a></li>
 <li><a href='https://x.test/training-course/python'>Python</a></li>
 <li><a href='https://x.test/training-course/excel'>Excel</a></li></ul></li>
<li class='dropdown-item hs-has-sub-menu'><a href='https://x.test/courses/database-and-sql'>Database and SQL</a><ul>
 <li><a href='https://x.test/training-course/sql-beginners'>SQL for Beginners</a></li></ul></li>
<li><a href='https://x.test/courses/empty-heading'>Empty</a></li>
"""


def test_the_menu_is_parsed_into_categories() -> None:
    menu = a.parse_category_menu(MENU)
    assert [c.name for c in menu] == ["Data & AI Technologies", "Database and SQL"]  # the empty heading is dropped


def test_links_outside_a_categorys_own_list_do_not_leak_into_it() -> None:
    """The last category used to swallow every later /training-course/ link on the page
    (43 'Teens Coding' courses on the real site)."""
    html = MENU + "<footer><a href='https://x.test/training-course/footer-only'>Footer</a></footer>"
    menu = a.parse_category_menu(html)
    assert all("footer-only" not in u for c in menu for u in c.course_urls)
    assert a.choose_category("https://x.test/training-course/footer-only", menu) is None
    assert [len(c.course_urls) for c in menu] == [3, 1]


def test_the_narrowest_category_wins() -> None:
    menu = a.parse_category_menu(MENU)
    assert a.choose_category("https://x.test/training-course/sql-beginners", menu) == "Database and SQL"
    assert a.choose_category("https://x.test/training-course/python", menu) == "Data & AI Technologies"


def test_a_course_the_menu_does_not_list_gets_no_category() -> None:
    assert a.choose_category("https://x.test/training-course/unknown", a.parse_category_menu(MENU)) is None


def test_url_matching_ignores_case_and_trailing_slash() -> None:
    menu = a.parse_category_menu(MENU)
    assert a.choose_category("HTTPS://X.TEST/training-course/Python/", menu) == "Data & AI Technologies"


@pytest.mark.parametrize("url,ok", [
    ("https://www.londonacademyofit.co.uk/training-course/x", True),
    ("https://londonacademyofit.co.uk/x", True),
    ("http://www.londonacademyofit.co.uk/x", False),
    ("https://londonacademyofit.co.uk.evil.test/x", False),
    ("https://evil.test/londonacademyofit.co.uk", False),
    ("https://notlondonacademyofit.co.uk/x", False),
    ("file:///etc/passwd", False),
])
def test_only_the_lait_site_is_ever_fetched(url: str, ok: bool) -> None:
    assert a.host_allowed(url, ("londonacademyofit.co.uk",)) is ok


# ---------------------------------------------------------------- payloads


def test_course_mapping() -> None:
    c = a.map_course({
        "course_id": 1134, "course_title": "  Agentic AI &  Automation ", "course_details": "Text\r\n",
        "small_course_image": "https://x/s.jpg", "course_image": "javascript:alert(1)", "course_duration": 12,
        "is_live": True, "course_url": "https://x/training-course/a",
    })
    assert (c.external_id, c.title, c.description, c.is_live, c.api_duration_hours) == ("1134", "Agentic AI & Automation", "Text", True, 12)
    assert c.course_image is None and any("course_image" in w for w in c.warnings)  # a non-http(s) image is dropped
    assert c.small_course_image == "https://x/s.jpg"


@pytest.mark.parametrize("payload", [{}, {"course_id": 1}, {"course_title": "x"}, {"course_id": "abc", "course_title": "x"}])
def test_unusable_courses_are_refused(payload: dict) -> None:
    with pytest.raises(MappingError):
        a.map_course(payload)


BATCH = {
    "batch_id": 11285, "course_id": 1077, "Course_title": "SQL for Beginners", "training_days": "Monday & Friday",
    "training_start_date": "2026-09-21T10:00:00", "training_end_date": "2026-09-25T10:00:00",
    "training_start_time": "10:00 AM", "training_end_time": "04:00 PM", "training_sessions": 2,
    "class_duration_h": 6, "class_duration_m": 0, "method_name": "Classroom Training",
    "tutor_id": 1, "tutor_user_id": "746affe5-c99a-484c-95f8-577f1325a5fa", "tutor_name": "Mr Younus  Kazi",
    "batch_is_active": True, "total_admission": 2,
}


def test_batch_mapping_matches_the_spec() -> None:
    b = a.map_batch(BATCH, source_timezone=TZ)
    assert (b.batch_code, b.external_course_id, b.duration_hours, b.number_of_sessions) == ("11285", "1077", 6, 2)
    assert (b.start_date, b.end_date, b.is_active, b.total_admission, b.platform) == (date(2026, 9, 21), date(2026, 9, 25), True, 2, "Classroom")
    assert len(b.sessions) == 2 and b.warnings == []
    assert b.notes.startswith(a.AUTO_NOTE_PREFIX) and "11285" in b.notes and "SQL for Beginners" in b.notes and "2 students" in b.notes


def test_batch_dates_are_utc_dates_not_uk_dates() -> None:
    late = {**BATCH, "training_start_date": "2026-09-22T00:30:00", "training_start_time": "12:30 AM"}
    assert a.map_batch(late, source_timezone=TZ).start_date == date(2026, 9, 21)


def test_a_partial_hour_duration_is_kept_exactly_on_the_sessions() -> None:
    b = a.map_batch({**BATCH, "class_duration_h": 1, "class_duration_m": 30, "training_sessions": 2}, source_timezone=TZ)
    assert {s.duration_minutes for s in b.sessions} == {90}


@pytest.mark.parametrize("override", [{"batch_id": None}, {"course_id": None}, {"training_start_date": "garbage"}, {"training_start_date": None}])
def test_unusable_batches_are_refused(override: dict) -> None:
    with pytest.raises(MappingError):
        a.map_batch({**BATCH, **override}, source_timezone=TZ)


def test_a_bad_tutor_guid_is_a_warning_not_a_failure() -> None:
    b = a.map_batch({**BATCH, "tutor_user_id": "nope"}, source_timezone=TZ)
    assert b.tutor_guid is None and any("GUID" in w for w in b.warnings)


# ---------------------------------------------------------------- companies


@pytest.mark.parametrize("junk", ["", "N/A", "none", "Self employed", "self-employed", "Student", "-", "12345", "a", "me@x.com", "www.x.com"])
def test_placeholders_are_not_organisations(junk: str) -> None:
    assert a.company_junk_reason(junk) is not None


@pytest.mark.parametrize("real", ["Acme Ltd", "NHS", "Barclays Bank PLC", "Ministry of Defence"])
def test_real_employers_are_accepted(real: str) -> None:
    assert a.company_junk_reason(real) is None


def test_company_keys_ignore_case_spacing_and_trailing_punctuation() -> None:
    assert a.company_key("ACME  Ltd.") == a.company_key("acme ltd") == "acme ltd"



def test_the_schedule_the_source_states_is_kept_so_sessions_can_be_regenerated() -> None:
    """The batch payload the source sends, verbatim: Monday & Friday, 10:00 AM - 04:00 PM UK time, two sessions."""
    from datetime import time

    from backend.integrations.lait_academic import map_batch

    payload = {
        "batch_id": 11285, "course_id": 1077, "Course_title": "SQL for Beginners", "batch_fee": 420, "training_days": "Monday & Friday",
        "training_start_date": "2026-09-21T10:00:00", "training_start_day": "Monday", "training_end_date": "2026-09-25T10:00:00", "training_end_day": "Friday",
        "dates": "21 Sep 2026 - 25 Sep 2026", "training_start_time": "10:00 AM", "training_end_time": "04:00 PM", "training_sessions": 2,
        "class_duration_h": 6, "class_duration_m": 0, "training_method_id": 1, "method_name": "Classroom Training", "tutor_id": 1,
        "tutor_user_id": "746affe5-c99a-484c-95f8-577f1325a5fa", "tutor_name": "Mr Younus Kazi", "batch_is_active": True, "total_admission": 2,
    }
    m = map_batch(payload, source_timezone="Europe/London")
    assert (m.training_days, m.training_start_day, m.training_end_day) == ("Monday & Friday", "Monday", "Friday")
    assert (m.start_time, m.end_time, m.class_duration_minutes, m.batch_fee, m.schedule_timezone) == (time(10, 0), time(16, 0), 360, 420.0, "Europe/London")
    assert m.method_name == "Classroom Training" and len(m.sessions) == 2

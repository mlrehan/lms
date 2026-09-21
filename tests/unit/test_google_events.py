"""backend/integrations/google_events.py -- what is written to Google, and what guests may do."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from backend.integrations import google_events as g

START = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)
BATCH = g.BatchView(code="11285", course_title="SQL for Beginners", is_active=True, start_date=date(2026, 9, 21), end_date=date(2026, 9, 25), delivery="Classroom Training")


def _session(**over):  # noqa: ANN003, ANN202
    base = dict(public_id="sess-1", number=1, total=2, start_utc=START, end_utc=START + timedelta(hours=6),
                tutor_name="Younus Kazi", platform="Classroom", meeting_link=None, classroom=None, student_notes=None)
    base.update(over)
    return g.SessionView(**base)


GUESTS = [g.Guest("tutor@x.test", "Tutor", "tutor"), g.Guest("s@x.test", "Stu", "student")]


# ------------------------------------------------------------------ guests


def test_emails_are_deduplicated_case_insensitively_keeping_the_most_senior_role() -> None:
    kept, dropped = g.dedupe_guests([g.Guest("A@X.test", "A", "guardian"), g.Guest("a@x.test", "A", "tutor"), g.Guest("b@x.test", "B", "student")], 50)
    assert [(k.email, k.role) for k in kept] == [("a@x.test", "tutor"), ("b@x.test", "student")] and dropped == 0


@pytest.mark.parametrize("bad", ["", "nope", "a@b", "a b@x.test", "a@x.test, b@x.test", "<a@x.test>", None])
def test_invalid_addresses_are_dropped_not_sent_to_google(bad) -> None:  # noqa: ANN001
    kept, _ = g.dedupe_guests([g.Guest(bad, "X", "student"), g.Guest("ok@x.test", "Ok", "student")], 50)
    assert [k.email for k in kept] == ["ok@x.test"]


def test_the_guest_cap_is_reported_not_silent() -> None:
    many = [g.Guest(f"s{i}@x.test", "S", "student") for i in range(10)] + [g.Guest("t@x.test", "T", "tutor")]
    kept, dropped = g.dedupe_guests(many, 5)
    assert len(kept) == 5 and dropped == 6 and kept[0].role == "tutor"  # the tutor is never the one left off


# ------------------------------------------------------------------- events


def test_times_are_utc_with_an_explicit_z() -> None:
    body = g.build_event_body(_session(), BATCH, GUESTS, invite=True)
    assert body["start"] == {"dateTime": "2026-09-21T09:00:00Z", "timeZone": "UTC"}
    assert body["end"]["dateTime"] == "2026-09-21T15:00:00Z"


def test_guests_can_neither_see_each_other_edit_nor_invite() -> None:
    body = g.build_event_body(_session(), BATCH, GUESTS, invite=True)
    assert body["guestsCanSeeOtherGuests"] is False  # else every guest reads everyone's email
    assert body["guestsCanModify"] is False and body["guestsCanInviteOthers"] is False


def test_reminders_never_send_email() -> None:
    reminders = g.build_event_body(_session(), BATCH, GUESTS, invite=True)["reminders"]
    assert reminders["useDefault"] is False and {r["method"] for r in reminders["overrides"]} == {"popup"}


def test_attendees_are_omitted_entirely_when_inviting_is_off() -> None:
    assert "attendees" not in g.build_event_body(_session(), BATCH, GUESTS, invite=False)
    assert [a["email"] for a in g.build_event_body(_session(), BATCH, GUESTS, invite=True)["attendees"]] == ["tutor@x.test", "s@x.test"]


def test_the_event_can_be_traced_back_to_its_session() -> None:
    props = g.build_event_body(_session(), BATCH, GUESTS, invite=True)["extendedProperties"]["private"]
    assert props == {g.MANAGED_KEY: "1", g.SESSION_KEY: "sess-1", g.BATCH_KEY: "11285"}


def test_the_title_follows_the_institutions_calendar_and_the_session_number_is_in_the_description() -> None:
    body = g.build_event_body(_session(number=2), BATCH, GUESTS, invite=True)
    assert body["summary"] == "SQL for Beginners (11285)"  # as in the calendar it replaces: Course (batch-code)
    assert body["description"].splitlines()[0] == "Session 2 of 2"


def test_location_is_the_classroom_address_or_the_platform_name() -> None:
    assert g.build_event_body(_session(classroom="Office 4, Boardman House, London E15 1NT"), BATCH, GUESTS, invite=True)["location"] == "Office 4, Boardman House, London E15 1NT"
    assert g.build_event_body(_session(platform="Zoom"), BATCH, GUESTS, invite=True)["location"] == "Zoom Video Conferencing"
    assert g.build_event_body(_session(platform="Microsoft_Teams"), BATCH, GUESTS, invite=True)["location"] == "Microsoft Teams"
    assert g.build_event_body(_session(platform="Classroom"), BATCH, GUESTS, invite=True)["location"] == "Classroom"
    assert g.build_event_body(_session(platform=None), BATCH, GUESTS, invite=True)["location"] == "Online"


def test_the_join_link_and_student_notes_are_included_but_the_body_has_no_field_for_tutor_notes() -> None:
    body = g.build_event_body(_session(platform="Zoom", meeting_link="https://zoom.test/j/1", student_notes="Bring a laptop"), BATCH, GUESTS, invite=True)
    assert "https://zoom.test/j/1" in body["description"] and "Bring a laptop" in body["description"]
    import inspect
    assert "tutor_notes" not in inspect.signature(g.SessionView).parameters  # cannot be passed in, so cannot leak


# --------------------------------------------------------------------- hash


def test_the_hash_is_stable_and_sensitive_to_every_visible_change() -> None:
    base = g.build_event_body(_session(), BATCH, GUESTS, invite=True)
    assert g.body_hash(base) == g.body_hash(g.build_event_body(_session(), BATCH, GUESTS, invite=True))
    for changed in (
        g.build_event_body(_session(start_utc=START + timedelta(hours=1), end_utc=START + timedelta(hours=7)), BATCH, GUESTS, invite=True),
        g.build_event_body(_session(meeting_link="https://z.test/1"), BATCH, GUESTS, invite=True),
        g.build_event_body(_session(), BATCH, GUESTS[:1], invite=True),  # a guest removed (an enrolment dropped)
        g.build_event_body(_session(tutor_name="Someone Else"), BATCH, GUESTS, invite=True),
    ):
        assert g.body_hash(changed) != g.body_hash(base)


# --------------------------------------------------------------- calendars


def test_a_closed_batch_is_labelled_in_its_calendar_title() -> None:
    closed = g.BatchView("1", "Course", False, None, None)
    assert g.build_calendar_body(closed, "Europe/London")["summary"].endswith("[Closed]")
    assert g.build_calendar_body(BATCH, "Europe/London")["timeZone"] == "Europe/London"


def test_google_datetimes_parse_to_utc_and_all_day_events_are_ignored() -> None:
    assert g.parse_google_datetime({"dateTime": "2026-09-21T10:00:00+01:00"}) == datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)
    assert g.parse_google_datetime({"dateTime": "2026-09-21T09:00:00Z"}) == START
    assert g.parse_google_datetime({"date": "2026-09-21"}) is None
    assert g.parse_google_datetime({"dateTime": "garbage"}) is None and g.parse_google_datetime(None) is None


def test_guest_emails_exclude_the_organiser() -> None:
    event = {"attendees": [{"email": "Org@x.test", "organizer": True}, {"email": "A@x.test"}, {"email": "me@x.test", "self": True}]}
    assert g.guest_emails(event) == {"a@x.test"}


def test_the_calendar_link_encodes_the_id() -> None:
    assert g.calendar_url("abc@group.calendar.google.com").startswith("https://calendar.google.com/calendar/u/0/r?cid=")


# ------------------------------------------------ what an administrator types in Google


@pytest.mark.parametrize("text,platform,classroom", [
    ("Zoom Video Conferencing", "Zoom", None),
    ("zoom", "Zoom", None),
    ("https://us02web.zoom.us/j/123", "Zoom", None),
    ("Microsoft Teams", "Microsoft_Teams", None),
    ("Google Meet", "Google_Meet", None),
    ("https://meet.google.com/abc-defg-hij", "Google_Meet", None),
    ("Office 4 (4th Floor), Boardman House, 64 Broadway, Stratford, London E15 1NT", "Classroom", "Office 4 (4th Floor), Boardman House, 64 Broadway, Stratford, London E15 1NT"),
    ("Room 12", "Classroom", "Room 12"),
    ("", None, None),
    (None, None, None),
])
def test_a_typed_location_becomes_a_platform_or_a_classroom(text, platform, classroom) -> None:  # noqa: ANN001
    assert g.parse_location(text) == (platform, classroom)


def test_every_label_the_builder_writes_is_understood_when_read_back() -> None:
    for platform in ("Zoom", "Google_Meet", "Microsoft_Teams", "Zoho"):
        assert g.parse_location(g.platform_label(platform)) == (platform, None)


@pytest.mark.parametrize("title,yes", [
    ("CANCEL", True), ("Cancelled", True), ("cancelled - SQL for Beginners (11285)", True), ("[CANCELED] Python", True),
    ("(Cancel) Python L2", True), ("  CANCEL: room booked", True),
    ("SQL for Beginners (11285)", False), ("Cancellation policy workshop", False), ("Do not cancel", False), ("", False), (None, False),
])
def test_only_a_leading_cancel_cancels(title, yes) -> None:  # noqa: ANN001
    assert g.is_cancel_title(title) is yes


def test_a_rejected_event_is_reconsidered_only_when_it_changes() -> None:
    a = {"summary": "X", "location": "Room", "start": {"dateTime": "2026-09-21T09:00:00Z"}, "end": {"dateTime": "2026-09-21T10:00:00Z"}}
    assert g.event_signature(a) == g.event_signature(dict(a))
    assert g.event_signature(a) != g.event_signature({**a, "summary": "Y"})
    assert g.event_signature(a) != g.event_signature({**a, "end": {"dateTime": "2026-09-21T11:00:00Z"}})


def test_the_description_never_names_the_guests() -> None:
    body = g.build_event_body(_session(), BATCH, [g.Guest("secret.student@x.test", "Secret Student", "student")], invite=True)
    assert "Secret Student" not in body["description"] and "secret.student" not in body["description"]

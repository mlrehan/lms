"""Generating a batch's sessions from how it is scheduled."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest

from backend.services.session_planner import (
    PlanError, PlanSettings, carry_schedule, infer_from_sessions, plan_sessions, weekdays_from_text, weekdays_to_text, zone,
)


def settings(**over) -> PlanSettings:  # noqa: ANN003
    base = dict(timezone="Europe/London", weekdays=[0, 4], start_time=time(10, 0), duration_minutes=360, start_date=date(2026, 9, 21), end_date=date(2026, 9, 25), sessions=2)
    return PlanSettings(**{**base, **over})


def utc(*a: int) -> datetime:
    return datetime(*a, tzinfo=timezone.utc)


def test_the_sample_batch_yields_its_two_sessions_in_utc() -> None:
    """Monday & Friday, 21-25 Sep 2026, 10:00 AM - 04:00 PM UK (BST, so an hour behind UTC)."""
    planned, warnings = plan_sessions(settings())
    assert warnings == []
    assert [(p.start_utc, p.end_utc) for p in planned] == [(utc(2026, 9, 21, 9), utc(2026, 9, 21, 15)), (utc(2026, 9, 25, 9), utc(2026, 9, 25, 15))]


def test_the_same_classes_read_in_another_zone_are_the_same_instants() -> None:
    carried = carry_schedule(time(10, 0), [0, 4], from_tz="Europe/London", to_tz="Asia/Dhaka", on=date(2026, 9, 21))
    assert carried.clock == time(15, 0) and carried.weekdays == [0, 4] and carried.day_shift == 0
    planned, _ = plan_sessions(settings(timezone="Asia/Dhaka", start_time=carried.clock, weekdays=carried.weekdays))
    assert [p.start_utc for p in planned] == [utc(2026, 9, 21, 9), utc(2026, 9, 25, 9)]


def test_a_class_that_crosses_midnight_in_the_other_zone_moves_its_weekday() -> None:
    """Monday 23:00 in London is Tuesday 04:00 in Dhaka: carrying only the clock would be a different instant."""
    carried = carry_schedule(time(23, 0), [0], from_tz="Europe/London", to_tz="Asia/Dhaka", on=date(2026, 9, 21))
    assert (carried.clock, carried.weekdays, carried.day_shift) == (time(4, 0), [1], 1)
    planned, _ = plan_sessions(settings(timezone="Asia/Dhaka", weekdays=carried.weekdays, start_time=carried.clock, start_date=date(2026, 9, 22), end_date=date(2026, 9, 22), sessions=1))
    assert planned[0].start_utc == utc(2026, 9, 21, 22)         # the London Monday 23:00 (BST) instant


def test_more_dates_than_sessions_are_trimmed_and_fewer_are_reported() -> None:
    planned, w = plan_sessions(settings(weekdays=[0, 1, 2, 3, 4], start_date=date(2026, 9, 21), end_date=date(2026, 9, 30), sessions=3))
    assert [p.start_utc.day for p in planned] == [21, 22, 23] and w == []
    planned, w = plan_sessions(settings(sessions=5))
    assert len(planned) == 2 and "2 sessions but 5 were asked for" in w[0]


def test_without_an_end_date_the_count_decides() -> None:
    planned, w = plan_sessions(settings(weekdays=[3], end_date=None, sessions=4, start_date=date(2026, 9, 21)))
    assert w == [] and [p.start_utc.date() for p in planned] == [date(2026, 9, 24), date(2026, 10, 1), date(2026, 10, 8), date(2026, 10, 15)]


def test_five_thursdays_means_five_weekly_classes() -> None:
    days, count = weekdays_from_text("5 Thursdays")
    planned, _ = plan_sessions(settings(weekdays=days, weekly_count=count, sessions=None, end_date=date(2026, 9, 25)))
    assert len(planned) == 5 and all(p.start_utc.weekday() == 3 for p in planned)


@pytest.mark.parametrize("over, expect", [
    (dict(start_time=None), "start time"), (dict(duration_minutes=None), "duration"), (dict(duration_minutes=2), "duration"), (dict(start_date=None), "start date"),
    (dict(weekdays=[]), "days"), (dict(end_date=date(2026, 9, 1)), "before the start"), (dict(end_date=None, sessions=None), "end date or a number"),
])
def test_missing_or_impossible_inputs_produce_a_message_not_a_guess(over, expect) -> None:  # noqa: ANN001
    planned, warnings = plan_sessions(settings(**over))
    assert planned == [] and expect in warnings[0]


def test_an_unknown_time_zone_is_refused() -> None:
    with pytest.raises(PlanError):
        zone("Mars/Olympus")
    with pytest.raises(PlanError):
        plan_sessions(settings(timezone="Nowhere/Land"))


def test_a_time_that_does_not_exist_is_moved_and_reported() -> None:
    """01:30 on 29 Mar 2026 does not exist in London: the clocks jump from 01:00 to 02:00."""
    planned, warnings = plan_sessions(settings(weekdays=[6], start_date=date(2026, 3, 29), end_date=date(2026, 3, 29), start_time=time(1, 30), sessions=1))
    assert len(planned) == 1 and "does not exist" in warnings[0]


def test_a_class_after_the_clocks_change_keeps_its_local_time() -> None:
    planned, _ = plan_sessions(settings(weekdays=[0], start_date=date(2026, 10, 19), end_date=date(2026, 11, 2), sessions=3, start_time=time(10, 0)))
    assert [p.start_utc.hour for p in planned] == [9, 10, 10]                 # BST until 25 Oct, then GMT
    assert [p.start_local.hour for p in planned] == [10, 10, 10]


def test_the_session_cap_stops_a_runaway_request() -> None:
    planned, warnings = plan_sessions(settings(weekdays=[0, 1, 2, 3, 4, 5, 6], start_date=date(2026, 1, 1), end_date=date(2028, 1, 1), sessions=None))
    assert len(planned) == 200


def test_days_text_round_trips() -> None:
    assert weekdays_from_text("Monday & Friday") == ([0, 4], None)
    assert weekdays_to_text([4, 0]) == "Monday & Friday" and weekdays_to_text([2]) == "Wednesday" and weekdays_to_text([0, 2, 4]) == "Monday, Wednesday & Friday"


def test_existing_sessions_imply_a_schedule() -> None:
    got = infer_from_sessions([(utc(2026, 9, 21, 9), utc(2026, 9, 21, 15)), (utc(2026, 9, 25, 9), utc(2026, 9, 25, 15)), (utc(2026, 9, 28, 9), utc(2026, 9, 28, 14))], "Europe/London")
    assert (got.weekdays, got.start_time, got.duration_minutes, got.count) == ([0, 4], time(10, 0), 360, 3)
    assert infer_from_sessions([(utc(2026, 9, 21, 9), utc(2026, 9, 21, 15))], "Asia/Dhaka").start_time == time(15, 0)

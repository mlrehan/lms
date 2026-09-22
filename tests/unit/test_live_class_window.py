"""When the door to a class is open.

The rule -- thirty minutes before the start until the end -- is enforced
server-side, so it has to be right in the one place that decides it. These are
pure-function tests over explicit times; no clock is frozen and no session row
exists, because neither is what the rule depends on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.core.live_class import FALLBACK_DURATION, JOIN_OPENS_BEFORE, is_open, join_window

START = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)
END = START + timedelta(hours=1)


def test_the_door_opens_exactly_thirty_minutes_early() -> None:
    window = join_window(START, END)
    assert window is not None
    assert window.opens_at == START - timedelta(minutes=30)
    assert JOIN_OPENS_BEFORE == timedelta(minutes=30)


@pytest.mark.parametrize(
    ("moment", "open_"),
    [
        (START - timedelta(minutes=31), False),   # a minute too early
        (START - timedelta(minutes=30), True),    # the boundary is inclusive
        (START, True),
        (END, True),                              # still open at the final second
        (END + timedelta(seconds=1), False),      # and shut immediately after
    ],
)
def test_the_boundaries(moment: datetime, open_: bool) -> None:
    assert is_open(moment, START, END) is open_


def test_a_duration_stands_in_for_a_missing_end() -> None:
    window = join_window(START, None, duration_minutes=90)
    assert window is not None
    assert window.closes_at == START + timedelta(minutes=90)


def test_a_stored_end_beats_a_batch_duration() -> None:
    """Both present: the end is what the calendar and the tutor agreed on,
    while the duration is a property of the batch that may not fit this one."""
    window = join_window(START, END, duration_minutes=600)
    assert window is not None
    assert window.closes_at == END


def test_a_session_with_neither_still_stops_being_joinable() -> None:
    window = join_window(START)
    assert window is not None
    assert window.closes_at == START + FALLBACK_DURATION
    assert is_open(START + FALLBACK_DURATION + timedelta(minutes=1), START) is False


def test_an_end_before_its_start_does_not_leave_the_door_open_forever() -> None:
    """Bad data is bad data; it is not a reason to make a room permanently
    joinable, which is what a negative-length window would silently do."""
    window = join_window(START, START - timedelta(hours=3))
    assert window is not None
    assert window.closes_at == START + FALLBACK_DURATION
    assert window.closes_at > window.opens_at


def test_a_session_with_no_start_has_no_window_at_all() -> None:
    assert join_window(None) is None
    assert is_open(START, None) is False

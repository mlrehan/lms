"""Being online is a heartbeat inside a window, not a session that has not expired.

The guarantee worth testing is the one that cannot be demonstrated by closing a
browser: a connection that dies *silently* -- a lost network, a suspended
laptop, a machine powered off -- sends nothing, so nothing marks the person
offline. They fall out of the window instead. These tests move the clock rather
than waiting, so the boundary is checked exactly rather than approximately.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from backend.core.config import RealtimeBackend, RealtimeSettings
from backend.realtime.presence import (
    DEFAULT_WINDOW_SECONDS,
    MemoryPresence,
    build_presence_store,
)


@pytest.fixture()
def clock(monkeypatch):
    """A time source the test moves by hand."""
    now = {"t": 1_000_000.0}
    monkeypatch.setattr("backend.realtime.presence.time.time", lambda: now["t"])
    return now


def run(coro):
    """Drive one coroutine to completion.

    The project has no pytest-asyncio; every other async test here drives a
    loop by hand, so this does the same rather than adding a plugin for four
    methods that never actually await anything in the memory adapter.
    """
    return asyncio.run(coro)


def online_ids(store, **kwargs) -> set[int]:
    return set(run(store.online(**kwargs)))


@pytest.mark.parametrize("window", [DEFAULT_WINDOW_SECONDS, 30])
def test_a_heartbeat_makes_somebody_online(clock, window: int) -> None:
    store = MemoryPresence()
    run(store.touch(7))
    assert online_ids(store, window_seconds=window) == {7}


def test_silence_past_the_window_is_what_marks_somebody_offline(clock) -> None:
    """The case no event can cover: the browser never said goodbye."""
    store = MemoryPresence()
    run(store.touch(7))

    clock["t"] += DEFAULT_WINDOW_SECONDS - 1
    assert online_ids(store) == {7}, "one missed beat must not flicker offline"

    clock["t"] += 2
    assert online_ids(store) == set()


def test_a_beat_inside_the_window_keeps_them_there(clock) -> None:
    store = MemoryPresence()
    run(store.touch(7))
    for _ in range(5):
        clock["t"] += DEFAULT_WINDOW_SECONDS / 2
        run(store.touch(7))
        assert online_ids(store) == {7}


def test_closing_the_last_tab_drops_them_at_once(clock) -> None:
    """The courtesy path. Correctness does not depend on it, but the common
    case should not wait out a minute."""
    store = MemoryPresence()
    run(store.touch(7))
    run(store.drop(7))
    assert online_ids(store) == set()


def test_dropping_somebody_who_was_never_here_is_not_an_error(clock) -> None:
    store = MemoryPresence()
    run(store.drop(999))
    assert online_ids(store) == set()


def test_several_people_are_tracked_apart(clock) -> None:
    store = MemoryPresence()
    run(store.touch(1))
    clock["t"] += DEFAULT_WINDOW_SECONDS - 5
    run(store.touch(2))
    clock["t"] += 10  # 1 is now stale, 2 is not
    assert online_ids(store) == {2}


def test_last_seen_comes_back_with_the_id(clock) -> None:
    store = MemoryPresence()
    run(store.touch(7))
    assert run(store.online())[7] == pytest.approx(clock["t"])


class TestChoosingAnAdapter:
    def test_memory_is_refused_in_a_deployed_environment(self) -> None:
        """Several workers each see only the tabs they happen to hold, so the
        count becomes a fraction that changes with whichever process answers --
        a wrong number that looks plausible."""
        settings = RealtimeSettings(backend=RealtimeBackend.MEMORY)
        with pytest.raises(RuntimeError, match="redis"):
            build_presence_store(settings, deployed=True)

    def test_memory_is_fine_when_one_process_serves_everything(self) -> None:
        settings = RealtimeSettings(backend=RealtimeBackend.MEMORY)
        assert isinstance(build_presence_store(settings, deployed=False), MemoryPresence)

    def test_redis_without_a_url_is_refused_rather_than_guessed(self) -> None:
        settings = RealtimeSettings(backend=RealtimeBackend.REDIS, redis_url="")
        with pytest.raises(RuntimeError, match="REALTIME_REDIS_URL"):
            build_presence_store(settings, deployed=True)


# =============================================================================
# Transitions
# =============================================================================
#
# `touch` is called on every heartbeat -- roughly every twenty-five seconds per
# connected browser. If it reported "something changed" each time, one person
# sitting at their desk would publish an event to every administrator watching
# the dashboard, for ever. So it reports a *transition* and nothing else, and
# that distinction is what makes the presence topic affordable at all.


def test_the_first_touch_is_an_arrival_and_the_next_is_not():
    store = MemoryPresence()
    assert run(store.touch(7)) is True, "the first sighting is an arrival"
    assert run(store.touch(7)) is False, "a heartbeat is not news"
    assert run(store.touch(7)) is False


def test_returning_after_the_window_lapses_is_an_arrival_again():
    """A suspended tab stops sending heartbeats and is counted as gone.

    When it wakes, the dashboards that dropped it have to be told it is back,
    so this must read as an arrival rather than as another heartbeat.
    """
    store = MemoryPresence()
    run(store.touch(7))
    # Backdate the sighting past the window, as a suspended tab would.
    store._seen[7] = time.time() - (DEFAULT_WINDOW_SECONDS + 5)  # noqa: SLF001
    assert run(store.touch(7)) is True


def test_a_clean_departure_is_reported_once():
    store = MemoryPresence()
    run(store.touch(7))
    assert run(store.drop(7)) is True
    # A second close for somebody already gone announces nothing: with several
    # tabs open, the later ones must not each publish a departure.
    assert run(store.drop(7)) is False


def test_dropping_somebody_who_was_never_here_announces_nothing():
    assert run(MemoryPresence().drop(999)) is False

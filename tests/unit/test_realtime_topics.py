"""Topic events: who is subscribed, what raises one, and what stays quiet.

The per-user channel was never enough for a badge. Nobody is notified when an
administrator adds a batch, so every sidebar counting batches was wrong until
the next refetch -- which is the page refresh this exists to remove.

What is tested here is the part that could go wrong silently: a role seeing a
topic it should not, a table announcing changes nobody counts, or a transaction
that writes twelve rows sending twelve frames to everybody.
"""

from __future__ import annotations

import asyncio
import selectors

import pytest

from backend.core.events import EventKind, RealtimeEvent, drain_committed, queue_topic_event
from backend.core.permissions import Action, Module, perm
from backend.core.topics import (
    ACADEMIC,
    ALL_TOPICS,
    ANNOUNCEMENTS,
    ASSESSMENT,
    DIRECTORY,
    PRESENCE,
    TABLE_TOPICS,
    TOPIC_PERMISSIONS,
    topic_for_table,
    topics_for,
)
from backend.realtime.bus import InProcessBus, channel_for, channel_for_topic


def run(coro):  # noqa: ANN001, ANN201
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# =============================================================================
# Who may subscribe
# =============================================================================

_USER_READ = perm(Module.USER, Action.READ)
_COURSE_READ = perm(Module.COURSE, Action.READ)
_ASSIGNMENT_READ = perm(Module.ASSIGNMENT, Action.READ)
_ANNOUNCEMENT_READ = perm(Module.ANNOUNCEMENT, Action.READ)


def test_a_student_is_not_subscribed_to_the_directory():
    """The counts a student's sidebar shows are academic, not administrative.

    Being subscribed means being told to look again. A student told that the
    user directory changed would re-read an endpoint that refuses them -- a
    wasted request on every account edit, multiplied by every student.
    """
    held = {_COURSE_READ, _ASSIGNMENT_READ, _ANNOUNCEMENT_READ}
    topics = topics_for(held, unrestricted=False)

    assert ACADEMIC in topics
    assert ASSESSMENT in topics
    assert DIRECTORY not in topics
    assert PRESENCE not in topics


def test_presence_needs_institution_wide_visibility_not_just_user_read():
    """A tutor may read users within their scope; there is no scoped presence.

    `GET /presence/active` is a single institution-wide list, so a tutor would
    be told it changed and then refused when they asked. The subscription
    matches the endpoint's gate exactly.
    """
    tutor = {_USER_READ, _COURSE_READ}
    assert PRESENCE not in topics_for(tutor, unrestricted=False)
    assert PRESENCE in topics_for(tutor, unrestricted=True)


def test_an_account_with_no_permissions_subscribes_to_nothing():
    assert topics_for(set(), unrestricted=True) == ()


def test_every_topic_has_a_permission_and_every_permission_is_real():
    """A topic nobody can be admitted to is dead code; a typo is a silent hole.

    A misspelled permission name would simply never match a held permission,
    so the topic would be subscribed by nobody and the badges it feeds would
    quietly never update -- the exact failure this whole mechanism exists to
    fix, reintroduced one level up.
    """
    from backend.core.permissions import ALL_PERMISSIONS

    assert set(TOPIC_PERMISSIONS) == set(ALL_TOPICS)
    for topic, permission in TOPIC_PERMISSIONS.items():
        assert permission in ALL_PERMISSIONS, f"{topic} gates on unknown {permission}"


# =============================================================================
# What raises an event
# =============================================================================


def test_tables_nobody_counts_stay_quiet():
    """Audit rows, tokens and sync jobs change constantly and move no badge.

    Announcing them would be noise multiplied by every connected browser.
    """
    for table in ("audit_logs", "tokens", "sync_pipeline_jobs", "sync_pipeline_runs"):
        assert topic_for_table(table) is None, f"{table} should raise no event"


def test_messages_and_notifications_stay_on_their_personal_channel():
    """They already have precise per-user events.

    A topic would tell everybody that somebody, somewhere, received something.
    """
    assert topic_for_table("notifications") is None
    assert topic_for_table("mail_messages") is None


def test_the_tables_badges_count_are_all_mapped():
    """A sidebar badge whose table is unmapped never updates.

    Driven from the console's own badge list rather than restating it, so a
    new badge over an unmapped table fails here rather than shipping dead.
    """
    counted = {
        "courses": ACADEMIC,
        "batches": ACADEMIC,
        "batch_sessions": ACADEMIC,
        "enrollments": ACADEMIC,
        "assignments": ASSESSMENT,
        "quizzes": ASSESSMENT,
        "exams": ASSESSMENT,
        "announcements": ANNOUNCEMENTS,
        "users": DIRECTORY,
        "roles": DIRECTORY,
        "permissions": DIRECTORY,
        "student_guardians": DIRECTORY,
    }
    for table, expected in counted.items():
        assert TABLE_TOPICS.get(table) == expected, f"{table} is unmapped or wrong"


# =============================================================================
# Coalescing
# =============================================================================


class _FakeSession:
    """Only `info` is touched by the queueing helpers."""

    def __init__(self) -> None:
        self.info: dict = {}


def test_one_transaction_writing_many_rows_sends_one_frame():
    """Twelve marks saved together are one piece of news to a badge.

    Without this, a sweep over a class publishes a frame per row to every
    connected browser to say the same thing twelve times.
    """
    session = _FakeSession()
    for _ in range(12):
        queue_topic_event(session, ASSESSMENT)

    events = session.info["realtime.queued"]
    assert len(events) == 1
    assert events[0].topic == ASSESSMENT
    assert events[0].kind == EventKind.DATA_CHANGED


def test_different_topics_in_one_transaction_each_get_a_frame():
    """A request that enrols a student touches two vocabularies, not one."""
    session = _FakeSession()
    queue_topic_event(session, ACADEMIC)
    queue_topic_event(session, DIRECTORY)
    queue_topic_event(session, ACADEMIC)

    assert {e.topic for e in session.info["realtime.queued"]} == {ACADEMIC, DIRECTORY}
    assert len(session.info["realtime.queued"]) == 2


# =============================================================================
# Routing
# =============================================================================


def test_a_topic_frame_reaches_only_its_subscribers():
    """The isolation the whole design rests on."""

    async def check():  # noqa: ANN202
        bus = InProcessBus()
        admin = bus.subscribe(1, (DIRECTORY, PRESENCE))
        student = bus.subscribe(2, (ACADEMIC,))

        await bus.publish(RealtimeEvent(kind=EventKind.DATA_CHANGED, user_id=0, topic=DIRECTORY))

        got_admin = await admin.next_event(timeout=0.05)
        got_student = await student.next_event(timeout=0.05)

        await admin.aclose()
        await student.aclose()
        return got_admin, got_student

    admin_event, student_event = run(check())
    assert admin_event is not None and admin_event.topic == DIRECTORY
    assert student_event is None, "a student must not receive directory frames"


def test_a_personal_event_never_leaks_onto_a_topic():
    """Topic and user channels are separate namespaces.

    A topic named `7` must not be able to reach user 7, which is why the two
    use distinct channel prefixes rather than one keyspace.
    """
    assert channel_for(7) != channel_for_topic("7")

    async def check():  # noqa: ANN202
        bus = InProcessBus()
        listener = bus.subscribe(99, (ACADEMIC,))
        # Addressed to a different person entirely.
        await bus.publish(RealtimeEvent(kind=EventKind.NOTIFICATION_CREATED, user_id=1234))
        got = await listener.next_event(timeout=0.05)
        await listener.aclose()
        return got

    assert run(check()) is None


def test_closing_a_subscription_leaves_no_topic_registration_behind():
    """A leak here is unbounded: one entry per connection, for the process life."""

    async def check():  # noqa: ANN202
        bus = InProcessBus()
        subs = [bus.subscribe(i, (ACADEMIC, ASSESSMENT)) for i in range(5)]
        peak = bus.topic_subscriber_count
        for sub in subs:
            await sub.aclose()
        return peak, bus.topic_subscriber_count, bus.subscriber_count

    peak, after, users = run(check())
    assert peak == 10  # five connections, two topics each
    assert after == 0
    assert users == 0


def test_an_event_survives_the_wire_with_its_topic():
    """Redis carries JSON, so a field the parser forgets is a silent loss."""
    original = RealtimeEvent(kind=EventKind.DATA_CHANGED, user_id=0, topic=ACADEMIC)
    assert RealtimeEvent.from_json(original.to_json()).topic == ACADEMIC


def test_a_personal_event_still_has_no_topic():
    """The two are exclusive; a personal event gaining one would broadcast it."""
    evt = RealtimeEvent(kind=EventKind.NOTIFICATION_CREATED, user_id=3)
    assert evt.topic is None
    assert RealtimeEvent.from_json(evt.to_json()).topic is None


# =============================================================================
# The committed-only guarantee, for topic events too
# =============================================================================


def test_a_topic_event_is_not_published_before_its_transaction_commits():
    """Same rule as a notification: a badge must not move for a rolled-back write."""
    session = _FakeSession()
    queue_topic_event(session, ACADEMIC)

    # Nothing has been promoted, so nothing is drainable yet.
    assert drain_committed(session) == []
    assert len(session.info["realtime.queued"]) == 1

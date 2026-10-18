"""What the server tells a browser, the moment it becomes true.

Three rules shape everything in this module, and each of them is the answer to
a way this could go wrong.

**An event is a hint, not a payload.** It says "your unread count changed", not
what the message says. The reason is `core/privacy.py`: every read path runs
under `set_viewer`, which decides whether this caller may see another person's
email address or even their username. An event is built once, at the moment of
the write, by whoever performed it -- so a payload assembled there would be
assembled for the *wrong viewer*, and would sail past the masking entirely. The
browser is told something changed and re-reads it through the ordinary endpoint,
where the rule still applies.

**Nothing is published until the transaction commits.** A notification is staged
inside the caller's transaction on purpose (see `notification_service.emit`), so
a tray can never announce a grade whose insert rolled back. Publishing eagerly
would reintroduce exactly that bug in its most visible form -- a chime, a badge,
and nothing there when you look. Events are queued on the session and moved to a
"committed" list by SQLAlchemy's own `after_commit`, which fires on commit and
never on rollback.

**An event is addressed to one user.** There is no broadcast channel and no
"everyone in batch X": fan-out happens where the recipients are already being
resolved (`notify_many`, `notify_guardians_of`), under the same audience rules
and the same `MAX_FANOUT` bound. A channel anyone could subscribe to would be an
authorization question this layer is not equipped to answer.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import event
from sqlalchemy.orm import Session

from backend.core.topics import topic_for_table

# The session keys the two lists live under. Namespaced because `session.info`
# is shared with anything else that wants per-session state.
_QUEUED: Final = "realtime.queued"
_COMMITTED: Final = "realtime.committed"
#: Topics already announced by the current transaction, so a request that
#: writes twelve rows of one table still sends one frame.
_TOPICS: Final = "realtime.topics"


class EventKind:
    """The vocabulary. Deliberately small.

    Each name answers "what should the client re-read?", not "what happened":
    a client that has to map twelve verbs onto three queries will get the
    mapping wrong somewhere, and the bug will be an unread badge that does not
    clear.
    """

    #: Something a shared screen counts has changed -- a course, a batch, an
    #: enrolment, an account. Addressed to a *topic* rather than a person,
    #: because nobody is notified when an administrator adds a batch and yet
    #: every sidebar badge counting batches is now wrong. Carries the topic
    #: name and nothing else; see `realtime/topics.py` for why that is safe.
    DATA_CHANGED: Final = "data.changed"

    MESSAGE_RECEIVED: Final = "message.received"
    MESSAGE_UPDATED: Final = "message.updated"
    NOTIFICATION_CREATED: Final = "notification.created"
    #: Sent on connect, so a client can tell "the stream is open" from "the
    #: stream is open and nothing has happened yet" -- which are the same
    #: silence, and only one of them is healthy.
    READY: Final = "ready"
    #: Keeps proxies and load balancers from reaping an idle connection. Not a
    #: real event; clients ignore it.
    PING: Final = "ping"


@dataclass(frozen=True)
class RealtimeEvent:
    """One thing that happened, addressed to one person or to one topic."""

    kind: str
    #: The recipient, for a personal event. `0` when the event is addressed to
    #: a topic instead -- there is no user it belongs to, and `None` would mean
    #: threading an optional through every existing caller to say the same
    #: thing.
    user_id: int
    #: Small, non-confidential context: a count, a title we generated for this
    #: recipient, an id they are already entitled to. Never another person's
    #: name, address, or the body of anything.
    data: dict[str, Any] = field(default_factory=dict)
    #: Set instead of `user_id` for an event everybody holding a permission
    #: should see. Exactly one of the two is meaningful, and `bus.publish`
    #: routes on this field's presence.
    topic: str | None = None
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @staticmethod
    def from_json(raw: str) -> "RealtimeEvent":
        payload = json.loads(raw)
        return RealtimeEvent(
            kind=payload["kind"],
            user_id=payload["user_id"],
            data=payload.get("data") or {},
            topic=payload.get("topic"),
            at=payload.get("at") or datetime.now(UTC).isoformat(),
        )

    def sse(self) -> str:
        """One SSE frame.

        The blank line terminates the event; without it the browser buffers
        indefinitely waiting for the rest, and the symptom is a stream that
        "works" in curl and delivers nothing in a page.
        """
        return f"event: {self.kind}\ndata: {self.to_json()}\n\n"


def queue_event(session: Session, evt: RealtimeEvent) -> None:
    """Stage an event to be published *if* this transaction commits.

    Safe to call from anywhere a write happens, including deep inside a
    service: nothing leaves the process until the data it describes is real.
    """
    session.info.setdefault(_QUEUED, []).append(evt)


def drain_committed(session: Session) -> list[RealtimeEvent]:
    """Take the events whose transaction actually committed."""
    events: list[RealtimeEvent] = session.info.get(_COMMITTED) or []
    session.info[_COMMITTED] = []
    return events


def _promote(session: Session) -> None:
    queued: list[RealtimeEvent] = session.info.get(_QUEUED) or []
    if queued:
        session.info.setdefault(_COMMITTED, []).extend(queued)
        session.info[_QUEUED] = []


def _discard(session: Session) -> None:
    session.info[_QUEUED] = []


def queue_topic_event(session: Session, topic: str) -> None:
    """Stage one `data.changed` for a topic, at most once per transaction.

    Coalesced on purpose. A single request can touch a dozen rows of the same
    table -- an enrolment sweep, a batch of marks -- and each one of those is
    the *same* news to a badge: "the number you are showing is out of date."
    Sending twelve frames to every connected browser to say it once is the
    cheapest mistake available here and the easiest to avoid.
    """
    staged: set[str] = session.info.setdefault(_TOPICS, set())
    if topic in staged:
        return
    staged.add(topic)
    queue_event(session, RealtimeEvent(kind=EventKind.DATA_CHANGED, user_id=0, topic=topic))


def _table_of(obj: object) -> str | None:
    table = getattr(type(obj), "__tablename__", None)
    return table if isinstance(table, str) else None


def _detect_changes(session: Session, _flush_context: object = None) -> None:
    """Queue a topic event for every table this transaction wrote to.

    **Bound to `after_flush`, and that choice is the whole correctness of this
    hook.** The obvious place is `before_commit`, and it is wrong: a service
    that calls `flush()` -- which nearly all of them do, to obtain an id before
    returning -- has already emptied `session.new` by the time the commit
    begins. Measured, after the live run showed a course being created and
    announcing nothing:

        with an explicit flush:  after_flush sees 1, before_commit sees 0
        without a flush:         after_flush sees 1, before_commit sees 1

    So `before_commit` catches exactly the case a test writes and none of the
    cases the application performs. `after_flush` sees both, because the commit
    itself triggers a final implicit flush when one is needed.

    Flushing is not committing, so this only *stages* the event;
    `after_commit` promotes it and `after_rollback` discards it, exactly as for
    a notification. A flush that is later rolled back therefore announces
    nothing.

    **Here rather than in each service, deliberately.** Forty call sites would
    each need to remember to announce themselves, and the failure mode of
    forgetting is invisible: a screen that quietly never updates, found by a
    user months later. One hook over the session covers every write in the
    application, including ones not yet written, and a table nobody mapped
    stays silent rather than guessing.
    """
    for bucket in (session.new, session.dirty, session.deleted):
        for obj in bucket:
            table = _table_of(obj)
            if table is None:
                continue
            topic = topic_for_table(table)
            if topic is not None:
                queue_topic_event(session, topic)


def _clear_topics(session: Session) -> None:
    session.info[_TOPICS] = set()


def install_listeners() -> None:
    """Bind the promote/discard hooks to every session in the process.

    Called once at import of this module. `after_commit` is the only signal
    that means "the rows are durable"; `after_rollback` and its soft-rollback
    sibling are what stop a failed request announcing itself.
    """
    if getattr(install_listeners, "_installed", False):
        return
    event.listen(Session, "after_flush", _detect_changes)
    event.listen(Session, "after_commit", _promote)
    event.listen(Session, "after_commit", _clear_topics)
    event.listen(Session, "after_rollback", _discard)
    event.listen(Session, "after_rollback", _clear_topics)
    # A nested/soft rollback (a flush that failed inside a still-open
    # transaction) does not fire `after_rollback`, and the events staged before
    # it describe rows that no longer exist.
    event.listen(Session, "after_soft_rollback", lambda s, _ctx: _discard(s))
    event.listen(Session, "after_soft_rollback", lambda s, _ctx: _clear_topics(s))
    install_listeners._installed = True  # type: ignore[attr-defined]


install_listeners()

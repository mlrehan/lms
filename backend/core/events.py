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

# The session keys the two lists live under. Namespaced because `session.info`
# is shared with anything else that wants per-session state.
_QUEUED: Final = "realtime.queued"
_COMMITTED: Final = "realtime.committed"


class EventKind:
    """The vocabulary. Deliberately small.

    Each name answers "what should the client re-read?", not "what happened":
    a client that has to map twelve verbs onto three queries will get the
    mapping wrong somewhere, and the bug will be an unread badge that does not
    clear.
    """

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
    """One thing that happened, addressed to one person."""

    kind: str
    user_id: int
    #: Small, non-confidential context: a count, a title we generated for this
    #: recipient, an id they are already entitled to. Never another person's
    #: name, address, or the body of anything.
    data: dict[str, Any] = field(default_factory=dict)
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


def install_listeners() -> None:
    """Bind the promote/discard hooks to every session in the process.

    Called once at import of this module. `after_commit` is the only signal
    that means "the rows are durable"; `after_rollback` and its soft-rollback
    sibling are what stop a failed request announcing itself.
    """
    if getattr(install_listeners, "_installed", False):
        return
    event.listen(Session, "after_commit", _promote)
    event.listen(Session, "after_rollback", _discard)
    # A nested/soft rollback (a flush that failed inside a still-open
    # transaction) does not fire `after_rollback`, and the events staged before
    # it describe rows that no longer exist.
    event.listen(Session, "after_soft_rollback", lambda s, _ctx: _discard(s))
    install_listeners._installed = True  # type: ignore[attr-defined]


install_listeners()

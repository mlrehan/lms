"""The live connection a signed-in browser holds open.

**Why this route authenticates by hand instead of using `CurrentUser`.**
FastAPI closes a `yield` dependency *after* the response body has finished --
which for a streaming response means when the stream ends, minutes or half an
hour later. `DBSession` is such a dependency, so the ordinary auth chain would
pin one pooled database connection per open browser tab. With a default pool
that is a handful of tabs before every other request in the process starts
waiting for a connection. So the caller is resolved inside a session this module
opens and closes itself, before a single byte of the stream is written, and the
stream then holds no database connection at all.

**Why SSE and not a WebSocket.** This traffic is one-directional: the server
tells the browser something changed and the browser re-reads it over the normal
API. A WebSocket would add a second protocol, a second auth path and a second
thing for a proxy to get wrong, in exchange for an upstream channel nothing
needs. SSE is an ordinary HTTP GET, so it inherits the console's BFF proxy, its
cookie-based auth and its error handling unchanged.
"""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.api.deps import JWTDep, resolve_permissions
from backend.core.config import Settings
from backend.core.context import user_id_ctx
from backend.core.errors import AuthenticationError
from backend.core.events import EventKind, RealtimeEvent
from backend.core.logging import get_logger
from backend.core.permissions import Action, Module, perm
from backend.core.topics import PRESENCE, topics_for
from backend.db.manager import DatabaseManager
from backend.repositories.user import UserRepository

router = APIRouter(tags=["Realtime"])
logger = get_logger(__name__)

_bearer = HTTPBearer(auto_error=False)

# Either is enough to have something to be told about. Gating on both would shut
# out a role that holds one and not the other, and gating on neither would let
# an account with no inbox at all hold a connection open.
_AUDIENCE = (perm(Module.MESSAGE, Action.READ), perm(Module.NOTIFICATION, Action.READ))

#: Institution-wide visibility. Decides the `presence` topic, which has no
#: per-scope version to offer a caller who lacks it.
_VIEW_ALL = perm(Module.INSTITUTION, Action.VIEW_ALL)


class _Listener:
    """The authenticated identity behind one stream. No ORM objects.

    Detached instances would be bound to a session this route has deliberately
    closed, and touching any unloaded attribute mid-stream would raise long
    after the request looked successful.
    """

    __slots__ = ("user_id", "public_id", "topics")

    def __init__(self, user_id: int, public_id: str, topics: tuple[str, ...] = ()) -> None:
        self.user_id = user_id
        self.public_id = public_id
        #: Resolved from this caller's permissions while the session was still
        #: open, and fixed for the life of the stream. A permission revoked
        #: mid-stream therefore keeps delivering *hints* until the connection
        #: turns over, which is harmless: a hint carries no data, and the
        #: endpoint the client then calls re-checks the permission properly.
        self.topics = topics


async def _identify(
    request: Request,
    jwt_service: JWTDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> _Listener:
    """Authenticate, authorise, and release the database connection.

    A plain `async def` dependency, not a generator: it owns its session for the
    duration of this function and nothing longer. See the module docstring.
    """
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Authentication required.")

    claims = jwt_service.verify_access_token(credentials.credentials)
    db: DatabaseManager = request.app.state.db

    async with db.session_factory() as session:
        user = await UserRepository(session).get_by_public_id_with_roles(claims.subject)

        # Reported identically to a bad token, for the same reason
        # `get_current_user` does it: telling a bearer which of "no such
        # account", "suspended" and "locked" applies describes the account to
        # whoever holds a stolen token.
        if user is None or not user.is_login_permitted or user.is_locked_out:
            raise AuthenticationError("Authentication required.")

        held = resolve_permissions(user)
        if not held.intersection(_AUDIENCE):
            raise AuthenticationError("Authentication required.")

        listener = _Listener(
            user.id,
            str(user.public_id),
            topics_for(held, unrestricted=_VIEW_ALL in held),
        )

    user_id_ctx.set(listener.public_id)
    return listener


def _settings(request: Request) -> Settings:
    from backend.core.config import get_settings

    return get_settings()


async def _announce_presence(bus: object) -> None:
    """Tell every dashboard that the online list moved.

    Best effort, and deliberately silent on failure: this runs inside a live
    stream, and an unreachable bus must cost a late presence update rather than
    tear down the connection carrying everybody's notifications.

    **A departure detected by expiry raises nothing**, and cannot: nobody is
    executing code at the moment a window lapses. A browser that crashed is
    discovered by the next read, which is why the dashboard keeps a slow poll
    underneath this rather than relying on events alone.
    """
    try:
        await bus.publish(  # type: ignore[attr-defined]
            RealtimeEvent(kind=EventKind.DATA_CHANGED, user_id=0, topic=PRESENCE)
        )
    except Exception:  # noqa: BLE001
        logger.warning("Presence announcement failed", exc_info=True)


@router.get(
    "/realtime/stream",
    summary="Live events for the signed-in user",
    response_class=StreamingResponse,
)
async def realtime_stream(
    request: Request,
    listener: Annotated[_Listener, Depends(_identify)],
    settings: Annotated[Settings, Depends(_settings)],
) -> StreamingResponse:
    """Server-sent events for this caller, and no one else.

    The channel is derived from the authenticated user id, never from anything
    in the request: there is no parameter here to point at somebody else's
    stream, which is the only reason a subscription needs no authorization
    check of its own.

    Every event is a *hint* -- a kind and a count. The client re-reads the
    actual content through the ordinary endpoints, so the privacy rules in
    `core/privacy.py` still decide what it sees.
    """
    bus = getattr(request.app.state, "event_bus", None)
    realtime = settings.realtime

    if bus is None:
        # An honest, immediately-closing stream rather than a 404: the client's
        # fallback is the polling it already does, and a stream that opens and
        # ends is something it handles. A 404 would look like a deploy error.
        async def disabled() -> AsyncIterator[bytes]:
            yield b": realtime disabled\n\n"

        return StreamingResponse(disabled(), media_type="text/event-stream", headers=_HEADERS)

    live: dict[int, int] = request.app.state.__dict__.setdefault("realtime_live", {})
    if live.get(listener.user_id, 0) >= realtime.max_streams_per_user:
        async def too_many() -> AsyncIterator[bytes]:
            # `retry` is honoured by EventSource, so a client that hit the cap
            # backs off for a minute instead of reconnecting in a tight loop
            # and holding the cap open forever.
            yield b"retry: 60000\n: too many open streams\n\n"

        logger.warning("Realtime stream cap reached", extra={"user_id": listener.user_id})
        return StreamingResponse(too_many(), media_type="text/event-stream", headers=_HEADERS)

    live[listener.user_id] = live.get(listener.user_id, 0) + 1
    subscription = bus.subscribe(listener.user_id, listener.topics)
    # Presence is a side effect of this stream: holding it open *is* being
    # at your desk, so no polling endpoint and no client code are needed.
    presence = getattr(request.app.state, "presence", None)
    deadline = time.monotonic() + realtime.max_stream_seconds

    async def stream() -> AsyncIterator[bytes]:
        try:
            # Sent before anything else so a client can distinguish "connected,
            # nothing has happened" from "never connected" -- both of which
            # otherwise look like an idle socket.
            yield RealtimeEvent(kind=EventKind.READY, user_id=listener.user_id).sse().encode()
            if presence is not None and await presence.touch(listener.user_id):
                # An arrival, not a heartbeat. Published to the topic so every
                # dashboard showing "who is online" updates at once instead of
                # waiting out its poll.
                await _announce_presence(bus)

            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    # Ending deliberately, with a reconnect hint: EventSource
                    # reopens, and the connection lands on whatever worker is
                    # current -- which is what makes a rolling deploy drain.
                    yield b"retry: 1000\nevent: reconnect\ndata: {}\n\n"
                    return

                event = await subscription.next_event(
                    timeout=min(realtime.heartbeat_seconds, remaining)
                )

                if event is None:
                    # A comment frame. Keeps intermediaries from reaping an idle
                    # connection, and is the only way this end learns the socket
                    # is gone -- the write fails and the generator is closed.
                    yield b": ping\n\n"
                    if await request.is_disconnected():
                        return
                    continue

                yield event.sse().encode()
        except asyncio.CancelledError:
            # The client went away. Normal, and not worth a log line per tab.
            raise
        finally:
            await subscription.aclose()
            # A courtesy, so closing the last tab shows up at once instead of
            # at the end of the window. Nothing depends on it arriving: a
            # crash sends no `finally` either.
            if presence is not None and live.get(listener.user_id, 1) <= 1:
                if await presence.drop(listener.user_id):
                    await _announce_presence(bus)
            remaining_for_user = live.get(listener.user_id, 1) - 1
            if remaining_for_user <= 0:
                live.pop(listener.user_id, None)
            else:
                live[listener.user_id] = remaining_for_user

    return StreamingResponse(stream(), media_type="text/event-stream", headers=_HEADERS)


_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    # nginx buffers proxied responses by default, which turns a stream into a
    # single delivery at the end. This header is how it is told not to, and
    # without it the feature looks broken only once it is behind a proxy.
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}

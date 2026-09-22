"""Does a push actually leave the building, and is it encrypted when it does?

A browser is needed to *subscribe*; nothing in that step is ours. What is ours
is everything after: signing a VAPID assertion, encrypting the payload against
the device's public key, and -- the part most implementations get wrong --
noticing that a push service has said the device is gone and acting on it.

So this stands up a real HTTP server that plays the part of Mozilla's or
Google's push endpoint and points a real subscription row at it. That makes the
send a real network call through `pywebpush`, which is the only way to find out
whether the key format this codebase generates is one the library accepts. A
mocked `webpush()` would assert that I called my own wrapper.
"""

from __future__ import annotations

import asyncio
import base64
import os
import random
import selectors
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import select, text

from backend.core.config import PushSettings, get_settings
from backend.db.manager import DatabaseManager
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.push import PushSubscription
from backend.services.push_service import PushService
from backend.utils.enums import UserStatus


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _browser_keys() -> tuple[str, str]:
    """What a browser hands over at subscribe time: its public point and a
    random auth secret. Real key material, so the encryption step is real."""
    key = ec.generate_private_key(ec.SECP256R1())
    p256dh = _b64(key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))
    return p256dh, _b64(os.urandom(16))


def _vapid() -> PushSettings:
    key = ec.generate_private_key(ec.SECP256R1())
    return PushSettings(
        vapid_public_key=_b64(
            key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        ),
        vapid_private_key=_b64(key.private_numbers().private_value.to_bytes(32, "big")),
        subject="mailto:tests@example.test",
    )


class _PushService:
    """Stands in for the browser vendor's push endpoint."""

    def __init__(self) -> None:
        self.requests: list[tuple[dict[str, str], bytes]] = []
        self.status = 201
        handler = self._handler()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/push/{random.randint(1000, 9999)}"

    def _handler(self):  # noqa: ANN202
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("content-length") or 0)
                body = self.rfile.read(length)
                outer.requests.append((dict(self.headers.items()), body))
                self.send_response(outer.status)
                self.end_headers()

            def log_message(self, *args) -> None:  # noqa: ANN002, D102
                pass  # the test's own output is the interesting one

        return Handler

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture()
def env():
    tag = f"push{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="push-tests")
    service = _PushService()

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s, *, endpoint: str):  # noqa: ANN001, ANN202
        role = (await s.execute(select(Role).where(Role.name == "STUDENT"))).scalar_one()
        user = User(
            username=f"{tag}.stu", slug=f"{tag}-stu", email=f"{tag}@t.test",
            hashed_password="x", status=UserStatus.ACTIVE, roles=[role],
        )
        s.add(user)
        await s.flush()
        p256dh, auth = _browser_keys()
        s.add(PushSubscription(
            user_id=user.id, endpoint=endpoint, p256dh=p256dh, auth=auth,
            user_agent="Tests/1.0", created_at=datetime.now(UTC),
        ))
        await s.flush()
        return user

    ns = type("Env", (), dict(
        tag=tag, run=staticmethod(run), build=staticmethod(build),
        push=service, settings=_vapid(),
    ))
    try:
        yield ns
    finally:
        service.close()

        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"u": f"{tag}.%"}
                await s.execute(text("DELETE FROM push_subscriptions WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM users WHERE username LIKE :u"), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _send(env, *, status: int = 201) -> tuple[int, int]:
    """Send one push; return (delivered, subscriptions still stored)."""
    env.push.status = status
    endpoint = env.push.url

    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            user = await env.build(s, endpoint=endpoint)
            service = PushService(s, env.settings)
            delivered = await service.send_to_user(
                user.id, service.payload(title="New message", body="Open the LMS.", url="/x", tag="t")
            )
            await s.flush()
            remaining = len(await service.list_for(user.id))
            return delivered, remaining
        return go()

    return env.run(f)


# --------------------------------------------------------------- delivery ---


def test_a_push_reaches_the_endpoint(env) -> None:
    delivered, _ = _send(env)
    assert delivered == 1
    assert len(env.push.requests) == 1


def test_it_is_signed_so_the_push_service_knows_who_sent_it(env) -> None:
    """VAPID is the whole reason a push service will accept anything at all;
    without this header the send is rejected by every real one."""
    _send(env)
    headers, _ = env.push.requests[0]
    lowered = {k.lower(): v for k, v in headers.items()}
    assert "authorization" in lowered
    assert lowered["authorization"].lower().startswith("vapid")


def test_the_payload_is_encrypted_and_not_readable_in_transit(env) -> None:
    """The push service relays a message it cannot read. If the title appeared
    in the body, every intermediary would be reading our notifications."""
    _send(env)
    headers, body = env.push.requests[0]
    lowered = {k.lower(): v for k, v in headers.items()}
    assert lowered.get("content-encoding") == "aes128gcm"
    assert b"New message" not in body
    assert body  # and something was actually sent


def test_a_gone_device_is_forgotten(env) -> None:
    """410 is the only reliable signal that a subscription is dead -- a browser
    that clears its site data tells us nothing. Ignoring it means pushing to a
    dead endpoint on every notification, for ever."""
    delivered, remaining = _send(env, status=410)
    assert delivered == 0
    assert remaining == 0


def test_a_transient_failure_keeps_the_device(env) -> None:
    """The mirror of the test above, so "forgotten" cannot be passing because
    every failure deletes. A push service having a bad minute is not a reason
    to unsubscribe somebody's phone."""
    delivered, remaining = _send(env, status=503)
    assert delivered == 0
    assert remaining == 1


# ------------------------------------------------------- configuration off ---


def test_nothing_is_sent_when_no_keys_are_configured(env) -> None:
    """The deployment default. A send that quietly no-ops is right here; the
    console hides the control rather than offering one that does nothing."""
    endpoint = env.push.url

    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            user = await env.build(s, endpoint=endpoint)
            service = PushService(s, PushSettings())  # no VAPID keys
            return await service.send_to_user(user.id, "{}")
        return go()

    assert env.run(f) == 0
    assert env.push.requests == []


# ------------------------------------------------------------- ownership ---


def test_a_device_registered_again_moves_to_its_new_owner(env) -> None:
    """An endpoint identifies a browser profile. The same one arriving under a
    second account means the device changed hands, and leaving the old row
    would keep delivering the previous person's notifications to it."""
    endpoint = env.push.url

    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            first = await env.build(s, endpoint=endpoint)
            role = (await s.execute(select(Role).where(Role.name == "STUDENT"))).scalar_one()
            second = User(
                username=f"{env.tag}.two", slug=f"{env.tag}-two", email=f"{env.tag}.two@t.test",
                hashed_password="x", status=UserStatus.ACTIVE, roles=[role],
            )
            s.add(second)
            await s.flush()

            p256dh, auth = _browser_keys()
            service = PushService(s, env.settings)
            await service.register(
                user_id=second.id, endpoint=endpoint, p256dh=p256dh, auth=auth, user_agent=None
            )
            await s.flush()
            return len(await service.list_for(first.id)), len(await service.list_for(second.id))
        return go()

    assert env.run(f) == (0, 1)


def test_you_cannot_unsubscribe_a_device_that_is_not_yours(env) -> None:
    """A push endpoint travels in every subscribe call and is not a secret, so
    an unscoped delete would let anyone who had seen one silence that device."""
    endpoint = env.push.url

    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            owner = await env.build(s, endpoint=endpoint)
            service = PushService(s, env.settings)
            removed = await service.unregister(user_id=owner.id + 999_999, endpoint=endpoint)
            await s.flush()
            return removed, len(await service.list_for(owner.id))
        return go()

    assert env.run(f) == (False, 1)

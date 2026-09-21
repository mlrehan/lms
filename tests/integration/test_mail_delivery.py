"""The email copies: what is sent, to whom, and -- as important -- what is never in it.

A tiny SMTP server on localhost records every message it is handed, so these tests read the real bytes the
sender produced rather than a mock's idea of them. Nothing here can reach a real mail server.
"""

from __future__ import annotations

import asyncio
import email
import random
import selectors
import threading
import uuid
from datetime import datetime, timezone
from email import policy

import pytest
from pydantic import SecretStr
from sqlalchemy import select, text

from backend.core.config import MailSettings, get_settings
from backend.db.manager import DatabaseManager
from backend.integrations.smtp import SmtpMailer
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.mail import MailAttachment, MailMessage, MailRecipient
from backend.services.mail_delivery import deliver_message
from backend.storage import get_storage
from backend.utils.enums import UserStatus


FIRST = {"sender": "Sonia", "to": "Alice", "cc": "Carol", "bcc": "Bruno", "bounce": "Boris", "blank": "Blanca"}
BY_FIRST = {v.lower(): k for k, v in FIRST.items()}


class SmtpSink:
    """Accepts mail on 127.0.0.1 and remembers it. An address containing "bounce" is refused with a 550."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, list[str], bytes]] = []
        self.port = 0
        self._loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "SmtpSink":
        self._thread.start()
        self._ready.wait(5)
        return self

    def stop(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(5)

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        server = self._loop.run_until_complete(asyncio.start_server(self._handle, "127.0.0.1", 0))
        self.port = server.sockets[0].getsockname()[1]
        self._ready.set()
        self._loop.run_forever()
        server.close()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async def say(line: str) -> None:
            writer.write((line + "\r\n").encode())
            await writer.drain()

        await say("220 sink ready")
        mail_from, rcpts = "", []
        while True:
            line = (await reader.readline()).decode("latin-1").strip()
            if not line:
                break
            verb = line.split(" ", 1)[0].upper()
            if verb in ("EHLO", "HELO"):
                await say("250 sink")
            elif verb == "MAIL":
                mail_from, rcpts = line.split(":", 1)[1].strip(), []
                await say("250 ok")
            elif verb == "RCPT":
                address = line.split(":", 1)[1].strip()
                if "bounce" in address.lower():
                    await say("550 no such user")
                else:
                    rcpts.append(address.strip("<>"))
                    await say("250 ok")
            elif verb == "DATA":
                await say("354 go")
                data = b""
                while True:
                    chunk = await reader.readline()
                    if chunk in (b".\r\n", b""):
                        break
                    data += chunk[1:] if chunk.startswith(b"..") else chunk
                self.messages.append((mail_from, rcpts, data))
                await say("250 queued")
            elif verb in ("RSET", "NOOP"):
                await say("250 ok")
            elif verb == "QUIT":
                await say("221 bye")
                break
            else:
                await say("502 not implemented")
        writer.close()

    def parsed(self) -> list[tuple[list[str], email.message.EmailMessage]]:
        return [(rcpts, email.message_from_bytes(raw, policy=policy.default)) for _, rcpts, raw in self.messages]  # type: ignore[misc]


@pytest.fixture()
def env():
    tag = f"md{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="mail-delivery-tests")
    sink = SmtpSink().start()
    ids: dict[str, str] = {}
    emails: dict[str, str] = {}

    def settings(**kw):  # noqa: ANN202
        base = dict(enabled=True, server="127.0.0.1", port=sink.port, tls=False, ssl=False, username="", password=SecretStr(""), MAIL_FROM="noreply@lms.test", from_name="The LMS", suppress_send=False, app_url="https://lms.example")
        return MailSettings(**{**base, **kw})

    async def build(subject: str = "Term dates", body_html: str = "<p>See you <b>Monday</b>.</p>", with_bounce: bool = False, no_address: bool = False, attach: bytes | None = None) -> str:
        async with db.session_factory.begin() as s:
            role = (await s.execute(select(Role).where(Role.name == "STUDENT"))).scalar_one()

            def person(key: str, address: str | None = None) -> User:
                e = address if address is not None else f"{tag}.{key}@t.test"
                emails[key] = e
                return User(username=f"{tag}.{key}", slug=f"{tag}-{key}", email=e, first_name=FIRST[key], last_name=tag, hashed_password="x", status=UserStatus.ACTIVE, roles=[role])

            sender, to, cc, bcc = person("sender"), person("to"), person("cc"), person("bcc")
            extra = [person("bounce", f"{tag}.bounce@t.test")] if with_bounce else []
            blank = [person("blank", "")] if no_address else []
            s.add_all([sender, to, cc, bcc, *extra, *blank])
            await s.flush()
            m = MailMessage(sender_id=sender.id, thread_id=uuid.uuid4(), subject=subject, body_html=body_html, body_text="See you Monday.", is_draft=False,
                            sent_at=datetime.now(timezone.utc), email_copy_requested=True, recipients=[], attachments=[])
            s.add(m)
            await s.flush()
            for user, kind in [(to, "TO"), (cc, "CC"), (bcc, "BCC"), *[(u, "TO") for u in extra], *[(u, "TO") for u in blank]]:
                s.add(MailRecipient(message_id=m.id, user_id=user.id, kind=kind))
            if attach is not None:
                key = f"mail/test/{uuid.uuid4().hex}/notes.txt"
                await get_storage().save(key, attach, content_type="text/plain")
                s.add(MailAttachment(message_id=m.id, uploader_id=sender.id, filename="notes.txt", content_type="text/plain", size=len(attach), storage_key=key))
            await s.flush()
            ids["m"] = str(m.public_id)
            return str(m.public_id)

    def run(coro):  # noqa: ANN001, ANN202
        return loop.run_until_complete(coro)

    def deliver(public_id: str, **kw):  # noqa: ANN202
        s = settings(**kw)
        run(deliver_message(db.session_factory, uuid.UUID(public_id), settings=s, mailer=SmtpMailer(s)))

    def state():  # noqa: ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory() as s:
                m = (await s.execute(select(MailMessage).where(MailMessage.public_id == uuid.UUID(ids["m"])))).scalar_one()
                return {BY_FIRST[r.user.first_name.lower()]: (r.email_status, r.email_error) for r in m.recipients}, m.email_copy_status
        return run(go())

    ns = type("E", (), dict(tag=tag, sink=sink, emails=emails, build=staticmethod(lambda **kw: run(build(**kw))), deliver=staticmethod(deliver), state=staticmethod(state)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                users = "SELECT id FROM users WHERE username LIKE :u"
                await s.execute(text(f"DELETE FROM mail_messages WHERE sender_id IN ({users})"), {"u": f"{tag}.%"})
                await s.execute(text(f"DELETE FROM user_roles WHERE user_id IN ({users})"), {"u": f"{tag}.%"})
                await s.execute(text("DELETE FROM users WHERE username LIKE :u"), {"u": f"{tag}.%"})
        run(cleanup())
        run(db.dispose())
        sink.stop()
        loop.close()


def _body_text(msg) -> str:  # noqa: ANN001
    part = msg.get_body(preferencelist=("plain",))
    return part.get_content() if part else ""


def test_each_recipient_gets_their_own_email_addressed_only_to_them(env) -> None:
    mid = env.build()
    env.deliver(mid)
    mails = {rcpts[0]: (rcpts, msg) for rcpts, msg in env.sink.parsed() if len(rcpts) == 1}
    assert len(env.sink.messages) == 4                                     # to, cc, bcc + the sender's copy
    for key in ("to", "cc", "bcc"):
        rcpts, msg = mails[env.emails[key]]
        assert rcpts == [env.emails[key]] and env.emails[key] in msg["To"] and msg["Cc"] is None and msg["Bcc"] is None
    statuses, copy = env.state()
    assert {k: v[0] for k, v in statuses.items()} == {"to": "SENT", "cc": "SENT", "bcc": "SENT"} and copy == "SENT"


def test_the_senders_email_address_is_in_nobody_elses_email(env) -> None:
    env.deliver(env.build())
    for rcpts, msg in env.sink.parsed():
        if rcpts == [env.emails["sender"]]:
            continue                                                       # the sender's own copy is addressed to them
        assert env.emails["sender"].encode() not in msg.as_bytes()
        assert msg["Reply-To"] is None and msg["From"].endswith("<noreply@lms.test>") and "The LMS" in msg["From"]


def test_bcc_is_hidden_in_every_email_but_the_senders_copy(env) -> None:
    env.deliver(env.build())
    for rcpts, msg in env.sink.parsed():
        body = _body_text(msg)
        if rcpts == [env.emails["sender"]]:
            assert f"Bcc: Bruno {env.tag}" in body                          # the sender's copy says who was Bcc'd
        else:
            bruno_is_the_recipient = rcpts == [env.emails["bcc"]]
            # Nobody's email says who was Bcc'd; Bruno's own only carries his name in the To header, addressed to him.
            assert "Bcc:" not in body and (bruno_is_the_recipient or f"Bruno {env.tag}" not in msg.as_string())
            assert f"To: Alice {env.tag}" in body and f"Cc: Carol {env.tag}" in body   # names, never addresses
        if rcpts != [env.emails["sender"]]:
            assert f"Sonia {env.tag}" in _body_text(msg)                   # everyone else is told who it is from, by name


def test_the_body_and_a_reply_pointer_are_in_the_email(env) -> None:
    env.deliver(env.build())
    rcpts, msg = next((r, m) for r, m in env.sink.parsed() if r == [env.emails["to"]])
    assert "See you Monday." in _body_text(msg) and "https://lms.example/messages" in _body_text(msg)
    html_part = msg.get_body(preferencelist=("html",)).get_content()
    assert "<b>Monday</b>" in html_part and msg["Subject"] == "Term dates"


def test_a_refused_address_fails_alone_and_says_so(env) -> None:
    env.deliver(env.build(with_bounce=True))
    statuses, copy = env.state()
    assert statuses["bounce"][0] == "FAILED" and "refused" in statuses["bounce"][1]
    assert statuses["to"][0] == statuses["cc"][0] == statuses["bcc"][0] == "SENT" and copy == "SENT"


def test_somebody_without_an_address_is_skipped_with_a_reason(env) -> None:
    env.deliver(env.build(no_address=True))
    assert env.state()[0]["blank"] == ("SKIPPED", "No email address on file.")


def test_with_delivery_switched_off_nothing_is_sent_and_everything_is_marked(env) -> None:
    env.deliver(env.build(), enabled=False)
    statuses, copy = env.state()
    assert env.sink.messages == [] and copy == "SKIPPED"
    assert all(v == ("SKIPPED", "Email delivery is switched off.") for v in statuses.values())


def test_a_smtp_server_that_is_down_marks_failures_and_does_not_raise(env) -> None:
    env.deliver(env.build(), port=1)                                        # nothing listens on port 1
    statuses, copy = env.state()
    assert all(v[0] == "FAILED" for v in statuses.values()) and copy == "FAILED"


def test_a_subject_with_a_line_break_cannot_add_a_header(env) -> None:
    env.deliver(env.build(subject="Hello\r\nBcc: victim@example.com"))
    for _, msg in env.sink.parsed():
        assert msg["Bcc"] is None and len(msg.get_all("Subject")) == 1
        assert str(msg["Subject"]).replace("Copy: ", "").startswith("Hello")


def test_an_attachment_travels_with_the_email(env) -> None:
    env.deliver(env.build(attach=b"lecture notes"))
    _, msg = next((r, m) for r, m in env.sink.parsed() if r == [env.emails["to"]])
    files = [(p.get_filename(), p.get_content()) for p in msg.iter_attachments()]
    assert files == [("notes.txt", "lecture notes")]


def test_delivering_twice_does_not_email_twice(env) -> None:
    mid = env.build()
    env.deliver(mid)
    env.deliver(mid)
    assert len(env.sink.messages) == 4          # three recipients and the sender's copy, once each

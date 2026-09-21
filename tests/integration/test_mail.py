"""Internal mail over real HTTP: who may write to whom, Cc/Bcc, sanitising, threads, attachments, per-side removal."""

from __future__ import annotations

import asyncio
import random
import selectors
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.db.manager import DatabaseManager
from backend.main import app
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.security.password import hash_password
from backend.utils.enums import CourseStatus, EnrollmentStatus, Platforms, UserStatus

PASSWORD = "Mail!Test2026xx"


@pytest.fixture()
def world(monkeypatch):  # noqa: ANN001, ANN201
    # Delivery is exercised on its own (test_mail_delivery); here nothing may ever try to send a real email.
    async def no_delivery(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        return None

    monkeypatch.setattr("backend.api.v1.messages.deliver_message", no_delivery)

    tag = f"ml{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="mail-tests")
    people: dict[str, dict] = {}
    tokens: dict[str, str] = {}

    async def build() -> None:
        async with db.session_factory.begin() as s:
            roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

            def person(key: str, role: str) -> User:
                email = f"{tag}.{key}@t.test"
                people[key] = {"email": email, "name": f"{key.title()} {tag}"}
                return User(username=email, slug=f"{tag}-{key}", email=email, first_name=key.title(), last_name=tag, hashed_password=hash_password(PASSWORD),
                            status=UserStatus.ACTIVE, can_login=True, mobile=f"+4477{random.randint(10000000, 99999999)}", roles=[roles[role]])

            u = {k: person(k, r) for k, r in [("admin", "ADMIN"), ("tutora", "TUTOR"), ("tutorb", "TUTOR"), ("stua", "STUDENT"), ("stub", "STUDENT"), ("stuc", "STUDENT")]}
            course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
            course.batches, course.resources, course.tags, course.tutors = [], [], [], []
            s.add_all([*u.values(), course])
            await s.flush()
            now = datetime.now(timezone.utc)
            batches = {}
            for code, tutor in (("A", u["tutora"]), ("B", u["tutorb"])):
                b = Batch(batch_code=f"{tag}-{code}", course_id=course.id, start_date=date.today(), end_date=date.today() + timedelta(days=30), is_active=True, capacity=10)
                b.sessions, b.enrollments, b.student_reviews = [], [], []
                s.add(b)
                await s.flush()
                sess = BatchSession(batch_id=b.id, tutor_id=tutor.id, session_start_time=now + timedelta(days=1), session_end_time=now + timedelta(days=1, hours=1),
                                    duration_minutes=60, platform=Platforms.Zoom)
                sess.attendances = []
                s.add(sess)
                batches[code] = b
            await s.flush()
            for stu, code in (("stua", "A"), ("stub", "A"), ("stuc", "B")):
                s.add(Enrollments(batch_id=batches[code].id, student_id=u[stu].id, enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
            await s.flush()
            for k, v in u.items():
                people[k]["public_id"] = str(v.public_id)

    loop.run_until_complete(build())
    lifespan = app.router.lifespan_context(app)
    loop.run_until_complete(lifespan.__aenter__())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")

    def call(who: str, method: str, path: str, **kw):  # noqa: ANN202
        async def go():  # noqa: ANN202
            if who not in tokens:
                r = await client.post("/api/v1/auth/login", json={"identifier": people[who]["email"], "password": PASSWORD})
                assert r.status_code == 200, r.text
                tokens[who] = r.json()["access_token"]
            return await client.request(method, f"/api/v1{path}", headers={"Authorization": f"Bearer {tokens[who]}"}, **kw)
        return loop.run_until_complete(go())

    def pid(*keys: str) -> list[str]:
        return [people[k]["public_id"] for k in keys]

    def send(who: str, to=(), cc=(), bcc=(), subject="Hello", body="<p>Body</p>", **extra):  # noqa: ANN001, ANN202
        payload = {"to": pid(*to), "cc": pid(*cc), "bcc": pid(*bcc), "subject": subject, "body_html": body, **extra}
        return call(who, "POST", "/messages", json=payload)

    ns = type("W", (), dict(tag=tag, people=people, call=staticmethod(call), pid=staticmethod(pid), send=staticmethod(send)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                users = "SELECT id FROM users WHERE email LIKE :u"
                await s.execute(text(f"DELETE FROM mail_messages WHERE sender_id IN ({users})"), p)
                await s.execute(text(f"DELETE FROM mail_attachments WHERE uploader_id IN ({users})"), p)
                await s.execute(text(f"DELETE FROM tokens WHERE user_id IN ({users})"), p)
                # Sending now raises a `message_received` notification, which references the recipient.
                await s.execute(text(f"DELETE FROM notifications WHERE user_id IN ({users})"), p)
                await s.execute(text("DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
                await s.execute(text("DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
                await s.execute(text("DELETE FROM batches WHERE batch_code LIKE :c"), p)
                await s.execute(text("DELETE FROM courses WHERE title LIKE :t"), p)
                await s.execute(text(f"DELETE FROM user_roles WHERE user_id IN ({users})"), p)
                await s.execute(text("DELETE FROM users WHERE email LIKE :u"), p)
        loop.run_until_complete(client.aclose())
        loop.run_until_complete(lifespan.__aexit__(None, None, None))
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def names(response) -> list[str]:  # noqa: ANN001
    return sorted(p["name"] for p in response.json()["items"])


# --------------------------------------------------------------------------- who may write to whom


def test_the_address_book_is_limited_to_the_people_you_may_write_to(world) -> None:
    w = world
    n = lambda k: w.people[k]["name"]  # noqa: E731
    assert names(w.call("stua", "GET", "/messages/recipients", params={"query": w.tag})) == sorted([n("admin"), n("tutora")])          # own tutor + admin
    assert names(w.call("tutora", "GET", "/messages/recipients", params={"query": w.tag})) == sorted([n("admin"), n("stua"), n("stub")])  # own students + admin
    assert names(w.call("stuc", "GET", "/messages/recipients", params={"query": w.tag})) == sorted([n("admin"), n("tutorb")])
    everyone = names(w.call("admin", "GET", "/messages/recipients", params={"query": w.tag, "limit": 50}))
    assert everyone == sorted(n(k) for k in ("tutora", "tutorb", "stua", "stub", "stuc"))                                           # not themselves


def test_the_address_book_never_carries_an_email_address_or_login_name(world) -> None:
    for who in ("admin", "tutora", "stua"):
        body = world.call(who, "GET", "/messages/recipients", params={"query": world.tag, "limit": 50}).text
        assert "@" not in body and "t.test" not in body
    # ... and typing an address finds nobody: the directory searches names only.
    assert world.call("admin", "GET", "/messages/recipients", params={"query": world.people["stua"]["email"]}).json()["items"] == []


@pytest.mark.parametrize("sender, recipient, allowed", [
    ("tutora", "stua", True), ("tutora", "stub", True), ("tutora", "admin", True),
    ("tutora", "stuc", False),        # a student of another tutor
    ("tutora", "tutorb", False),      # tutors do not write to each other
    ("stua", "tutora", True), ("stua", "admin", True),
    ("stua", "tutorb", False),        # not their tutor
    ("stua", "stub", False),          # students do not write to students
    ("admin", "stuc", True), ("admin", "tutorb", True),
])
def test_the_audience_rules(world, sender: str, recipient: str, allowed: bool) -> None:
    r = world.send(sender, to=[recipient])
    assert (r.status_code == 201) is allowed, r.text
    if not allowed:
        assert r.status_code == 403


def test_a_missing_person_and_a_forbidden_one_are_refused_identically(world) -> None:
    forbidden = world.send("stua", to=["tutorb"])
    missing = world.call("stua", "POST", "/messages", json={"to": ["00000000-0000-0000-0000-000000000001"], "subject": "x", "body_html": "<p>x</p>"})
    assert forbidden.status_code == missing.status_code == 403 and forbidden.json()["message"] == missing.json()["message"]


def test_a_message_needs_a_recipient_and_something_to_say(world) -> None:
    assert world.send("tutora", to=[]).status_code == 422
    assert world.send("tutora", to=["stua"], subject="", body="").status_code == 422


# --------------------------------------------------------------------------- Cc / Bcc


def test_bcc_is_disclosed_to_the_sender_alone(world) -> None:
    w = world
    r = w.send("tutora", to=["stua"], cc=["stub"], bcc=["admin"], subject="Term dates")
    assert r.status_code == 201
    thread = r.json()["thread_id"]
    n = lambda k: w.people[k]["name"]  # noqa: E731

    mine = w.call("tutora", "GET", f"/messages/threads/{thread}").json()["messages"][0]
    assert [p["name"] for p in mine["bcc"]] == [n("admin")]                                   # the sender sees who was Bcc'd

    for reader in ("stua", "stub"):
        m = w.call(reader, "GET", f"/messages/threads/{thread}").json()["messages"][0]
        assert [p["name"] for p in m["to"]] == [n("stua")] and [p["name"] for p in m["cc"]] == [n("stub")]
        assert m["bcc"] == [] and not m["you_were_bcc"] and n("admin") not in str(m)

    bcc = w.call("admin", "GET", f"/messages/threads/{thread}").json()["messages"][0]
    assert bcc["you_were_bcc"] and bcc["bcc"] == []                                            # told only that *they* were Bcc'd


def test_somebody_named_twice_appears_once_in_the_most_visible_field(world) -> None:
    r = world.send("tutora", to=["stua"], cc=["stua"], bcc=["stua", "stub"]).json()
    assert [p["name"] for p in r["to"]] == [world.people["stua"]["name"]] and r["cc"] == [] and [p["name"] for p in r["bcc"]] == [world.people["stub"]["name"]]


def test_no_email_address_appears_in_any_mail_response(world) -> None:
    w = world
    thread = w.send("tutora", to=["stua"], cc=["stub"], bcc=["admin"]).json()["thread_id"]
    seen = w.call("tutora", "GET", f"/messages/threads/{thread}").text + w.call("stua", "GET", "/messages").text + w.call("tutora", "GET", "/messages", params={"folder": "sent"}).text
    assert all(p["email"] not in seen for p in w.people.values()) and "t.test" not in seen


# --------------------------------------------------------------------------- bodies


def test_a_hostile_body_is_sanitised_before_it_is_stored_or_shown(world) -> None:
    w = world
    r = w.send("tutora", to=["stua"], body='<p onclick="x()">Hi <b>you</b></p><script>steal()</script><img src=x onerror=steal()><a href="javascript:steal()">go</a>')
    assert r.status_code == 201
    shown = w.call("stua", "GET", f"/messages/threads/{r.json()['thread_id']}").json()["messages"][0]["body_html"]
    assert "script" not in shown and "onerror" not in shown and "onclick" not in shown and "javascript:" not in shown and "<img" not in shown and "<b>you</b>" in shown


# --------------------------------------------------------------------------- threads, read state, removal


def test_a_reply_joins_the_thread_and_opening_it_marks_it_read(world) -> None:
    w = world
    first = w.send("tutora", to=["stua"], subject="Homework").json()
    assert w.call("stua", "GET", "/messages/unread-count").json()["unread"] == 1
    inbox = w.call("stua", "GET", "/messages").json()["items"]
    assert len(inbox) == 1 and not inbox[0]["is_read"] and inbox[0]["thread_count"] == 1

    reply = w.send("stua", to=["tutora"], subject="Re: Homework", reply_to_id=first["public_id"])
    assert reply.status_code == 201 and reply.json()["thread_id"] == first["thread_id"]

    thread = w.call("stua", "GET", f"/messages/threads/{first['thread_id']}").json()
    assert [m["is_mine"] for m in thread["messages"]] == [False, True]
    assert w.call("stua", "GET", "/messages/unread-count").json()["unread"] == 0            # reading the thread read it

    inbox = w.call("tutora", "GET", "/messages").json()["items"]
    assert len(inbox) == 1 and inbox[0]["thread_count"] == 2 and not inbox[0]["is_read"]   # one row per conversation, and the reply is unread


def test_you_cannot_reply_to_a_message_you_were_not_part_of(world) -> None:
    first = world.send("tutora", to=["stua"]).json()
    r = world.send("admin", to=["tutora"], reply_to_id=first["public_id"])
    assert r.status_code == 404


def test_removing_a_message_hides_only_your_own_copy(world) -> None:
    w = world
    m = w.send("tutora", to=["stua"], cc=["stub"]).json()
    assert w.call("stua", "DELETE", f"/messages/{m['public_id']}").status_code == 204
    assert w.call("stua", "GET", "/messages").json()["items"] == []
    assert w.call("stua", "GET", f"/messages/{m['public_id']}").status_code == 404
    assert len(w.call("stub", "GET", "/messages").json()["items"]) == 1                     # the Cc'd student still has it
    assert len(w.call("tutora", "GET", "/messages", params={"folder": "sent"}).json()["items"]) == 1


def test_a_stranger_cannot_read_a_message_or_a_thread(world) -> None:
    m = world.send("tutora", to=["stua"]).json()
    assert world.call("stuc", "GET", f"/messages/{m['public_id']}").status_code == 404
    assert world.call("stuc", "GET", f"/messages/threads/{m['thread_id']}").status_code == 404
    assert world.call("stuc", "PATCH", f"/messages/{m['public_id']}/state", json={"starred": True}).status_code == 404


def test_starring_and_the_folders(world) -> None:
    w = world
    m = w.send("tutora", to=["stua"], subject="Star me").json()
    assert w.call("stua", "PATCH", f"/messages/{m['public_id']}/state", json={"starred": True}).status_code == 204
    assert [i["subject"] for i in w.call("stua", "GET", "/messages", params={"folder": "starred"}).json()["items"]] == ["Star me"]
    assert w.call("tutora", "GET", "/messages", params={"folder": "starred"}).json()["items"] == []       # starring is per person
    assert w.call("stua", "GET", "/messages", params={"q": "star"}).json()["total"] == 1 and w.call("stua", "GET", "/messages", params={"q": "nothing-here"}).json()["total"] == 0


def test_searching_matches_a_senders_name_but_never_their_email(world) -> None:
    w = world
    w.send("tutora", to=["stua"], subject="Hello")
    assert w.call("stua", "GET", "/messages", params={"q": "tutora"}).json()["total"] == 1             # their name is "Tutora <tag>"
    assert w.call("stua", "GET", "/messages", params={"q": w.people["tutora"]["email"]}).json()["total"] == 0


def test_reply_all_never_proposes_somebody_you_may_not_write_to(world) -> None:
    w = world
    n = lambda k: w.people[k]["name"]  # noqa: E731
    m = w.send("tutora", to=["stua"], cc=["stub", "admin"]).json()
    opts = w.call("stua", "GET", f"/messages/{m['public_id']}/reply-options").json()
    assert [p["name"] for p in opts["reply"]] == [n("tutora")]
    assert [p["name"] for p in opts["reply_all_to"]] == [n("tutora")]
    assert [p["name"] for p in opts["reply_all_cc"]] == [n("admin")]                       # not Stub: students cannot write to students

    own = w.call("tutora", "GET", f"/messages/{m['public_id']}/reply-options").json()      # following up on my own message
    assert [p["name"] for p in own["reply"]] == [n("stua")]
    assert w.call("tutorb", "GET", f"/messages/{m['public_id']}/reply-options").status_code == 404  # a stranger may not


def test_a_bcc_reader_may_reply_and_is_never_offered_as_a_reply_all_recipient(world) -> None:
    w = world
    n = lambda k: w.people[k]["name"]  # noqa: E731
    m = w.send("tutora", to=["stua"], bcc=["stub"]).json()
    assert [p["name"] for p in w.call("stub", "GET", f"/messages/{m['public_id']}/reply-options").json()["reply"]] == [n("tutora")]
    opts = w.call("stua", "GET", f"/messages/{m['public_id']}/reply-options").json()
    assert n("stub") not in str(opts)                                                     # only the sender knows who was Bcc'd


# --------------------------------------------------------------------------- drafts


def test_a_draft_is_private_until_it_is_sent(world) -> None:
    w = world
    d = w.call("tutora", "POST", "/messages/drafts", json={"to": w.pid("stua"), "subject": "Not yet", "body_html": "<p>wip</p>"}).json()
    assert d["is_draft"] and w.call("stua", "GET", "/messages").json()["items"] == []
    assert w.call("stua", "GET", f"/messages/{d['public_id']}").status_code == 404
    assert [i["subject"] for i in w.call("tutora", "GET", "/messages", params={"folder": "drafts"}).json()["items"]] == ["Not yet"]

    sent = w.call("tutora", "POST", "/messages", json={"draft_id": d["public_id"], "to": w.pid("stua"), "subject": "Now", "body_html": "<p>done</p>"})
    assert sent.status_code == 201 and sent.json()["public_id"] == d["public_id"] and not sent.json()["is_draft"]
    assert w.call("tutora", "GET", "/messages", params={"folder": "drafts"}).json()["items"] == []
    assert [i["subject"] for i in w.call("stua", "GET", "/messages").json()["items"]] == ["Now"]


def test_deleting_a_draft_removes_it(world) -> None:
    w = world
    d = w.call("tutora", "POST", "/messages/drafts", json={"subject": "Oops"}).json()
    assert w.call("tutora", "DELETE", f"/messages/{d['public_id']}").status_code == 204
    assert w.call("tutora", "GET", "/messages", params={"folder": "drafts"}).json()["items"] == []


# --------------------------------------------------------------------------- attachments


def _upload(w, who: str, name: str, data: bytes = b"hello"):  # noqa: ANN001, ANN202
    return w.call(who, "POST", "/messages/attachments", files={"file": (name, data, "application/octet-stream")})


def test_an_attachment_is_downloadable_only_by_the_people_it_was_sent_to(world) -> None:
    w = world
    up = _upload(w, "tutora", "notes.pdf", b"%PDF-1.4 hello")
    assert up.status_code == 201 and up.json()["filename"] == "notes.pdf"
    aid = up.json()["public_id"]
    assert w.call("stua", "GET", f"/messages/attachments/{aid}/download").status_code == 404        # not sent yet: only the uploader
    sent = w.send("tutora", to=["stua"], bcc=["admin"], attachment_ids=[aid]).json()
    assert sent["attachments"][0]["filename"] == "notes.pdf"
    for reader in ("tutora", "stua", "admin"):
        r = w.call(reader, "GET", f"/messages/attachments/{aid}/download")
        assert r.status_code == 200 and r.content == b"%PDF-1.4 hello" and "attachment" in r.headers["content-disposition"] and r.headers["x-content-type-options"] == "nosniff"
    assert w.call("stub", "GET", f"/messages/attachments/{aid}/download").status_code == 404
    assert w.call("stuc", "GET", f"/messages/attachments/{aid}/download").status_code == 404


def test_programs_and_oversized_or_empty_files_are_refused(world) -> None:
    w = world
    assert _upload(w, "tutora", "setup.exe").status_code == 422
    assert _upload(w, "tutora", "run.SH").status_code == 422
    assert _upload(w, "tutora", "empty.txt", b"").status_code == 422
    assert _upload(w, "tutora", "huge.zip", b"x" * (10 * 1024 * 1024 + 1)).status_code == 422


def test_somebody_elses_attachment_cannot_be_attached(world) -> None:
    aid = _upload(world, "tutora", "mine.txt").json()["public_id"]
    r = world.send("admin", to=["stua"], attachment_ids=[aid])
    assert r.status_code == 404


def test_an_attachment_name_is_made_safe(world) -> None:
    up = _upload(world, "tutora", "../../evil‮gnp.txt")
    assert up.status_code == 201 and "/" not in up.json()["filename"] and "‮" not in up.json()["filename"]


def test_a_sent_attachment_cannot_be_removed(world) -> None:
    w = world
    aid = _upload(w, "tutora", "keep.txt").json()["public_id"]
    w.send("tutora", to=["stua"], attachment_ids=[aid])
    assert w.call("tutora", "DELETE", f"/messages/attachments/{aid}").status_code == 409


# --------------------------------------------------------------------------- permissions


def test_only_people_with_the_message_permissions_can_use_it(world) -> None:
    async def anonymous() -> int:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
            return (await c.get("/api/v1/messages")).status_code

    assert asyncio.run(anonymous(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())) == 401

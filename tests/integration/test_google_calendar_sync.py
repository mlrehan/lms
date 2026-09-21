"""The Google Calendar sync against real Postgres and a stateful fake of Google's API.

The fake sits behind the real `GoogleCalendarClient` (as an httpx transport), so retries, paging
and error handling are exercised too. Nothing here talks to Google or touches the real
`google_connections` row: the service is given a token override.
"""

from __future__ import annotations

import asyncio
import random
import selectors
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select, text

from backend.core.config import get_settings
from backend.core.errors import ServiceUnavailableError
from backend.db.manager import DatabaseManager
from backend.integrations import google_calendar as gc
from backend.integrations import google_events as ge
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.guardian import StudentGuardian
from backend.models.attendance import Attendance
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.organization import Organization, OrganizationManager
from backend.models.user_sync import UserSyncRun
from backend.services.google_calendar_service import GoogleCalendarSyncService
from backend.utils.enums import CourseStatus, EnrollmentStatus, Platforms, UserStatus


class FakeGoogle:
    """Just enough of the Calendar API to be wrong in the same ways the real one is."""

    def __init__(self) -> None:
        self.calendars: dict[str, dict[str, Any]] = {}
        self.acl: list[tuple[str, str, str]] = []
        self.log: list[tuple[str, str]] = []
        self.fail_events_for: set[str] = set()  # calendar ids whose event writes return 500
        self.revoked = False
        self._n = 0

    def _id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def writes(self) -> int:
        return sum(1 for m, _ in self.log if m != "GET")

    def events(self, cal: str) -> dict[str, dict[str, Any]]:
        return {k: v for k, v in self.calendars[cal]["events"].items() if v.get("status") != "cancelled"}

    def only_calendar(self) -> str:
        assert len(self.calendars) == 1, list(self.calendars)
        return next(iter(self.calendars))

    # ---- what an administrator can do in Google's own interface
    def admin_move(self, cal: str, event_id: str, start: datetime, end: datetime) -> None:
        e = self.calendars[cal]["events"][event_id]
        e["start"] = {"dateTime": ge.iso_utc(start), "timeZone": "UTC"}
        e["end"] = {"dateTime": ge.iso_utc(end), "timeZone": "UTC"}
        e["updated"] = self.now()

    def admin_delete(self, cal: str, event_id: str) -> None:
        e = self.calendars[cal]["events"][event_id]
        e["status"], e["updated"] = "cancelled", self.now()

    def admin_create(self, cal: str, summary: str, start: datetime, end: datetime, *, location: str | None = None, attendees: list[str] | None = None) -> str:
        eid = self._id("ev")
        self.calendars[cal]["events"][eid] = {
            "id": eid, "status": "confirmed", "updated": self.now(), "summary": summary,
            "start": {"dateTime": ge.iso_utc(start), "timeZone": "UTC"}, "end": {"dateTime": ge.iso_utc(end), "timeZone": "UTC"},
            **({"location": location} if location else {}), **({"attendees": [{"email": a} for a in attendees]} if attendees else {}),
        }
        return eid

    def admin_edit(self, cal: str, event_id: str, **fields: Any) -> None:
        e = self.calendars[cal]["events"][event_id]
        e.update(fields)
        e["updated"] = self.now()

    def admin_add_guest(self, cal: str, event_id: str, email: str) -> None:
        e = self.calendars[cal]["events"][event_id]
        e["attendees"] = [*e.get("attendees", []), {"email": email}]
        e["updated"] = self.now()

    # ---- the HTTP surface
    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            if self.revoked:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "AT", "expires_in": 3600})
        path = request.url.path.removeprefix("/calendar/v3")
        method = request.method
        self.log.append((method, path))
        body = request.content and httpx.Response(200, content=request.content).json() or {}
        parts = [p for p in path.split("/") if p]

        if parts == ["calendars"] and method == "POST":
            cid = self._id("cal") + "-" + uuid.uuid4().hex[:10] + "@group.calendar.google.com"
            self.calendars[cid] = {"body": body, "events": {}}
            return httpx.Response(200, json={"id": cid, **body})
        cid = httpx.URL(f"http://x{path}").path.split("/")[2] if len(parts) >= 2 else None
        from urllib.parse import unquote

        cid = unquote(parts[1]) if len(parts) >= 2 else None
        if cid not in self.calendars:
            return httpx.Response(404, json={"error": {"errors": [{"reason": "notFound"}]}})
        cal = self.calendars[cid]

        if len(parts) == 2:
            if method == "PATCH":
                cal["body"] = {**cal["body"], **body}
                return httpx.Response(200, json={"id": cid, **cal["body"]})
            if method == "DELETE":
                del self.calendars[cid]
                return httpx.Response(204)
            return httpx.Response(200, json={"id": cid, **cal["body"]})
        if parts[2] == "acl":
            self.acl.append((cid, body["scope"]["value"], body["role"]))
            return httpx.Response(200, json={})
        if parts[2] != "events":
            return httpx.Response(404, json={})

        if cid in self.fail_events_for and method != "GET":
            return httpx.Response(500, json={"error": {"errors": [{"reason": "backendError"}]}})

        if len(parts) == 3:
            if method == "POST":
                eid = self._id("ev")
                cal["events"][eid] = {"id": eid, "status": "confirmed", "updated": self.now(), **body}
                return httpx.Response(200, json=cal["events"][eid])
            params = request.url.params
            items = list(cal["events"].values())
            if params.get("showDeleted") != "true":
                items = [e for e in items if e.get("status") != "cancelled"]
            if params.get("updatedMin"):
                items = [e for e in items if e["updated"] >= params["updatedMin"].replace("Z", ".000000Z") or e["updated"] >= params["updatedMin"]]
            return httpx.Response(200, json={"items": items})

        eid = unquote(parts[3])
        event = cal["events"].get(eid)
        if event is None or (event.get("status") == "cancelled" and method != "DELETE"):
            return httpx.Response(410 if event else 404, json={"error": {"errors": [{"reason": "deleted" if event else "notFound"}]}})
        if method == "PATCH":
            event.update(body)
            event["updated"] = self.now()
            return httpx.Response(200, json=event)
        if method == "DELETE":
            event["status"], event["updated"] = "cancelled", self.now()
            return httpx.Response(204)
        return httpx.Response(200, json=event)


@pytest.fixture()
def env():
    n = random.randint(100000, 900000)
    tag = f"gc{n}"
    fake = FakeGoogle()
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    base = get_settings()
    db = DatabaseManager(base.database, application_name="google-tests")
    run_ids: list[int] = []

    def service(**overrides: Any) -> GoogleCalendarSyncService:
        google = base.google.model_copy(update={
            "client_id": "123456789012-abcdefghijklmnopqrstuvwxyz012345.apps.googleusercontent.com", "client_secret": SecretStr("secret"), "email": "org@lait.test", "share_with_admins": True, **overrides})
        settings = base.model_copy(update={"google": google})
        return GoogleCalendarSyncService(
            db.session_factory, settings, token_override="REFRESH",
            client_factory=lambda token: gc.GoogleCalendarClient(google, token, transport=httpx.MockTransport(fake.handle), pace_seconds=0),
        )

    def sync(*, dry_run: bool = False, batches: list[int] | None = None, **overrides: Any) -> UserSyncRun:
        async def go() -> UserSyncRun:
            svc = service(**overrides)
            run = await svc.run(trigger_type="MANUAL", triggered_by_user_id=None, dry_run=dry_run, batch_ids=batches if batches is not None else world["batches"])
            run_ids.append(run.id)
            return run
        return loop.run_until_complete(go())

    def q(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    world: dict[str, Any] = {}

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars().all()}

        def user(name: str, email: str | None, role: str | None = None) -> User:
            u = User(username=f"{tag}.{name}", slug=f"{tag}-{name}", email=email, first_name=name.title(), last_name="Test", hashed_password="x", status=UserStatus.ACTIVE,
                     roles=[roles[role]] if role else [])
            s.add(u)
            return u

        tutor, s1, s2, s3, noemail, gdn, mgr, tutor2 = (
            user("tutor", f"{tag}.tutor@t.test", "TUTOR"), user("s1", f"{tag}.s1@t.test", "STUDENT"), user("s2", f"{tag}.s2@t.test", "STUDENT"),
            user("s3", f"{tag}.s3@t.test", "STUDENT"), user("noemail", None, "STUDENT"), user("guardian", f"{tag}.guardian@t.test"), user("manager", f"{tag}.manager@t.test"),
            user("tutor2", f"{tag}.tutor2@t.test", "TUTOR"))
        user("boss", f"{tag}.boss@t.test", "SUPER_ADMIN")
        user("admin", f"{tag}.admin@t.test", "ADMIN")
        await s.flush()
        course = Course(title=f"{tag} Course", code=f"{tag}", status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        org = Organization(name=f"{tag} Corp", is_active=True, created_at=datetime.now(timezone.utc))
        org.managers, org.memberships = [], []
        s.add_all([course, org])
        await s.flush()
        s.add_all([StudentGuardian(guardian_id=gdn.id, student_id=s1.id, created_at=datetime.now(timezone.utc)),
                   OrganizationManager(organization_id=org.id, user_id=mgr.id, is_active=True, invited_at=datetime.now(timezone.utc))])

        def batch(code: str) -> Batch:
            b = Batch(batch_code=f"{tag}-{code}", course_id=course.id, start_date=date.today(), end_date=date.today() + timedelta(days=7), is_active=True, capacity=25)
            b.sessions, b.enrollments, b.student_reviews = [], [], []
            s.add(b)
            return b

        b1, b2 = batch("A"), batch("B")
        await s.flush()
        t0 = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(days=2)
        for b in (b1, b2):
            for i in range(2):
                sess = BatchSession(batch_id=b.id, tutor_id=tutor.id, session_start_time=t0 + timedelta(days=i), session_end_time=t0 + timedelta(days=i, hours=2),
                                    duration_minutes=120, platform=Platforms.Zoom, meeting_link="https://zoom.test/j/1")
                sess.attendances = []
                s.add(sess)
        for stu, org_id in ((s1, None), (s2, org.id), (noemail, None)):
            s.add(Enrollments(batch_id=b1.id, student_id=stu.id, enrollment_date=datetime.now(timezone.utc), status=EnrollmentStatus.CONFIRMED, organization_id=org_id))
        s.add(Enrollments(batch_id=b1.id, student_id=s3.id, enrollment_date=datetime.now(timezone.utc), status=EnrollmentStatus.DROPPED))
        await s.flush()
        world.update(batches=[b1.id], batch_b=b2.id, s3=s3.id, s1=s1.id, tag=tag, t0=t0, tutor=tutor.id, tutor2=tutor2.id)

    loop.run_until_complete(_run(db, build))

    ns = type("Env", (), dict(tag=tag, fake=fake, sync=staticmethod(sync), q=staticmethod(q), world=world, db=db, loop=loop, service=staticmethod(service)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                ids = "(SELECT id FROM batches WHERE batch_code LIKE :c)"
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                await s.execute(text(f"DELETE FROM google_change_requests WHERE batch_id IN {ids}"), p)
                await s.execute(text(f"DELETE FROM attendances WHERE session_id IN (SELECT id FROM batch_sessions WHERE batch_id IN {ids})"), p)
                await s.execute(text(f"DELETE FROM enrollments WHERE batch_id IN {ids}"), p)
                await s.execute(text(f"DELETE FROM batch_sessions WHERE batch_id IN {ids}"), p)
                await s.execute(text("DELETE FROM batches WHERE batch_code LIKE :c"), p)
                await s.execute(text("DELETE FROM student_guardians WHERE guardian_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM organization_managers WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM organizations WHERE name LIKE :t"), p)
                await s.execute(text("DELETE FROM courses WHERE title LIKE :t"), p)
                await s.execute(text("DELETE FROM google_change_requests WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c) OR email LIKE :e"), {**p, "e": f"{tag}.%"})
                await s.execute(text("DELETE FROM attendances WHERE student_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM notifications WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM users WHERE username LIKE :u"), p)
                if run_ids:
                    await s.execute(delete(UserSyncRun).where(UserSyncRun.id.in_(run_ids)))
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


async def _run(db, fn):  # noqa: ANN001, ANN202
    async with db.session_factory.begin() as s:
        return await fn(s)


# ------------------------------------------------------------------ helpers


def _emails(event: dict[str, Any]) -> set[str]:
    return {a["email"] for a in event.get("attendees", [])}


def _sessions(e):  # noqa: ANN001, ANN202
    async def f(s):  # noqa: ANN001, ANN202
        return (await s.execute(select(BatchSession).where(BatchSession.batch_id == e.world["batches"][0]).order_by(BatchSession.session_start_time))).scalars().all()
    return e.q(f)


def _expected(e) -> set[str]:  # noqa: ANN001
    t = e.tag
    return {f"{t}.tutor@t.test", f"{t}.s1@t.test", f"{t}.s2@t.test", f"{t}.guardian@t.test", f"{t}.manager@t.test"}


# --------------------------------------------------------------- the push


def test_a_first_sync_builds_one_calendar_with_one_event_per_session(env) -> None:
    e = env
    run = e.sync()
    assert run.status == "SUCCEEDED", run.errors
    cal = e.fake.only_calendar()
    assert e.fake.calendars[cal]["body"]["summary"] == f"{e.tag} Course ({e.tag}-A)"
    assert e.fake.calendars[cal]["body"]["timeZone"] == "Europe/London"
    assert len(e.fake.events(cal)) == 2 and run.stats["events"]["created"] == 2 and run.stats["calendars"]["created"] == 1


def test_guests_are_the_tutor_the_enrolled_their_guardians_and_their_employers_managers(env) -> None:
    e = env
    e.sync()
    for event in e.fake.events(e.fake.only_calendar()).values():
        assert _emails(event) == _expected(e)  # not the dropped student, not the one with no email


def test_every_event_is_private_utc_and_traceable(env) -> None:
    e = env
    e.sync()
    sessions = _sessions(e)
    events = sorted(e.fake.events(e.fake.only_calendar()).values(), key=lambda v: v["start"]["dateTime"])
    for event, s in zip(events, sessions, strict=True):
        assert event["start"] == {"dateTime": ge.iso_utc(s.session_start_time), "timeZone": "UTC"}
        assert event["guestsCanSeeOtherGuests"] is False and event["guestsCanModify"] is False and event["guestsCanInviteOthers"] is False
        assert event["extendedProperties"]["private"][ge.SESSION_KEY] == str(s.public_id)
        assert {r["method"] for r in event["reminders"]["overrides"]} == {"popup"}


def test_super_admins_may_edit_the_calendar_and_administrators_may_only_view_it(env) -> None:
    e = env
    e.sync()
    granted = {email: role for _cal, email, role in e.fake.acl}
    # Google cannot say who made an edit, so write access to the calendar IS the authorisation.
    assert granted[f"{e.tag}.boss@t.test"] == "writer"
    assert granted[f"{e.tag}.admin@t.test"] == "reader"
    assert "org@lait.test" not in granted  # the owner is not "shared" with itself
    assert set(granted.values()) <= {"writer", "reader"}  # nobody is ever made an owner


def test_administrators_can_be_allowed_to_edit(env) -> None:
    e = env
    e.sync(admins_can_edit=True)
    granted = {email: role for _c, email, role in e.fake.acl}
    assert granted[f"{e.tag}.admin@t.test"] == "writer" and granted[f"{e.tag}.boss@t.test"] == "writer"


def test_the_mapping_is_stored_so_the_next_run_can_find_everything(env) -> None:
    e = env
    e.sync()
    assert all(s.google_event_id and s.google_synced_hash for s in _sessions(e))

    async def cal(s):  # noqa: ANN001, ANN202
        return (await s.execute(select(Batch.google_calendar_id).where(Batch.id == e.world["batches"][0]))).scalar_one()

    assert e.q(cal) == e.fake.only_calendar()


# ---------------------------------------------------------- idempotence, dry run


def test_a_second_run_with_nothing_changed_makes_no_google_writes(env) -> None:
    e = env
    e.sync()
    before = e.fake.writes()
    run = e.sync()
    assert e.fake.writes() == before, e.fake.log[before:]
    assert run.stats["events"] == {"created": 0, "updated": 0, "unchanged": 2, "deleted": 0, "recreated": 0}
    assert run.stats["calendars"]["unchanged"] == 1


def test_a_dry_run_reports_and_changes_nothing(env) -> None:
    e = env
    run = e.sync(dry_run=True)
    assert e.fake.writes() == 0 and not e.fake.calendars
    assert run.stats["events"]["created"] == 2 and run.stats["calendars"]["created"] == 1
    assert all(s.google_event_id is None for s in _sessions(e))


def test_a_dry_run_after_a_sync_reports_the_pending_change_without_making_it(env) -> None:
    e = env
    e.sync()

    async def move(s):  # noqa: ANN001, ANN202
        await s.execute(text("UPDATE batch_sessions SET meeting_link = 'https://zoom.test/NEW' WHERE batch_id = :b"), {"b": e.world["batches"][0]})

    e.q(move)
    before = e.fake.writes()
    run = e.sync(dry_run=True)
    assert e.fake.writes() == before and run.stats["events"]["updated"] == 2


# --------------------------------------------------------- LMS changes flow out


def test_an_enrolment_added_in_the_lms_adds_the_guest_to_every_event(env) -> None:
    e = env
    e.sync()

    async def enrol(s):  # noqa: ANN001, ANN202
        await s.execute(text("UPDATE enrollments SET status = 'CONFIRMED' WHERE student_id = :s"), {"s": e.world["s3"]})

    e.q(enrol)
    run = e.sync()
    assert run.stats["events"]["updated"] == 2
    assert all(f"{e.tag}.s3@t.test" in _emails(v) for v in e.fake.events(e.fake.only_calendar()).values())


def test_a_dropped_enrolment_removes_the_guest(env) -> None:
    e = env
    e.sync()

    async def drop(s):  # noqa: ANN001, ANN202
        await s.execute(text("UPDATE enrollments SET status = 'DROPPED' WHERE student_id = (SELECT id FROM users WHERE username = :u)"), {"u": f"{e.tag}.s1"})

    e.q(drop)
    e.sync()
    for event in e.fake.events(e.fake.only_calendar()).values():
        assert f"{e.tag}.s1@t.test" not in _emails(event)


def test_a_rescheduled_session_updates_its_event(env) -> None:
    e = env
    e.sync()
    new_start = e.world["t0"] + timedelta(hours=5)

    async def move(s):  # noqa: ANN001, ANN202
        first = (await s.execute(select(BatchSession).where(BatchSession.batch_id == e.world["batches"][0]).order_by(BatchSession.session_start_time))).scalars().first()
        first.session_start_time, first.session_end_time = new_start, new_start + timedelta(hours=2)

    e.q(move)
    run = e.sync()
    assert run.stats["events"]["updated"] == 1 and run.stats["events"]["unchanged"] == 1
    starts = sorted(v["start"]["dateTime"] for v in e.fake.events(e.fake.only_calendar()).values())
    assert ge.iso_utc(new_start) in starts


def test_a_deleted_session_deletes_its_event(env) -> None:
    e = env
    e.sync()

    async def rm(s):  # noqa: ANN001, ANN202
        last = (await s.execute(select(BatchSession).where(BatchSession.batch_id == e.world["batches"][0]).order_by(BatchSession.session_start_time.desc()))).scalars().first()
        await s.delete(last)

    e.q(rm)
    run = e.sync()
    assert run.stats["events"]["deleted"] == 1 and len(e.fake.events(e.fake.only_calendar())) == 1


def test_the_description_renumbers_after_a_session_is_removed(env) -> None:
    e = env
    e.sync()

    async def rm(s):  # noqa: ANN001, ANN202
        first = (await s.execute(select(BatchSession).where(BatchSession.batch_id == e.world["batches"][0]).order_by(BatchSession.session_start_time))).scalars().first()
        await s.delete(first)

    e.q(rm)
    e.sync()
    (event,) = e.fake.events(e.fake.only_calendar()).values()
    assert event["description"].splitlines()[0] == "Session 1 of 1" and event["summary"] == f"{e.tag} Course ({e.tag}-A)"


# ------------------------------------------------------- Google changes flow in


def test_a_time_change_made_in_google_is_applied_to_the_lms(env) -> None:
    e = env
    e.sync()
    cal = e.fake.only_calendar()
    sessions = _sessions(e)
    new_start = e.world["t0"] + timedelta(hours=3)
    e.fake.admin_move(cal, sessions[0].google_event_id, new_start, new_start + timedelta(hours=2))
    run = e.sync()
    assert run.stats["pulled"]["time_changes"] == 1
    moved = _sessions(e)[0] if _sessions(e)[0].session_start_time.replace(tzinfo=timezone.utc) == new_start else _sessions(e)[-1]
    assert moved.session_start_time.astimezone(timezone.utc) == new_start and moved.duration_minutes == 120


def test_a_pulled_change_is_not_bounced_back_and_then_settles(env) -> None:
    e = env
    e.sync()
    cal = e.fake.only_calendar()
    s0 = _sessions(e)[0]
    new_start = e.world["t0"] + timedelta(hours=3)
    e.fake.admin_move(cal, s0.google_event_id, new_start, new_start + timedelta(hours=2))
    e.sync()
    assert e.fake.calendars[cal]["events"][s0.google_event_id]["start"]["dateTime"] == ge.iso_utc(new_start)  # Google's value stands
    before = e.fake.writes()
    e.sync()
    assert e.fake.writes() == before  # and the next run is quiet


def test_pulling_can_be_switched_off(env) -> None:
    e = env
    e.sync()
    cal = e.fake.only_calendar()
    s0 = _sessions(e)[0]
    e.fake.admin_move(cal, s0.google_event_id, e.world["t0"] + timedelta(hours=3), e.world["t0"] + timedelta(hours=5))
    run = e.sync(pull_session_times=False)
    assert run.stats["pulled"]["time_changes"] == 0
    assert _sessions(e)[0].session_start_time.astimezone(timezone.utc) == e.world["t0"]


@pytest.mark.parametrize("shift,length", [(timedelta(days=800), timedelta(hours=2)), (timedelta(hours=1), timedelta(hours=-1)), (timedelta(hours=1), timedelta(hours=30))])
def test_an_implausible_time_from_google_is_refused_and_put_back(env, shift, length) -> None:
    e = env
    e.sync()
    cal = e.fake.only_calendar()
    s0 = _sessions(e)[0]
    start = e.world["t0"] + shift
    e.fake.admin_move(cal, s0.google_event_id, start, start + length)
    run = e.sync()
    assert run.stats["pulled"]["rejected"] == 1 and run.stats["pulled"]["time_changes"] == 0
    assert _sessions(e)[0].session_start_time.astimezone(timezone.utc) == e.world["t0"]
    assert e.fake.calendars[cal]["events"][s0.google_event_id]["start"]["dateTime"] == ge.iso_utc(e.world["t0"])  # the LMS value was restored


def test_a_guest_added_in_google_is_removed_and_no_enrolment_is_created(env) -> None:
    e = env
    e.sync()
    cal = e.fake.only_calendar()
    s0 = _sessions(e)[0]
    e.fake.admin_add_guest(cal, s0.google_event_id, "stranger@evil.test")

    async def count(s):  # noqa: ANN001, ANN202
        return (await s.execute(select(text("count(*)")).select_from(Enrollments).where(Enrollments.batch_id == e.world["batches"][0]))).scalar_one()

    before = e.q(count)
    run = e.sync()
    assert run.stats["pulled"]["guest_drift"] == 1
    assert "stranger@evil.test" not in _emails(e.fake.calendars[cal]["events"][s0.google_event_id])
    assert e.q(count) == before  # enrolments are managed in the LMS, never by a guest list


def test_a_calendar_deleted_in_google_is_recreated_with_all_its_events(env) -> None:
    e = env
    e.sync()
    old = e.fake.only_calendar()
    del e.fake.calendars[old]
    # A pending change forces the calendar to be looked at again.
    async def rename(s):  # noqa: ANN001, ANN202
        await s.execute(text("UPDATE batches SET is_active = false WHERE id = :b"), {"b": e.world["batches"][0]})

    e.q(rename)
    run = e.sync()
    assert run.stats["calendars"]["recreated"] == 1
    new = e.fake.only_calendar()
    assert new != old and len(e.fake.events(new)) == 2


# ---------------------------------------------------------------- settings


def test_inviting_can_be_switched_off_so_events_carry_no_guests(env) -> None:
    e = env
    e.sync(invite_attendees=False)
    assert all("attendees" not in v for v in e.fake.events(e.fake.only_calendar()).values())


def test_the_guest_cap_is_applied_reported_and_never_drops_the_tutor(env) -> None:
    e = env
    run = e.sync(max_attendees_per_event=2)
    assert run.stats["guests_dropped"] > 0 and any("left off" in x["reason"] for x in run.errors)
    for event in e.fake.events(e.fake.only_calendar()).values():
        assert len(_emails(event)) == 2 and f"{e.tag}.tutor@t.test" in _emails(event)


def test_sharing_with_administrators_can_be_switched_off(env) -> None:
    e = env
    e.sync(share_with_admins=False)
    assert e.fake.acl == []


def test_a_batch_with_no_sessions_is_skipped_without_creating_a_calendar(env) -> None:
    e = env
    run = e.sync(batches=[e.world["batch_b"]])  # batch B has sessions; empty it first
    e.fake.calendars.clear()

    async def empty(s):  # noqa: ANN001, ANN202
        await s.execute(text("DELETE FROM batch_sessions WHERE batch_id = :b"), {"b": e.world["batch_b"]})
        await s.execute(text("UPDATE batches SET google_calendar_id = NULL WHERE id = :b"), {"b": e.world["batch_b"]})

    e.q(empty)
    before = len(e.fake.calendars)
    run = e.sync(batches=[e.world["batch_b"]])
    assert len(e.fake.calendars) == before and run.stats["batches"]["skipped"] == 1


# ------------------------------------------------------ failure and connection


def test_one_failing_batch_does_not_stop_the_others(env) -> None:
    e = env
    e.sync(batches=[e.world["batches"][0]])
    cal_a = e.fake.only_calendar()
    e.fake.fail_events_for.add(cal_a)

    async def touch(s):  # noqa: ANN001, ANN202
        await s.execute(text("UPDATE batch_sessions SET meeting_link = 'https://zoom.test/2' WHERE batch_id = :b"), {"b": e.world["batches"][0]})

    e.q(touch)
    run = e.sync(batches=[e.world["batches"][0], e.world["batch_b"]])
    assert run.status == "PARTIAL"
    assert any(x["source"] == "batch" for x in run.errors)
    assert len(e.fake.calendars) == 2  # batch B still got its calendar


def test_a_revoked_connection_fails_the_run_with_a_clear_message_and_leaks_nothing(env) -> None:
    e = env

    async def snapshot(s):  # noqa: ANN001, ANN202
        return (await s.execute(text("select id, status, disconnected_at, last_error from google_connections order by id"))).all()

    before = e.q(snapshot)
    e.fake.revoked = True
    run = e.sync()
    assert run.status == "FAILED" and "connect it again" in run.failure_reason
    assert "REFRESH" not in (run.failure_reason or "")
    # A run using an injected token says nothing about the stored connection. This test once marked
    # the developer's REAL connection as ERROR, silently disconnecting the console.
    assert e.q(snapshot) == before


def test_syncing_without_a_connection_is_refused_up_front(env) -> None:
    e = env

    async def go() -> None:
        settings = get_settings()
        google = settings.google.model_copy(update={"client_id": "123456789012-abcdefghijklmnopqrstuvwxyz012345.apps.googleusercontent.com", "client_secret": SecretStr("s")})
        svc = GoogleCalendarSyncService(e.db.session_factory, settings.model_copy(update={"google": google}))

        # Make sure the lookup sees no active connection regardless of the developer's real one.
        class _NoConnection:
            async def active(self):  # noqa: ANN202
                return None

        import backend.services.google_calendar_service as mod
        original = mod.GoogleConnectionService
        mod.GoogleConnectionService = lambda session, settings: _NoConnection()  # type: ignore[assignment,misc]
        try:
            await svc.start(trigger_type="MANUAL", triggered_by_user_id=None, dry_run=False)
        finally:
            mod.GoogleConnectionService = original

    with pytest.raises(ServiceUnavailableError, match="not connected"):
        e.loop.run_until_complete(go())



# ============================================================================================
# Managing sessions from Google: create, move, delete, cancel -- written to OUR database
# ============================================================================================


def _rows(e, *, cancelled: bool = False) -> list[BatchSession]:  # noqa: ANN001
    """The batch's sessions as the schedule lists them: cancelled ones are excluded unless asked for."""
    async def f(s):  # noqa: ANN001, ANN202
        q = select(BatchSession).where(BatchSession.batch_id == e.world["batches"][0]).order_by(BatchSession.session_start_time)
        if not cancelled:
            q = q.where(BatchSession.cancelled_at.is_(None))
        return (await s.execute(q)).scalars().all()
    return e.q(f)


def _start_valid_extra(e) -> tuple[datetime, datetime]:  # noqa: ANN001
    s = e.world["t0"] + timedelta(days=3, hours=1)
    return s, s + timedelta(hours=2)


def test_an_event_added_in_google_becomes_a_session_in_the_database(env) -> None:
    e = env
    e.sync()
    cal = e.fake.only_calendar()
    start, end = _start_valid_extra(e)
    eid = e.fake.admin_create(cal, "anything the admin typed", start, end, location="Zoom Video Conferencing")
    run = e.sync()
    rows = _rows(e)
    assert run.stats["pulled"]["adopted"] == 1 and len(rows) == 3
    new = [r for r in rows if r.google_event_id == eid][0]
    assert new.session_start_time.astimezone(timezone.utc) == start and new.duration_minutes == 120
    assert new.origin == "GOOGLE" and new.platform.name == "Zoom" and new.classroom is None
    assert new.tutor_id == e.world["tutor"]  # nothing named a tutor: the batch's own tutor is the default


def test_the_adopted_event_is_rewritten_in_the_institutions_format(env) -> None:
    e = env
    e.sync()
    cal = e.fake.only_calendar()
    start, end = _start_valid_extra(e)
    eid = e.fake.admin_create(cal, "typed by hand", start, end, location="Zoom Video Conferencing")
    e.sync()
    e.sync()  # the second run is the one that settles the format
    event = e.fake.calendars[cal]["events"][eid]
    assert event["summary"] == f"{e.tag} Course ({e.tag}-A)" and event["description"].splitlines()[0] == "Session 3 of 3"
    assert event["extendedProperties"]["private"][ge.MANAGED_KEY] == "1"
    assert event["guestsCanSeeOtherGuests"] is False


def test_a_physical_location_becomes_the_classroom(env) -> None:
    e = env
    e.sync()
    start, end = _start_valid_extra(e)
    e.fake.admin_create(e.fake.only_calendar(), "x", start, end, location="Office 4 (4th Floor), Boardman House, 64 Broadway, London E15 1NT")
    e.sync()
    new = _rows(e)[-1]
    assert new.platform.name == "Classroom" and new.classroom == "Office 4 (4th Floor), Boardman House, 64 Broadway, London E15 1NT"


def test_a_guest_who_is_a_tutor_becomes_the_sessions_tutor(env) -> None:
    e = env
    e.sync()
    start, end = _start_valid_extra(e)
    e.fake.admin_create(e.fake.only_calendar(), "x", start, end, location="Zoom", attendees=[f"{e.tag}.tutor2@t.test"])
    e.sync()
    assert _rows(e)[-1].tutor_id == e.world["tutor2"]


def test_the_number_of_planned_sessions_follows_the_change(env) -> None:
    e = env
    e.sync()
    start, end = _start_valid_extra(e)
    e.fake.admin_create(e.fake.only_calendar(), "x", start, end, location="Zoom")
    e.sync()

    async def planned(s):  # noqa: ANN001, ANN202
        return (await s.execute(select(Batch.number_of_sessions).where(Batch.id == e.world["batches"][0]))).scalar_one()

    assert e.q(planned) == 3


@pytest.mark.parametrize("make,reason", [
    (lambda e, s: (s + timedelta(hours=2), s), "not after the start"),
    (lambda e, s: (s, s + timedelta(hours=30)), "longer than 24 hours"),
    (lambda e, s: (s + timedelta(days=400), s + timedelta(days=400, hours=2)), "days after the batch ends"),
    (lambda e, s: (e.world["t0"], e.world["t0"] + timedelta(hours=1)), "already teaching"),  # the tutor's first session is then
])
def test_an_event_that_cannot_be_a_session_is_refused_with_the_reason_written_on_it(env, make, reason) -> None:
    e = env
    e.sync()
    cal = e.fake.only_calendar()
    base = e.world["t0"] + timedelta(days=3)
    start, end = make(e, base)
    if start > end:  # the "end before start" case
        start, end = end, start
        eid = e.fake.admin_create(cal, "bad", end, start)
    else:
        eid = e.fake.admin_create(cal, "bad", start, end, location="Zoom")
    run = e.sync()
    assert run.stats["pulled"]["adopted"] == 0 and run.stats["pulled"]["rejected_events"] == 1 and len(_rows(e)) == 2
    event = e.fake.calendars[cal]["events"][eid]
    assert event["description"].startswith("NOT ADDED TO THE LMS") and event["colorId"] == "11"
    assert any("not added as a session" in x["reason"] for x in run.errors)


def test_a_refused_event_is_not_reported_again_until_it_is_fixed_and_then_it_is_added(env) -> None:
    e = env
    e.sync()
    cal = e.fake.only_calendar()
    bad_start = e.world["t0"] + timedelta(days=400)
    eid = e.fake.admin_create(cal, "later", bad_start, bad_start + timedelta(hours=2), location="Zoom")
    assert e.sync().stats["pulled"]["rejected_events"] == 1
    assert e.sync().stats["pulled"]["rejected_events"] == 0  # unchanged: left alone, not re-reported
    start, end = _start_valid_extra(e)
    e.fake.admin_edit(cal, eid, start={"dateTime": ge.iso_utc(start), "timeZone": "UTC"}, end={"dateTime": ge.iso_utc(end), "timeZone": "UTC"})
    run = e.sync()
    assert run.stats["pulled"]["adopted"] == 1 and len(_rows(e)) == 3  # fixing it is enough


def test_an_all_day_note_in_the_calendar_is_not_a_session(env) -> None:
    e = env
    e.sync()
    cal = e.fake.only_calendar()
    e.fake.calendars[cal]["events"]["allday"] = {"id": "allday", "status": "confirmed", "updated": e.fake.now(), "summary": "Public holiday", "start": {"date": "2026-12-25"}, "end": {"date": "2026-12-26"}}
    run = e.sync()
    assert run.stats["pulled"]["adopted"] == 0 and run.stats["pulled"]["rejected_events"] == 0 and len(_rows(e)) == 2


def test_an_event_deleted_in_google_deletes_the_session_from_the_database(env) -> None:
    e = env
    e.sync()
    cal = e.fake.only_calendar()
    victim = _rows(e)[0]
    e.fake.admin_delete(cal, victim.google_event_id)
    run = e.sync()
    assert run.stats["pulled"]["deleted"] == 1 and run.stats["pulled"]["cancelled"] == 0
    assert victim.public_id not in {r.public_id for r in _rows(e)} and len(_rows(e)) == 1  # gone from OUR database
    assert len(e.fake.events(cal)) == 1  # and it was not recreated in Google


def test_deleting_an_event_whose_session_has_attendance_keeps_the_record_as_cancelled(env) -> None:
    e = env
    e.sync()
    cal = e.fake.only_calendar()
    victim = _rows(e)[0]

    async def mark(s):  # noqa: ANN001, ANN202
        s.add(Attendance(session_id=victim.id, student_id=e.world["s1"], recorded_by=e.world["tutor"], status="PRESENT", recorded_at=datetime.now(timezone.utc)))

    e.q(mark)
    e.fake.admin_delete(cal, victim.google_event_id)
    run = e.sync()
    assert run.stats["pulled"]["cancelled"] == 1 and run.stats["pulled"]["deleted"] == 0

    async def row(s):  # noqa: ANN001, ANN202
        return (await s.execute(select(BatchSession).where(BatchSession.id == victim.id))).scalar_one()

    kept = e.q(row)
    assert kept.cancelled_at is not None and "attendance" in kept.cancelled_reason  # the register survives, and says why
    assert len(e.fake.events(cal)) == 1


def test_a_title_starting_with_cancel_cancels_the_session_and_keeps_the_record(env) -> None:
    e = env
    e.sync()
    cal = e.fake.only_calendar()
    victim = _rows(e)[1]
    e.fake.admin_edit(cal, victim.google_event_id, summary="CANCELLED - room unavailable")
    run = e.sync()
    assert run.stats["pulled"]["cancelled"] == 1

    async def row(s):  # noqa: ANN001, ANN202
        return (await s.execute(select(BatchSession).where(BatchSession.id == victim.id))).scalar_one()

    kept = e.q(row)
    assert kept.cancelled_at is not None and kept.cancelled_reason == "Cancelled in Google Calendar" and kept.google_event_id is None
    assert len(e.fake.events(cal)) == 1  # the cancelled event is taken off everybody's calendar
    assert len(_rows(e)) == 1  # ...and the schedule no longer lists it


def test_a_cancelled_session_is_never_pushed_or_revived_by_later_runs(env) -> None:
    e = env
    e.sync()
    cal = e.fake.only_calendar()
    e.fake.admin_edit(cal, _rows(e)[1].google_event_id, summary="Cancel")
    e.sync()
    before = e.fake.writes()
    e.sync()
    assert e.fake.writes() == before and len(e.fake.events(cal)) == 1


def test_a_cancelled_session_no_longer_blocks_its_tutor(env) -> None:
    e = env

    async def other_batch_out_of_the_way(s):  # noqa: ANN001, ANN202
        # The fixture's second batch has the same tutor at the same times; clear it so the only
        # thing occupying the slot is the session about to be cancelled.
        await s.execute(text("DELETE FROM batch_sessions WHERE batch_id = :b"), {"b": e.world["batch_b"]})

    e.q(other_batch_out_of_the_way)
    e.sync()
    cal = e.fake.only_calendar()
    first = _rows(e)[0]
    slot = (first.session_start_time.astimezone(timezone.utc), first.session_end_time.astimezone(timezone.utc))

    e.fake.admin_create(cal, "while it is still scheduled", *slot, location="Zoom")
    refused = e.sync()
    assert refused.stats["pulled"]["rejected_events"] == 1  # the slot is taken: the tutor is teaching it

    e.fake.admin_edit(cal, first.google_event_id, summary="CANCEL")
    assert e.sync().stats["pulled"]["cancelled"] == 1
    e.fake.admin_create(cal, "replacement", *slot, location="Zoom")
    assert e.sync().stats["pulled"]["adopted"] == 1  # now the same slot is free


def test_a_move_that_double_books_the_tutor_is_refused_and_put_back(env) -> None:
    e = env
    e.sync()
    cal = e.fake.only_calendar()
    one, two = _rows(e)
    e.fake.admin_move(cal, two.google_event_id, one.session_start_time, one.session_end_time)  # onto the other session's slot
    run = e.sync()
    assert run.stats["pulled"]["rejected"] == 1
    assert _rows(e)[1].session_start_time.astimezone(timezone.utc) == e.world["t0"] + timedelta(days=1)


# ============================================================================================
# Enrolments: a guest list edited in Google is a PROPOSAL that waits for a person
# ============================================================================================


def _requests(e) -> list[dict[str, Any]]:  # noqa: ANN001
    async def f(s):  # noqa: ANN001, ANN202
        rows = (await s.execute(text("select kind, status, email, note from google_change_requests where batch_id = :b order by id"), {"b": e.world["batches"][0]})).all()
        return [dict(r._mapping) for r in rows]
    return e.q(f)


def _enrolled_emails(e) -> set[str]:  # noqa: ANN001
    async def f(s):  # noqa: ANN001, ANN202
        rows = await s.execute(text("select lower(u.email) from enrollments en join users u on u.id=en.student_id where en.batch_id=:b and en.status in ('PENDING','CONFIRMED','COMPLETED')"), {"b": e.world["batches"][0]})
        return {r[0] for r in rows.all() if r[0]}
    return e.q(f)


def test_a_student_added_as_a_guest_in_google_creates_a_pending_proposal_not_an_enrolment(env) -> None:
    e = env
    e.sync()
    cal = e.fake.only_calendar()
    before = _enrolled_emails(e)
    e.fake.admin_add_guest(cal, _rows(e)[0].google_event_id, f"{e.tag}.s3@t.test")
    run = e.sync()
    assert run.stats["pulled"]["change_requests"] == 1
    (req,) = _requests(e)
    assert (req["kind"], req["status"], req["email"]) == ("ENROL_ADD", "PENDING", f"{e.tag}.s3@t.test")
    assert _enrolled_emails(e) == before  # nothing was enrolled
    assert f"{e.tag}.s3@t.test" not in {a["email"] for a in e.fake.calendars[cal]["events"][_rows(e)[0].google_event_id].get("attendees", [])}  # and the guest list was put back


def test_a_student_removed_as_a_guest_creates_a_proposal_to_drop(env) -> None:
    e = env
    e.sync()
    cal = e.fake.only_calendar()
    event_id = _rows(e)[0].google_event_id
    e.fake.calendars[cal]["events"][event_id]["attendees"] = [a for a in e.fake.calendars[cal]["events"][event_id]["attendees"] if a["email"] != f"{e.tag}.s1@t.test"]
    e.fake.calendars[cal]["events"][event_id]["updated"] = e.fake.now()
    before = _enrolled_emails(e)
    e.sync()
    (req,) = _requests(e)
    assert (req["kind"], req["status"], req["email"]) == ("ENROL_REMOVE", "PENDING", f"{e.tag}.s1@t.test")
    assert _enrolled_emails(e) == before  # still enrolled
    assert f"{e.tag}.s1@t.test" in {a["email"] for a in e.fake.calendars[cal]["events"][event_id]["attendees"]}  # put back


def test_removing_a_guardian_or_a_tutor_is_not_an_enrolment_proposal(env) -> None:
    e = env
    e.sync()
    cal = e.fake.only_calendar()
    event_id = _rows(e)[0].google_event_id
    keep = [a for a in e.fake.calendars[cal]["events"][event_id]["attendees"] if a["email"] not in (f"{e.tag}.guardian@t.test", f"{e.tag}.tutor@t.test")]
    e.fake.admin_edit(cal, event_id, attendees=keep)
    e.sync()
    assert _requests(e) == []  # they are derived from enrolments, not enrolments themselves


def test_a_guest_who_is_not_a_student_is_reported_not_proposed(env) -> None:
    e = env
    e.sync()
    e.fake.admin_add_guest(e.fake.only_calendar(), _rows(e)[0].google_event_id, "stranger@evil.test")
    run = e.sync()
    assert _requests(e) == [] and any("no student account has that email" in x["reason"] for x in run.errors)


def test_the_same_edit_on_every_event_is_one_proposal_and_repeated_runs_do_not_multiply_it(env) -> None:
    e = env
    e.sync()
    cal = e.fake.only_calendar()
    for row in _rows(e):
        e.fake.admin_add_guest(cal, row.google_event_id, f"{e.tag}.s3@t.test")
    e.sync()
    e.fake.admin_add_guest(cal, _rows(e)[0].google_event_id, f"{e.tag}.s3@t.test")
    e.sync()
    assert len([r for r in _requests(e) if r["status"] == "PENDING"]) == 1


def test_a_proposal_that_was_already_done_in_the_lms_closes_itself(env) -> None:
    e = env
    e.sync()
    cal = e.fake.only_calendar()
    e.fake.admin_add_guest(cal, _rows(e)[0].google_event_id, f"{e.tag}.s3@t.test")
    e.sync()

    async def enrol(s):  # noqa: ANN001, ANN202
        await s.execute(text("UPDATE enrollments SET status='CONFIRMED' WHERE student_id=:s AND batch_id=:b"), {"s": e.world["s3"], "b": e.world["batches"][0]})

    e.q(enrol)
    e.sync()
    assert [r["status"] for r in _requests(e)] == ["SUPERSEDED"]


def test_proposals_are_not_made_when_inviting_is_off(env) -> None:
    e = env
    e.sync(invite_attendees=False)
    e.fake.admin_add_guest(e.fake.only_calendar(), _rows(e)[0].google_event_id, f"{e.tag}.s3@t.test")
    e.sync(invite_attendees=False)
    assert _requests(e) == []


def test_approving_a_proposal_enrols_the_student_and_the_calendar_then_agrees_without_a_new_proposal(env) -> None:
    """Regression: after an approval the LMS changes, and Google still holds our older guest list. That
    older list must not be mistaken for a fresh edit (it once proposed removing the student just added)."""
    from backend.services.google_change_service import GoogleChangeService

    e = env
    e.sync()
    cal = e.fake.only_calendar()
    e.fake.admin_add_guest(cal, _rows(e)[0].google_event_id, f"{e.tag}.s3@t.test")
    e.sync()
    (req,) = [r for r in _requests(e) if r["status"] == "PENDING"]

    async def approve(s):  # noqa: ANN001, ANN202
        actor = (await s.execute(select(User).where(User.username == "superadmin"))).scalar_one()
        rid = (await s.execute(text("select public_id from google_change_requests where batch_id=:b and status='PENDING'"), {"b": e.world["batches"][0]})).scalar_one()
        await GoogleChangeService(s).approve(rid, actor=actor)

    e.q(approve)
    assert f"{e.tag}.s3@t.test" in _enrolled_emails(e)
    run = e.sync()
    assert run.stats["pulled"]["change_requests"] == 0, run.errors  # no phantom "remove" proposal
    for row in _rows(e):
        assert f"{e.tag}.s3@t.test" in {a["email"] for a in e.fake.calendars[cal]["events"][row.google_event_id]["attendees"]}
    assert [r["status"] for r in _requests(e)] == ["APPROVED"] and req["kind"] == "ENROL_ADD"


def test_cancelled_sessions_are_hidden_from_the_schedule_and_refuse_attendance(env) -> None:
    from backend.core.errors import ConflictError
    from backend.schemas.attendance import AttendanceEntry
    from backend.services.attendance_service import AttendanceService
    from backend.services.session_service import SessionService

    e = env
    e.sync()
    victim = _rows(e)[0]
    e.fake.admin_edit(e.fake.only_calendar(), victim.google_event_id, summary="CANCEL")
    e.sync()

    async def attempt(s):  # noqa: ANN001, ANN202
        actor = (await s.execute(select(User).where(User.username == "superadmin"))).scalar_one()
        student = (await s.execute(select(User.public_id).where(User.id == e.world["s1"]))).scalar_one()
        with pytest.raises(ConflictError, match="cancelled"):
            await AttendanceService(s).mark(victim.public_id, [AttendanceEntry(student_id=student, status="PRESENT")], actor=actor)

    e.q(attempt)

    from backend.repositories.session import SessionRepository
    from backend.services.scope import ScopeResolver  # noqa: F401

    async def listing(s):  # noqa: ANN001, ANN202
        actor = (await s.execute(select(User).where(User.username == "superadmin"))).scalar_one()
        rows, _ = await SessionService(s).list_sessions(PageParams(limit=100, offset=0), actor=actor, batch_public_id=None)
        return {r.public_id for r in rows}

    from backend.schemas.base import PageParams

    visible = e.q(listing)
    assert victim.public_id not in visible


def test_a_cancelled_session_does_not_double_book_the_tutor_in_the_lms_either(env) -> None:
    from backend.repositories.session import SessionRepository

    e = env
    e.sync()
    victim = _rows(e)[0]
    e.fake.admin_edit(e.fake.only_calendar(), victim.google_event_id, summary="CANCEL")
    e.sync()

    async def clash(s):  # noqa: ANN001, ANN202
        return await SessionRepository(s).overlapping_for_tutor(
            tutor_id=e.world["tutor"], start=victim.session_start_time, end=victim.session_end_time)

    # Batch B's session (same tutor, same time) is what remains, so clear it to isolate the cancelled one.
    async def clear_b(s):  # noqa: ANN001, ANN202
        await s.execute(text("DELETE FROM batch_sessions WHERE batch_id = :b"), {"b": e.world["batch_b"]})

    e.q(clear_b)
    assert e.q(clash) is None


def test_a_session_saved_with_only_a_duration_still_reaches_google_with_an_end(env) -> None:
    """The API offers `duration_minutes` instead of an end time, which leaves the stored end empty."""
    e = env

    async def strip_end(s):  # noqa: ANN001, ANN202
        await s.execute(text("UPDATE batch_sessions SET session_end_time = NULL WHERE batch_id = :b"), {"b": e.world["batches"][0]})

    e.q(strip_end)
    run = e.sync()
    assert run.status == "SUCCEEDED", run.errors  # was: AttributeError on the first session
    for event in e.fake.events(e.fake.only_calendar()).values():
        start, end = event["start"]["dateTime"], event["end"]["dateTime"]
        assert (datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))) == timedelta(minutes=120)

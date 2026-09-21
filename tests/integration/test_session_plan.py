"""Previewing and replacing a batch's sessions, over real HTTP."""

from __future__ import annotations

import asyncio
import random
import selectors
from datetime import date, datetime, time, timedelta, timezone

import httpx
import pytest
from sqlalchemy import func, select, text

from backend.core.config import get_settings
from backend.db.manager import DatabaseManager
from backend.main import app
from backend.models.attendance import Attendance
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.security.password import hash_password
from backend.utils.enums import AttendanceStatus, CourseStatus, EnrollmentStatus, Platforms, UserStatus

PASSWORD = "Plan!Test2026xx"


def utc(*a: int) -> datetime:
    return datetime(*a, tzinfo=timezone.utc)


@pytest.fixture()
def world():
    tag = f"pl{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="plan-tests")
    ids: dict[str, str] = {}
    people: dict[str, dict] = {}
    tokens: dict[str, str] = {}

    async def build() -> None:
        async with db.session_factory.begin() as s:
            roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

            def person(key: str, role: str) -> User:
                email = f"{tag}.{key}@t.test"
                people[key] = {"email": email}
                return User(username=email, slug=f"{tag}-{key}", email=email, first_name=key.title(), last_name=tag, hashed_password=hash_password(PASSWORD),
                            status=UserStatus.ACTIVE, can_login=True, roles=[roles[role]])

            u = {k: person(k, r) for k, r in [("tutora", "TUTOR"), ("tutorb", "TUTOR"), ("stu", "STUDENT"), ("boss", "ADMIN")]}
            course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
            course.batches, course.resources, course.tags, course.tutors = [], [], [], []
            s.add_all([*u.values(), course])
            await s.flush()

            def batch(code: str, **kw) -> Batch:  # noqa: ANN003
                b = Batch(batch_code=f"{tag}-{code}", course_id=course.id, is_active=True, capacity=10, **kw)
                b.sessions, b.enrollments, b.student_reviews = [], [], []
                s.add(b)
                return b

            main = batch("A", start_date=date(2026, 9, 21), end_date=date(2026, 9, 25), number_of_sessions=2, training_days="Monday & Friday",
                         training_start_time=time(10, 0), class_duration_minutes=360, schedule_timezone="Europe/London")
            other = batch("B", start_date=date(2026, 9, 21), end_date=date(2026, 9, 25))
            bare = batch("C", start_date=date(2026, 9, 28), end_date=date(2026, 9, 28))
            await s.flush()

            def sess(b: Batch, tutor: User, start: datetime, hours: int = 6, **kw):  # noqa: ANN003, ANN202
                x = BatchSession(batch_id=b.id, tutor_id=tutor.id, session_start_time=start, session_end_time=start + timedelta(hours=hours), duration_minutes=hours * 60,
                                 platform=Platforms.Classroom, **kw)
                x.attendances = []
                s.add(x)
                return x

            marked = sess(main, u["tutora"], utc(2026, 9, 21, 9))                      # will hold attendance -> protected
            free = sess(main, u["tutora"], utc(2026, 9, 25, 9))                        # replaceable
            sess(other, u["tutorb"], utc(2026, 9, 21, 9))                              # another batch: tutorb is busy Monday 09:00-15:00Z
            s.add(Enrollments(batch_id=main.id, student_id=u["stu"].id, enrollment_date=datetime.now(timezone.utc), status=EnrollmentStatus.CONFIRMED))
            await s.flush()
            s.add(Attendance(session_id=marked.id, student_id=u["stu"].id, recorded_by=u["tutora"].id, status=AttendanceStatus.PRESENT))
            await s.flush()
            ids.update(main=str(main.public_id), bare=str(bare.public_id), tutora=str(u["tutora"].public_id), tutorb=str(u["tutorb"].public_id), free=str(free.public_id))
            for k, v in u.items():
                people[k]["public_id"] = str(v.public_id)

    loop.run_until_complete(build())
    lifespan = app.router.lifespan_context(app)
    loop.run_until_complete(lifespan.__aenter__())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")

    def call(who: str, method: str, path: str, **kw):  # noqa: ANN202
        async def go():  # noqa: ANN202
            if who not in tokens:
                ident, pwd = ("superadmin", "ConsoleDrive!2026") if who == "superadmin" else (people[who]["email"], PASSWORD)
                r = await client.post("/api/v1/auth/login", json={"identifier": ident, "password": pwd})
                assert r.status_code == 200, r.text
                tokens[who] = r.json()["access_token"]
            return await client.request(method, f"/api/v1{path}", headers={"Authorization": f"Bearer {tokens[who]}"}, **kw)
        return loop.run_until_complete(go())

    def live(batch_key: str = "main"):  # noqa: ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory() as s:
                b = (await s.execute(select(Batch).where(Batch.public_id == ids[batch_key]))).scalar_one()
                rows = (await s.execute(select(BatchSession.session_start_time, BatchSession.tutor_id).where(BatchSession.batch_id == b.id, BatchSession.cancelled_at.is_(None)).order_by(BatchSession.session_start_time))).all()
                return [r[0] for r in rows], b
        return loop.run_until_complete(go())

    ns = type("W", (), dict(tag=tag, ids=ids, people=people, call=staticmethod(call), live=staticmethod(live)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                await s.execute(text("DELETE FROM attendances WHERE session_id IN (SELECT id FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c))"), p)
                await s.execute(text("DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
                await s.execute(text("DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
                await s.execute(text("DELETE FROM batches WHERE batch_code LIKE :c"), p)
                await s.execute(text("DELETE FROM courses WHERE title LIKE :t"), p)
                await s.execute(text("DELETE FROM tokens WHERE user_id IN (SELECT id FROM users WHERE email LIKE :u)"), p)
                await s.execute(text("DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE email LIKE :u)"), p)
                await s.execute(text("DELETE FROM users WHERE email LIKE :u"), p)
        loop.run_until_complete(client.aclose())
        loop.run_until_complete(lifespan.__aexit__(None, None, None))
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def row(tutor: str, start: datetime, hours: int = 6, **extra):  # noqa: ANN003, ANN201
    return {"start_utc": start.isoformat(), "end_utc": (start + timedelta(hours=hours)).isoformat(), "tutor_id": tutor, "platform": "Classroom", **extra}


# ---------------------------------------------------------------------------- preview


def test_the_preview_is_built_from_the_batchs_own_schedule(world) -> None:
    r = world.call("boss", "POST", f"/batches/{world.ids['main']}/session-plan", json={"timezone": "Europe/London"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["settings"]["source"] == "the batch's schedule" and body["settings"]["training_days"] == "Monday & Friday"
    assert [s["start_local"] for s in body["sessions"]] == ["2026-09-21T10:00", "2026-09-25T10:00"] and [s["weekday"] for s in body["sessions"]] == ["Monday", "Friday"]
    assert [s["start_utc"][:16] for s in body["sessions"]] == ["2026-09-21T09:00", "2026-09-25T09:00"] and body["sessions"][0]["duration_minutes"] == 360


def test_switching_zone_proposes_the_same_moments_and_says_so(world) -> None:
    body = world.call("boss", "POST", f"/batches/{world.ids['main']}/session-plan", json={"timezone": "Asia/Dhaka"}).json()
    assert [s["start_local"] for s in body["sessions"]] == ["2026-09-21T15:00", "2026-09-25T15:00"]           # 10:00 BST is 15:00 in Dhaka
    assert [s["start_utc"][:16] for s in body["sessions"]] == ["2026-09-21T09:00", "2026-09-25T09:00"]       # ... the very same instants
    assert "same moment" in body["settings"]["note"] and body["settings"]["start_time"] == "15:00"


def test_the_preview_reports_what_already_exists_and_what_is_protected(world) -> None:
    ex = world.call("boss", "POST", f"/batches/{world.ids['main']}/session-plan", json={"timezone": "Europe/London"}).json()["existing"]
    assert (ex["total"], ex["protected"], ex["replaceable"]) == (2, 1, 1) and ex["protected_reasons"] == ["attendance recorded"]


def test_a_preview_can_be_adjusted_field_by_field(world) -> None:
    body = world.call("boss", "POST", f"/batches/{world.ids['main']}/session-plan",
                      json={"timezone": "Europe/London", "weekdays": [0, 2, 4], "start_time": "18:30", "duration_minutes": 90, "sessions": 3}).json()
    assert [s["start_local"] for s in body["sessions"]] == ["2026-09-21T18:30", "2026-09-23T18:30", "2026-09-25T18:30"] and body["sessions"][0]["duration_minutes"] == 90


def test_a_batch_with_no_schedule_falls_back_to_what_its_sessions_imply(world) -> None:
    async def strip() -> None:
        async with DatabaseManager(get_settings().database, application_name="x").session_factory.begin() as s:
            await s.execute(text("UPDATE batches SET training_days = NULL, training_start_time = NULL, class_duration_minutes = NULL WHERE batch_code LIKE :c"), {"c": f"{world.tag}-A"})

    asyncio.run(strip(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
    s = world.call("boss", "POST", f"/batches/{world.ids['main']}/session-plan", json={"timezone": "Europe/London"}).json()["settings"]
    assert s["source"] == "the existing sessions" and s["weekdays"] == [0, 4] and s["start_time"] == "10:00" and s["duration_minutes"] == 360


def test_an_empty_batch_gets_a_message_not_a_guess(world) -> None:
    body = world.call("boss", "POST", f"/batches/{world.ids['bare']}/session-plan", json={"timezone": "Europe/London"}).json()
    assert body["sessions"] == [] and "start time" in body["warnings"][0]


def test_an_unknown_zone_is_a_validation_error(world) -> None:
    assert world.call("boss", "POST", f"/batches/{world.ids['main']}/session-plan", json={"timezone": "Mars/Olympus"}).status_code == 422


# ---------------------------------------------------------------------------- replace


def test_replacing_needs_confirmation_when_sessions_would_go(world) -> None:
    r = world.call("boss", "POST", f"/batches/{world.ids['main']}/sessions/replace", json={"sessions": [row(world.ids["tutora"], utc(2026, 9, 28, 9))]})
    assert r.status_code == 409 and r.json()["details"] == {"replaceable": 1, "protected": 1}
    starts, _ = world.live()
    assert starts == [utc(2026, 9, 21, 9).replace(tzinfo=None) if starts[0].tzinfo is None else utc(2026, 9, 21, 9), starts[1]]   # nothing changed


def test_confirmed_replace_keeps_the_protected_session_and_replaces_the_rest(world) -> None:
    body = {"confirm_replace": True, "sessions": [
        row(world.ids["tutora"], utc(2026, 9, 21, 9)),      # the same moment as the protected one: skipped, not duplicated
        row(world.ids["tutora"], utc(2026, 9, 28, 9)), row(world.ids["tutora"], utc(2026, 10, 2, 9))]}
    r = world.call("boss", "POST", f"/batches/{world.ids['main']}/sessions/replace", json=body)
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 2, "replaced": 1, "kept_protected": 1, "skipped": 1, "total_sessions": 3}
    starts, batch = world.live()
    assert [x.replace(tzinfo=timezone.utc) for x in starts] == [utc(2026, 9, 21, 9), utc(2026, 9, 28, 9), utc(2026, 10, 2, 9)]
    assert batch.number_of_sessions == 3


def test_a_session_with_attendance_is_never_deleted(world) -> None:
    world.call("boss", "POST", f"/batches/{world.ids['main']}/sessions/replace", json={"confirm_replace": True, "sessions": [row(world.ids["tutora"], utc(2026, 11, 2, 9))]})
    starts, _ = world.live()
    assert utc(2026, 9, 21, 9) in [x.replace(tzinfo=timezone.utc) for x in starts]


def test_a_tutor_double_booking_refuses_everything_and_lists_the_clash(world) -> None:
    body = {"confirm_replace": True, "sessions": [row(world.ids["tutorb"], utc(2026, 9, 21, 10)), row(world.ids["tutora"], utc(2026, 9, 28, 9))]}
    r = world.call("boss", "POST", f"/batches/{world.ids['main']}/sessions/replace", json=body)
    assert r.status_code == 409 and r.json()["details"]["conflicts"][0]["session"] == 1 and r.json()["details"]["conflicts"][0]["with_batch"].endswith("-B")
    starts, _ = world.live()
    assert len(starts) == 2                                                                            # atomic: the good row was not created either


def test_two_proposed_sessions_for_one_tutor_cannot_overlap(world) -> None:
    body = {"confirm_replace": True, "sessions": [row(world.ids["tutora"], utc(2026, 9, 28, 9)), row(world.ids["tutora"], utc(2026, 9, 28, 12))]}
    r = world.call("boss", "POST", f"/batches/{world.ids['main']}/sessions/replace", json=body)
    assert r.status_code == 409 and r.json()["details"]["conflicts"][0]["with_batch"] == "another proposed session"


def test_the_sessions_being_replaced_do_not_count_as_clashes(world) -> None:
    """The replaceable Friday session is tutora's; proposing tutora at the same time is fine because it is going."""
    r = world.call("boss", "POST", f"/batches/{world.ids['main']}/sessions/replace", json={"confirm_replace": True, "sessions": [row(world.ids["tutora"], utc(2026, 9, 25, 9))]})
    assert r.status_code == 200 and r.json()["created"] == 1 and r.json()["replaced"] == 1


def test_the_schedule_used_is_saved_on_the_batch(world) -> None:
    body = {"confirm_replace": True, "sessions": [row(world.ids["tutora"], utc(2026, 9, 29, 13)), row(world.ids["tutora"], utc(2026, 10, 6, 13))],
            "schedule": {"timezone": "Asia/Dhaka", "weekdays": [1], "start_time": "19:00", "duration_minutes": 360}}
    assert world.call("boss", "POST", f"/batches/{world.ids['main']}/sessions/replace", json=body).status_code == 200
    _, b = world.live()
    assert (b.training_days, b.training_start_time, b.training_end_time, b.class_duration_minutes, b.schedule_timezone) == ("Tuesday", time(19, 0), time(1, 0), 360, "Asia/Dhaka")
    assert (b.training_start_day, b.training_end_day) == ("Tuesday", "Tuesday")


def test_a_row_without_a_tutor_who_teaches_is_refused(world) -> None:
    r = world.call("boss", "POST", f"/batches/{world.ids['main']}/sessions/replace", json={"confirm_replace": True, "sessions": [row(world.people["stu"]["public_id"], utc(2026, 9, 28, 9))]})
    assert r.status_code == 422


def test_bad_rows_are_refused(world) -> None:
    bad = {"start_utc": utc(2026, 9, 28, 9).isoformat(), "end_utc": utc(2026, 9, 28, 8).isoformat(), "tutor_id": world.ids["tutora"], "platform": "Zoom"}
    assert world.call("boss", "POST", f"/batches/{world.ids['main']}/sessions/replace", json={"confirm_replace": True, "sessions": [bad]}).status_code == 422
    twins = [row(world.ids["tutora"], utc(2026, 9, 28, 9)), row(world.ids["tutorb"], utc(2026, 9, 28, 9))]
    assert world.call("boss", "POST", f"/batches/{world.ids['main']}/sessions/replace", json={"confirm_replace": True, "sessions": twins}).status_code == 422


def test_only_people_who_may_create_and_delete_sessions_can_replace(world) -> None:
    body = {"confirm_replace": True, "sessions": [row(world.ids["tutora"], utc(2026, 9, 28, 9))]}
    assert world.call("tutora", "POST", f"/batches/{world.ids['main']}/sessions/replace", json=body).status_code == 403
    assert world.call("tutora", "POST", f"/batches/{world.ids['main']}/session-plan", json={"timezone": "UTC"}).status_code == 403
    assert world.call("stu", "POST", f"/batches/{world.ids['main']}/sessions/replace", json=body).status_code == 403


# ---------------------------------------------------------------------------- the batch list


def test_the_batch_list_carries_what_a_table_needs_and_can_search_and_sort(world) -> None:
    w = world
    listed = w.call("boss", "GET", "/batches", params={"q": w.tag, "limit": 10}).json()
    assert listed["total"] == 3
    first = listed["items"][0]
    assert first["batch_code"].endswith("-A") and first["course_title"] == f"{w.tag} Course" and first["training_days"] == "Monday & Friday"
    assert (first["session_count"], first["class_duration_minutes"], first["tutor_name"]) == (2, 360, f"Tutora {w.tag}")
    assert [i["session_count"] for i in listed["items"]] == [2, 1, 0]                    # A, B, C

    desc = w.call("boss", "GET", "/batches", params={"q": w.tag, "sort": "batch_code", "dir": "desc"}).json()["items"]
    assert [i["batch_code"][-1] for i in desc] == ["C", "B", "A"]
    assert [i["batch_code"][-1] for i in w.call("boss", "GET", "/batches", params={"q": "monday & fri"}).json()["items"] if i["batch_code"].startswith(w.tag)] == ["A"]   # days are searchable
    assert w.call("boss", "GET", "/batches", params={"q": w.tag, "limit": 2}).json()["total"] == 3                                                                      # total is not the page


def test_an_unknown_sort_column_is_refused_not_passed_to_the_database(world) -> None:
    assert world.call("boss", "GET", "/batches", params={"sort": "id; DROP TABLE batches"}).status_code == 422

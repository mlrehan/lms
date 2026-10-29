"""The academic sync (courses, batches, sessions, enrolments) against real Postgres,
with a fake LAIT API and fake course pages. Everything is created under a unique
tag and removed afterwards (audit rows are append-only and are left behind)."""

from __future__ import annotations

import asyncio
import random
import selectors
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select, text

from backend.core.config import get_settings
from backend.db.manager import DatabaseManager
from backend.integrations.lait_client import LaitClient
from backend.integrations.lait_pages import PageFetcher
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.user_sync import UserSyncRun
from backend.services.lait_academic_sync_service import LaitAcademicSyncService, refresh_course_statuses
from backend.utils.enums import CourseStatus, EnrollmentStatus, Levels

HOST = "https://www.londonacademyofit.co.uk"


def _page(duration: str, level: str, prereq: str, price: str = "Regular Price: \u00a3540") -> str:
    return (
        f'<span id="MainContent_lblPrice"><span>{price}</span></span><span id="MainContent_lblMinimumFee">From <b>\u00a3420</b></span>'
        f'<span id="MainContent_lblCourseDuration">{duration}</span>'
        f'<span id="MainContent_lblCourseLevel">{level}</span>'
        f'<span id="MainContent_lblPrerequisitesHTML"><p>{prereq}</p><p>Software Requirements</p><ul><li>Laptop</li></ul></span>'
    )


def _menu(category: str, urls: list[str]) -> str:
    links = "".join(f"<li><a href='{u}'>x</a></li>" for u in urls)
    return f"<li class='dropdown-item'><a href='{HOST}/courses/cat'>{category}</a><ul>{links}</ul></li>"


class Fake:
    def __init__(self) -> None:
        self.courses: list[dict[str, Any]] = []
        self.batches: list[dict[str, Any]] = []
        self.students: dict[int, list[dict[str, Any]]] = {}
        self.student_detail: dict[str, dict[str, Any]] = {}
        self.tutor_detail: dict[str, dict[str, Any]] = {}
        self.pages: dict[str, str] = {}

    def api(self, request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p == "/api/Courses":
            return httpx.Response(200, json=self.courses)
        if p == "/api/Batches/Upcoming":
            return httpx.Response(200, json=self.batches)
        if p.startswith("/api/Batches/") and p.endswith("/Students"):
            return httpx.Response(200, json=self.students.get(int(p.split("/")[3]), []))
        if p.startswith("/api/Students/guid/"):
            d = self.student_detail.get(p.rsplit("/", 1)[-1])
            return httpx.Response(200, json=d) if d else httpx.Response(404)
        if p.startswith("/api/Tutors/guid/"):
            d = self.tutor_detail.get(p.rsplit("/", 1)[-1])
            return httpx.Response(200, json=d) if d else httpx.Response(404)
        return httpx.Response(404)

    def web(self, request: httpx.Request) -> httpx.Response:
        html = self.pages.get(str(request.url))
        return httpx.Response(200, text=html) if html else httpx.Response(404)


@pytest.fixture()
def env():
    n = random.randint(100000, 900000)
    tag = f"ac{n}"
    fake = Fake()
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    settings = get_settings()
    settings = settings.model_copy(update={"lait": settings.lait.model_copy(
        update={"api_base_url": "https://lait.test", "api_key": SecretStr("k")})})
    db = DatabaseManager(settings.database, application_name="academic-tests")

    uk_today = datetime.now(ZoneInfo("Europe/London")).date()
    course_url = f"{HOST}/training-course/{tag}-a"
    guids = {k: str(uuid.uuid4()) for k in ("tutor", "s1", "s2", "s3")}

    fake.courses = [{
        "course_id": n, "course_title": f"{tag} Python", "small_course_image": "https://x/s.jpg",
        "course_image": "https://x/l.jpg", "course_details": "Learn.\r\n", "course_duration": 9, "is_live": True,
        "course_url": course_url,
    }]
    fake.pages[course_url] = _page("12 Hours", "Intermediate to Advanced", "Basic Python") + _menu(f"{tag} Category", [course_url])
    fake.tutor_detail[guids["tutor"]] = {
        "tutor_id": n, "user_id": guids["tutor"], "title": "Mr", "first_name": "Tia", "middle_name": "", "last_name": tag,
        "email_id": f"{tag}.tutor@sync.test", "is_public": True}

    def batch(bid: int, start, days: str, sessions: int, **over: Any) -> dict[str, Any]:
        b = {"batch_id": bid, "course_id": n, "Course_title": f"{tag} Python", "training_days": days,
             "training_start_date": f"{start.isoformat()}T10:00:00", "training_end_date": f"{(start + timedelta(days=6)).isoformat()}T10:00:00",
             "training_start_time": "10:00 AM", "training_end_time": "04:00 PM", "training_sessions": sessions,
             "class_duration_h": 6, "class_duration_m": 0, "method_name": "Online Training using Zoom", "tutor_id": n,
             "tutor_user_id": guids["tutor"], "tutor_name": "Mr Tia", "batch_is_active": True, "total_admission": 2}
        b.update(over)
        return b

    day = uk_today.strftime("%A")
    fake.batches = [batch(n + 1, uk_today, day, 1)]  # running today

    def student(k: str, i: int) -> dict[str, Any]:
        return {"StudentID": n + i, "UserID": guids[k], "UserName": f"{tag}.{k}@sync.test", "Email": f"{tag}.{k}@sync.test",
                "FirstName": "Stu", "LastName": k, "CompanyName": f"{tag} Corp", "CountryName": "United Kingdom",
                "RegistrationDate": "2026-07-01T09:30:00", "Roles": ["Student"]}

    fake.student_detail = {guids["s1"]: student("s1", 1), guids["s2"]: student("s2", 2)}
    fake.students = {n + 1: [
        {"student_id": n + 1, "user_name": f"{tag}.s1@sync.test", "user_id": guids["s1"], "admission_id": 5001},
        {"student_id": n + 2, "user_name": f"{tag}.s2@sync.test", "user_id": guids["s2"], "admission_id": 5002}]}

    run_ids: list[int] = []  # only the runs THIS test created are ever deleted

    def sync(dry_run: bool = False) -> UserSyncRun:
        async def go() -> UserSyncRun:
            client = LaitClient(settings.lait, transport=httpx.MockTransport(fake.api))
            fetcher = PageFetcher(settings.lait.course_page_hosts, transport=httpx.MockTransport(fake.web))
            async with client, fetcher:
                svc = LaitAcademicSyncService(db.session_factory, settings, client=client, fetcher=fetcher)
                run = await svc.run(trigger_type="MANUAL", triggered_by_user_id=None, dry_run=dry_run)
                run_ids.append(run.id)
                return run
        return loop.run_until_complete(go())

    def q(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    def commit(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    ctx = type("Ctx", (), dict(n=n, tag=tag, fake=fake, sync=sync, q=q, commit=commit, batch=staticmethod(batch),
                               guids=guids, course_url=course_url, uk_today=uk_today, settings=settings, db=db, loop=loop))
    try:
        yield ctx
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                await s.execute(text("DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code = ANY(:c))"), {"c": [str(n + i) for i in range(0, 20)]})
                await s.execute(text("DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code = ANY(:c))"), {"c": [str(n + i) for i in range(0, 20)]})
                await s.execute(text("DELETE FROM batches WHERE batch_code = ANY(:c)"), {"c": [str(n + i) for i in range(0, 20)]})
                await s.execute(text("DELETE FROM courses WHERE title LIKE :t OR code = :c"), {"t": f"{tag}%", "c": str(n)})
                await s.execute(text("DELETE FROM categories WHERE name LIKE :t"), {"t": f"{tag}%"})
                await s.execute(text("DELETE FROM organizations WHERE name LIKE :t"), {"t": f"{tag}%"})
                await s.execute(delete(User).where(User.username.like(f"{tag}.%")))
                if run_ids:
                    await s.execute(delete(UserSyncRun).where(UserSyncRun.id.in_(run_ids)))
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _course(e):  # noqa: ANN001, ANN202
    async def f(s):  # noqa: ANN001, ANN202
        return (await s.execute(select(Course).where(Course.code == str(e.n)))).scalar_one_or_none()
    return e.q(f)


def _batch(e, i=1):  # noqa: ANN001, ANN202
    async def f(s):  # noqa: ANN001, ANN202
        return (await s.execute(select(Batch).where(Batch.batch_code == str(e.n + i)))).scalar_one_or_none()
    return e.q(f)


def _counts(e):  # noqa: ANN001, ANN202
    async def f(s):  # noqa: ANN001, ANN202
        ids = [str(e.n + i) for i in range(0, 20)]
        return {
            "batches": (await s.execute(text("select count(*) from batches where batch_code = any(:c)"), {"c": ids})).scalar_one(),
            "sessions": (await s.execute(text("select count(*) from batch_sessions where batch_id in (select id from batches where batch_code = any(:c))"), {"c": ids})).scalar_one(),
            "enrollments": (await s.execute(text("select count(*) from enrollments where batch_id in (select id from batches where batch_code = any(:c))"), {"c": ids})).scalar_one(),
            "courses": (await s.execute(text("select count(*) from courses where code = :c"), {"c": str(e.n)})).scalar_one(),
        }
    return e.q(f)


# ------------------------------------------------------------------- happy path


def test_a_full_sync_builds_course_batch_sessions_and_enrolments(env) -> None:
    e = env
    run = e.sync()
    assert run.status == "SUCCEEDED", run.errors
    s = run.stats
    assert (s["courses"]["created"], s["batches"]["created"], s["sessions"]["created"], s["enrollments"]["created"]) == (1, 1, 1, 2)

    c = _course(e)
    assert c.title == f"{e.tag} Python" and c.level is Levels.INTERMEDIATE and c.duration_hours == 12  # the page beats the API's 9
    assert c.prerequisites == "Basic Python" and "Laptop" not in c.prerequisites
    assert c.price == 540.0  # the regular price, not the 420 batch price
    assert c.small_course_image == "https://x/s.jpg" and c.course_image == "https://x/l.jpg"
    assert c.description == "Learn." and c.course_link == e.course_url
    assert c.category is not None and c.category.name == f"{e.tag} Category"
    assert c.status is CourseStatus.RUNNING  # a batch is in progress today

    b = _batch(e)
    assert b.capacity == 25 and b.number_of_sessions == 1 and b.duration_hours == 6 and b.total_enrollments == 2
    assert b.notes.startswith("Auto: ") and str(e.n + 1) in b.notes

    # The run records WHICH records it created, so "which batch did the last
    # sync add?" has an answer -- and the batch carries its creation time.
    created = s["created"]
    assert [x["batch_code"] for x in created["batches"]] == [b.batch_code]
    assert [x["title"] for x in created["courses"]] == [c.title]
    assert created["enrollments_by_batch"] == {b.batch_code: 2}
    assert b.created_at is not None


def test_session_times_are_stored_in_utc(env) -> None:
    e = env
    e.sync()

    async def f(s):  # noqa: ANN001, ANN202
        b = (await s.execute(select(Batch).where(Batch.batch_code == str(e.n + 1)))).scalar_one()
        return (await s.execute(select(BatchSession).where(BatchSession.batch_id == b.id))).scalars().all()

    (row,) = e.q(f)
    expected = datetime.combine(e.uk_today, datetime.min.time().replace(hour=10), tzinfo=ZoneInfo("Europe/London")).astimezone(timezone.utc)
    assert row.session_start_time == expected and row.duration_minutes == 360
    assert row.session_end_time == expected + timedelta(hours=6)
    assert row.platform.name == "Zoom" and row.meeting_link is None and row.recording_link is None


def test_the_tutor_and_students_are_created_on_demand_without_login_access(env) -> None:
    e = env
    e.sync()

    async def f(s):  # noqa: ANN001, ANN202
        users = (await s.execute(select(User).where(User.username.like(f"{e.tag}.%")))).scalars().all()
        return {u.username: u for u in users}

    users = e.q(f)
    assert set(users) == {f"{e.tag}.tutor@sync.test", f"{e.tag}.s1@sync.test", f"{e.tag}.s2@sync.test"}
    assert all(u.can_login is False for u in users.values())
    assert [r.name for r in users[f"{e.tag}.tutor@sync.test"].roles] == ["TUTOR"]


def test_a_company_becomes_one_organisation_shared_by_its_students(env) -> None:
    e = env
    e.sync()

    async def f(s):  # noqa: ANN001, ANN202
        orgs = (await s.execute(text("select id from organizations where name = :n"), {"n": f"{e.tag} Corp"})).all()
        ens = (await s.execute(select(Enrollments).join(Batch).where(Batch.batch_code == str(e.n + 1)))).scalars().all()
        return len(orgs), {x.organization_id for x in ens}

    n_orgs, org_ids = e.q(f)
    assert n_orgs == 1 and len(org_ids) == 1 and None not in org_ids


def test_enrolments_are_confirmed_by_the_sync_actor_with_their_admission_ids(env) -> None:
    e = env
    e.sync()

    async def f(s):  # noqa: ANN001, ANN202
        return (await s.execute(select(Enrollments).join(Batch).where(Batch.batch_code == str(e.n + 1)))).scalars().all()

    rows = e.q(f)
    assert {r.admission_id for r in rows} == {5001, 5002}
    assert all(r.status is EnrollmentStatus.CONFIRMED and r.is_transfer is False and r.previous_enrollment_id is None for r in rows)
    assert all(r.enrolled_by is not None for r in rows)


def test_a_second_batch_links_each_student_to_their_previous_enrolment(env) -> None:
    e = env
    e.sync()
    e.fake.batches.append(e.batch(e.n + 2, e.uk_today + timedelta(days=30), (e.uk_today + timedelta(days=30)).strftime("%A"), 1))
    e.fake.students[e.n + 2] = [e.fake.students[e.n + 1][0]]  # student 1 again
    e.sync()

    async def f(s):  # noqa: ANN001, ANN202
        first = (await s.execute(select(Enrollments).join(Batch).where(Batch.batch_code == str(e.n + 1), Enrollments.admission_id == 5001))).scalar_one()
        second = (await s.execute(select(Enrollments).join(Batch).where(Batch.batch_code == str(e.n + 2)))).scalar_one()
        return first.enrollment_id, second.previous_enrollment_id

    first_id, prev = e.q(f)
    assert prev == first_id


def test_a_corporate_manager_is_flagged_on_the_enrolment(env) -> None:
    e = env
    e.fake.student_detail[e.guids["s1"]]["Roles"] = ["CorporateManager"]
    e.sync()

    async def f(s):  # noqa: ANN001, ANN202
        return {r.admission_id: r.is_manager for r in (await s.execute(select(Enrollments).join(Batch).where(Batch.batch_code == str(e.n + 1)))).scalars().all()}

    flags = e.q(f)
    assert flags == {5001: True, 5002: False}


# ---------------------------------------------------------------- idempotence


def test_a_second_run_changes_nothing(env) -> None:
    e = env
    e.sync()
    before = _counts(e)
    again = e.sync()
    s = again.stats
    assert (s["courses"]["created"], s["batches"]["created"], s["sessions"]["created"], s["enrollments"]["created"]) == (0, 0, 0, 0)
    assert (s["courses"]["unchanged"], s["batches"]["unchanged"], s["enrollments"]["unchanged"]) == (1, 1, 2)
    assert _counts(e) == before
    assert s["created"] == {"enrollments_by_batch": {}}  # a run that created nothing lists nothing


def test_a_dry_run_persists_nothing(env) -> None:
    e = env
    run = e.sync(dry_run=True)
    assert run.stats["courses"]["created"] == 1 and run.stats["batches"]["created"] == 1
    assert _counts(e) == {"batches": 0, "sessions": 0, "enrollments": 0, "courses": 0}


# ------------------------------------------------------- local ownership


def test_administrator_edits_survive_a_resync(env) -> None:
    e = env
    e.sync()

    async def tamper(s):  # noqa: ANN001, ANN202
        b = (await s.execute(select(Batch).where(Batch.batch_code == str(e.n + 1)))).scalar_one()
        b.capacity, b.notes = 40, "Custom note"
        sess = (await s.execute(select(BatchSession).where(BatchSession.batch_id == b.id))).scalars().one()
        sess.meeting_link = "https://zoom.example/j/1"
        en = (await s.execute(select(Enrollments).where(Enrollments.batch_id == b.id, Enrollments.admission_id == 5001))).scalar_one()
        en.status = EnrollmentStatus.DROPPED
        c = (await s.execute(select(Course).where(Course.code == str(e.n)))).scalar_one()
        c.category_id = None
        await s.commit()

    e.q(tamper)
    e.fake.pages[e.course_url] = _page("12 Hours", "Beginner", "Changed") + _menu(f"{e.tag} Category", [e.course_url])
    e.sync()

    async def read(s):  # noqa: ANN001, ANN202
        b = (await s.execute(select(Batch).where(Batch.batch_code == str(e.n + 1)))).scalar_one()
        sess = (await s.execute(select(BatchSession).where(BatchSession.batch_id == b.id))).scalars().one()
        en = (await s.execute(select(Enrollments).where(Enrollments.batch_id == b.id, Enrollments.admission_id == 5001))).scalar_one()
        return b, sess, en

    b, sess, en = e.q(read)
    assert (b.capacity, b.notes) == (40, "Custom note")  # not overwritten
    assert sess.meeting_link == "https://zoom.example/j/1"
    assert en.status is EnrollmentStatus.DROPPED  # a drop is never undone by the feed
    assert _course(e).prerequisites == "Changed"  # ...but LAIT still owns what it sends


def test_a_category_an_administrator_chose_is_kept(env) -> None:
    e = env
    e.sync()

    async def pick(s):  # noqa: ANN001, ANN202
        await s.execute(text("insert into categories (name, public_id) values (:n, gen_random_uuid())"), {"n": f"{e.tag} Mine"})
        cid = (await s.execute(text("select id from categories where name = :n"), {"n": f"{e.tag} Mine"})).scalar_one()
        await s.execute(text("update courses set category_id = :c where code = :k"), {"c": cid, "k": str(e.n)})
        await s.commit()

    e.q(pick)
    e.sync()
    assert _course(e).category.name == f"{e.tag} Mine"


def test_a_locally_deleted_course_is_not_restored(env) -> None:
    e = env
    e.sync()

    async def rm(s):  # noqa: ANN001, ANN202
        await s.execute(text("update courses set is_deleted = true where code = :k"), {"k": str(e.n)})
        await s.commit()

    e.q(rm)
    run = e.sync()
    assert run.stats["courses"]["skipped"] == 1 and "deleted locally" in run.errors[0]["reason"]


def test_a_different_course_with_the_same_title_is_skipped_not_merged(env) -> None:
    e = env

    async def other(s):  # noqa: ANN001, ANN202
        await s.execute(text("insert into courses (public_id, title, code, status, level, is_deleted, created_at) values (gen_random_uuid(), :t, :c, 'DRAFT', 'BEGINNER', false, now())"), {"t": f"{e.tag} Python", "c": f"X{e.n}"})
        await s.commit()

    e.q(other)
    run = e.sync()
    assert run.stats["courses"]["skipped"] == 1
    assert "already has this title" in run.errors[0]["reason"]
    assert _course(e) is None  # the code-matched course was not created, and the other one was not adopted


# ---------------------------------------------------------- degraded inputs


def test_a_course_page_that_cannot_be_fetched_still_creates_the_course(env) -> None:
    e = env
    e.fake.pages.clear()
    run = e.sync()
    c = _course(e)
    assert run.status in ("SUCCEEDED", "PARTIAL") and c is not None
    assert c.duration_hours == 9 and c.level is Levels.BEGINNER and c.prerequisites is None and c.category is None


def test_a_batch_for_a_course_missing_from_the_live_feed_creates_a_minimal_course(env) -> None:
    e = env
    e.fake.courses = []
    e.sync()
    c = _course(e)
    assert c is not None and c.title == f"{e.tag} Python" and _batch(e) is not None


def test_an_unknown_student_is_skipped_with_a_reason(env) -> None:
    e = env
    e.fake.student_detail.pop(e.guids["s2"])
    run = e.sync()
    assert run.stats["enrollments"]["created"] == 1 and run.stats["enrollments"]["skipped"] == 1
    assert any("not known to LAIT" in x["reason"] for x in run.errors)


def test_a_batch_whose_tutor_is_unknown_keeps_the_batch_and_loses_only_its_sessions(env) -> None:
    e = env
    e.fake.tutor_detail.clear()
    run = e.sync()
    assert any("sessions not generated" in x["reason"] and "tutor" in x["reason"] for x in run.errors)
    assert _batch(e) is not None and _counts(e)["sessions"] == 0
    assert run.stats["sessions"]["skipped"] == 1 and run.stats["batches"]["created"] == 1


def test_a_removed_untouched_session_is_deleted_but_one_with_history_is_kept(env) -> None:
    e = env
    e.fake.batches = [e.batch(e.n + 1, e.uk_today, "Mon, Wed & Fri", 3, training_end_date=f"{(e.uk_today + timedelta(days=6)).isoformat()}T10:00:00")]
    e.sync()
    assert _counts(e)["sessions"] == 3

    async def annotate(s):  # noqa: ANN001, ANN202
        b = (await s.execute(select(Batch).where(Batch.batch_code == str(e.n + 1)))).scalar_one()
        last = (await s.execute(select(BatchSession).where(BatchSession.batch_id == b.id).order_by(BatchSession.session_start_time.desc()))).scalars().first()
        last.tutor_notes = "history"
        await s.commit()

    e.q(annotate)
    e.fake.batches = [e.batch(e.n + 1, e.uk_today, "Mon, Wed & Fri", 1, training_end_date=f"{(e.uk_today + timedelta(days=6)).isoformat()}T10:00:00")]
    e.sync()
    # Session 1 is still scheduled, session 2 was untouched and left the schedule (deleted),
    # session 3 left the schedule but carries history (kept).
    async def notes(s):  # noqa: ANN001, ANN202
        b = (await s.execute(select(Batch).where(Batch.batch_code == str(e.n + 1)))).scalar_one()
        return [r.tutor_notes for r in (await s.execute(select(BatchSession).where(BatchSession.batch_id == b.id).order_by(BatchSession.session_start_time))).scalars().all()]

    assert e.q(notes) == [None, "history"]


# ---------------------------------------------------------------- course status


def test_course_status_follows_the_calendar_and_leaves_manual_states_alone(env) -> None:
    e = env
    e.sync()
    assert _course(e).status is CourseStatus.RUNNING

    async def end_batch(s):  # noqa: ANN001, ANN202
        await s.execute(text("update batches set start_date = current_date - 10, end_date = current_date - 3 where batch_code = :c"), {"c": str(e.n + 1)})
        await s.commit()

    e.q(end_batch)
    result = e.loop.run_until_complete(refresh_course_statuses(e.db.session_factory))
    assert result["stopped"] >= 1 and _course(e).status is CourseStatus.PUBLISHED

    async def archive(s):  # noqa: ANN001, ANN202
        await s.execute(text("update courses set status='ARCHIVED' where code = :k"), {"k": str(e.n)})
        await s.execute(text("update batches set start_date = current_date - 1, end_date = current_date + 1 where batch_code = :c"), {"c": str(e.n + 1)})
        await s.commit()

    e.q(archive)
    e.loop.run_until_complete(refresh_course_statuses(e.db.session_factory))
    assert _course(e).status is CourseStatus.ARCHIVED  # an administrator's decision stands


def test_an_inactive_batch_does_not_make_a_course_running(env) -> None:
    e = env
    e.fake.batches[0]["batch_is_active"] = False
    e.sync()
    assert _course(e).status is CourseStatus.PUBLISHED


def test_the_price_follows_the_page_when_it_changes(env) -> None:
    e = env
    e.sync()
    e.fake.pages[e.course_url] = _page("12 Hours", "Beginner", "x", "Regular Price: \u00a3600") + _menu(f"{e.tag} Category", [e.course_url])
    e.sync()
    assert _course(e).price == 600.0


def test_an_uploaded_image_survives_a_resync_but_external_urls_still_refresh(env) -> None:
    e = env
    e.sync()

    async def upload(s):  # noqa: ANN001, ANN202
        await s.execute(text("update courses set course_image = :k where code = :c"), {"k": "courses/x/full/abc123.webp", "c": str(e.n)})
        await s.commit()

    e.q(upload)
    e.fake.courses[0]["course_image"] = "https://x/NEW-full.jpg"
    e.fake.courses[0]["small_course_image"] = "https://x/NEW-small.jpg"
    e.sync()
    c = _course(e)
    assert c.course_image == "courses/x/full/abc123.webp"  # the administrator's upload is theirs
    assert c.small_course_image == "https://x/NEW-small.jpg"  # a URL LAIT supplied is refreshed



def test_the_lait_sync_never_deletes_a_session_that_was_created_in_google_or_the_lms(env) -> None:
    """A session someone created is a decision. When LAIT's schedule shrinks, only sessions LAIT itself
    derived may be removed."""
    e = env
    e.fake.batches = [e.batch(e.n + 1, e.uk_today, "Mon, Wed & Fri", 3, training_end_date=f"{(e.uk_today + timedelta(days=6)).isoformat()}T10:00:00")]
    e.sync()

    async def relabel(s):  # noqa: ANN001, ANN202
        b = (await s.execute(select(Batch).where(Batch.batch_code == str(e.n + 1)))).scalar_one()
        rows = (await s.execute(select(BatchSession).where(BatchSession.batch_id == b.id).order_by(BatchSession.session_start_time))).scalars().all()
        rows[1].origin = "GOOGLE"   # created in Google Calendar
        rows[2].origin = "MANUAL"   # created in the LMS
        await s.commit()

    e.q(relabel)
    e.fake.batches = [e.batch(e.n + 1, e.uk_today, "Mon, Wed & Fri", 1, training_end_date=f"{(e.uk_today + timedelta(days=6)).isoformat()}T10:00:00")]
    e.sync()
    assert _counts(e)["sessions"] == 3  # nothing was removed: the two extras are somebody's decision

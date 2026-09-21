"""The calendar window: who sees which sessions, and that the window is honoured."""

from __future__ import annotations

import asyncio
import random
import selectors
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.core.errors import NotFoundError
from backend.core.privacy import set_viewer
from backend.db.manager import DatabaseManager
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.guardian import StudentGuardian
from backend.models.identity.user import User
from backend.services.session_overview_service import SessionOverviewService
from backend.services.session_service import SessionService
from backend.utils.enums import CourseStatus, EnrollmentStatus, Platforms, UserStatus


@pytest.fixture()
def env():
    tag = f"cal{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="calendar-tests")
    world: dict = {}
    t0 = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(days=2)

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

        def user(name: str, role: str) -> User:
            return User(username=f"{tag}.{name}", slug=f"{tag}-{name}", email=f"{tag}.{name}@t.test", hashed_password="x",
                        status=UserStatus.ACTIVE, roles=[roles[role]])

        tutor, stu_a, stu_b = user("tutor", "TUTOR"), user("stua", "STUDENT"), user("stub", "STUDENT")
        classmate = user("mate", "STUDENT")
        guardian = user("guardian", "STUDENT")  # role is irrelevant here; only the link matters
        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([tutor, stu_a, stu_b, classmate, guardian, course])
        await s.flush()
        s.add(StudentGuardian(guardian_id=guardian.id, student_id=stu_a.id, relationship_type="Parent", is_primary=True, created_at=datetime.now(timezone.utc)))
        batches = []
        for code in ("A", "B"):
            b = Batch(batch_code=f"{tag}-{code}", course_id=course.id, start_date=date.today(), end_date=date.today() + timedelta(days=30), is_active=True, capacity=10)
            b.sessions, b.enrollments, b.student_reviews = [], [], []
            s.add(b)
            batches.append(b)
        await s.flush()
        for b, day in ((batches[0], 0), (batches[0], 20), (batches[1], 1)):
            sess = BatchSession(batch_id=b.id, tutor_id=tutor.id, session_start_time=t0 + timedelta(days=day), session_end_time=None,
                                duration_minutes=90, platform=Platforms.Zoom)
            sess.attendances = []
            s.add(sess)
        s.add(Enrollments(batch_id=batches[0].id, student_id=stu_a.id, enrollment_date=datetime.now(timezone.utc), status=EnrollmentStatus.CONFIRMED))
        s.add(Enrollments(batch_id=batches[0].id, student_id=classmate.id, enrollment_date=datetime.now(timezone.utc), status=EnrollmentStatus.CONFIRMED))
        s.add(Enrollments(batch_id=batches[1].id, student_id=stu_b.id, enrollment_date=datetime.now(timezone.utc), status=EnrollmentStatus.CONFIRMED))
        await s.flush()
        world.update(a=batches[0].public_id, b=batches[1].public_id, stu_a=stu_a.username, stu_b=stu_b.username, tutor=tutor.username)

    run(build)

    ns = type("Env", (), dict(tag=tag, world=world, run=staticmethod(run), t0=t0))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                await s.execute(text("DELETE FROM student_guardians WHERE guardian_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
                await s.execute(text("DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
                await s.execute(text("DELETE FROM batches WHERE batch_code LIKE :c"), p)
                await s.execute(text("DELETE FROM courses WHERE title LIKE :t"), p)
                await s.execute(text("DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM users WHERE username LIKE :u"), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def test_a_student_sees_only_the_batch_they_are_enrolled_in(env) -> None:
    # Read the batch code inside the session: the rows are detached once it closes.
    def codes(username, **kw):  # noqa: ANN001, ANN202
        async def g(s):  # noqa: ANN001, ANN202
            actor = (await s.execute(select(User).where(User.username == username))).scalar_one()
            rows = await SessionService(s).calendar(actor=actor, start=env.t0 - timedelta(days=1), end=env.t0 + timedelta(days=kw.get("days", 30)), batch_public_id=kw.get("batch"), limit=100)
            return sorted(r.batch.batch_code for r in rows)
        return env.run(g)

    assert codes(env.world["stu_a"]) == [f"{env.tag}-A", f"{env.tag}-A"]   # never batch B
    assert codes(env.world["stu_b"]) == [f"{env.tag}-B"]
    assert len(codes(env.world["tutor"])) == 3                            # the tutor teaches all three
    assert codes("superadmin", batch=env.world["b"]) == [f"{env.tag}-B"]   # the batch filter narrows


def test_the_window_excludes_sessions_outside_it(env) -> None:
    def count(username, days):  # noqa: ANN001, ANN202
        async def g(s):  # noqa: ANN001, ANN202
            actor = (await s.execute(select(User).where(User.username == username))).scalar_one()
            return len(await SessionService(s).calendar(actor=actor, start=env.t0 - timedelta(days=1), end=env.t0 + timedelta(days=days), batch_public_id=None, limit=100))
        return env.run(g)

    assert count(env.world["tutor"], 10) == 2    # the day-20 session is outside a 10-day window
    assert count(env.world["tutor"], 30) == 3


def _overview(env, username: str, *, which: int = 0, batch: str = "a"):  # noqa: ANN001, ANN202
    async def g(s):  # noqa: ANN001, ANN202
        actor = (await s.execute(select(User).where(User.username == username))).scalar_one()
        rows = (await s.execute(select(BatchSession.public_id).join(Batch, Batch.id == BatchSession.batch_id)
                                .where(Batch.public_id == env.world[batch]).order_by(BatchSession.session_start_time))).scalars().all()
        set_viewer(actor)  # what `get_current_user` does for a real request
        return await SessionOverviewService(s).overview(rows[which], actor=actor)
    return env.run(g)


def test_an_administrator_sees_the_whole_roster_with_guardians_and_contact_details(env) -> None:
    o = _overview(env, "superadmin")
    assert (o["number"], o["total"]) == (1, 2) and _overview(env, "superadmin", which=1)["number"] == 2
    assert sorted(r["student"]["name"] for r in o["roster"]) == [f"{env.tag}.mate", f"{env.tag}.stua"] and o["can_see_contacts"] and not o["roster_is_partial"]
    mine = next(r for r in o["roster"] if r["student"]["name"].endswith(".stua"))
    assert mine["student"]["email"] == f"{env.tag}.stua@t.test"
    assert [(g["name"], g["detail"]) for g in mine["guardians"]] == [(f"{env.tag}.guardian", "Parent")]
    assert o["batch"]["enrolled"] == 2  # counted live, whatever the cached column says
    assert o["tutor"]["name"] == f"{env.tag}.tutor" and o["course"]["title"] == f"{env.tag} Course"


def test_a_student_sees_only_themselves_and_no_contact_details(env) -> None:
    o = _overview(env, env.world["stu_a"])
    assert [r["student"]["name"] for r in o["roster"]] == [f"{env.tag}.stua"]
    r = o["roster"][0]
    assert r["student"]["email"] is None and r["guardians"] == [] and r["managers"] == []
    assert o["batch"]["enrolled"] is None and o["tutor"]["email"] is None and o["tutor_notes"] is None and not o["can_see_contacts"] and o["roster_is_partial"]


def test_a_tutor_sees_the_batch_and_its_guardians_by_name_but_no_contact_details(env) -> None:
    o = _overview(env, env.world["tutor"])
    assert len(o["roster"]) == 2 and not o["roster_is_partial"] and o["batch"]["enrolled"] == 2
    guardians = [g for r in o["roster"] for g in r["guardians"]]
    assert [g["name"] for g in guardians] == [f"{env.tag}.guardian"]
    # Names, never how to reach anyone outside the platform.
    assert not o["can_see_contacts"]
    assert all(r["student"]["email"] is None and r["student"]["phone"] is None for r in o["roster"])
    assert guardians[0]["email"] is None and o["tutor"]["email"] is None


def test_a_session_outside_ones_scope_is_a_404_not_a_leak(env) -> None:
    with pytest.raises(NotFoundError):
        _overview(env, env.world["stu_b"], batch="a")  # stu_b is only in batch B

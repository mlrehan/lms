"""Deciding on enrolment changes proposed from Google Calendar (GoogleChangeService)."""

from __future__ import annotations

import asyncio
import random
import selectors
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.core.errors import ConflictError, NotFoundError
from backend.db.manager import DatabaseManager
from backend.models.batch import Batch
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.google_connection import GoogleChangeRequest
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.services.google_change_service import GoogleChangeService
from backend.utils.enums import CourseStatus, EnrollmentStatus, UserStatus


@pytest.fixture()
def env():
    tag = f"gcs{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="change-tests")
    world: dict = {}

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                actor = (await s.execute(select(User).where(User.username == "superadmin"))).scalar_one()
                return await fn(s, actor)
        return loop.run_until_complete(go())

    async def build(s, actor):  # noqa: ANN001, ANN202
        role = (await s.execute(select(Role).where(Role.name == "STUDENT"))).scalar_one()
        stu = User(username=f"{tag}.stu", slug=f"{tag}-stu", email=f"{tag}.stu@t.test", hashed_password="x", status=UserStatus.ACTIVE, roles=[role])
        other = User(username=f"{tag}.other", slug=f"{tag}-other", email=f"{tag}.other@t.test", hashed_password="x", status=UserStatus.ACTIVE, roles=[role])
        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([stu, other, course])
        await s.flush()
        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(), end_date=date.today() + timedelta(days=5), is_active=True, capacity=1)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        s.add(batch)
        await s.flush()
        world.update(stu=stu.id, other=other.id, batch=batch.id)

    run(build)

    def make(kind: str, user_key: str = "stu", email: str | None = None, status: str = "PENDING") -> "object":
        async def f(s, actor):  # noqa: ANN001, ANN202
            uid = world[user_key]
            req = GoogleChangeRequest(batch_id=world["batch"], kind=kind, user_id=uid, email=email or f"{tag}.{user_key}@t.test", status=status,
                                      note="test", detected_at=datetime.now(timezone.utc))
            s.add(req)
            await s.flush()
            return req.public_id
        return run(f)

    ns = type("Env", (), dict(tag=tag, run=staticmethod(run), world=world, make=staticmethod(make), loop=loop))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                await s.execute(text("DELETE FROM google_change_requests WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
                await s.execute(text("DELETE FROM notifications WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
                await s.execute(text("DELETE FROM batches WHERE batch_code LIKE :c"), p)
                await s.execute(text("DELETE FROM courses WHERE title LIKE :t"), p)
                await s.execute(text("DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM users WHERE username LIKE :u"), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _enrolments(e) -> list[tuple[int, EnrollmentStatus]]:  # noqa: ANN001
    async def f(s, actor):  # noqa: ANN001, ANN202
        rows = (await s.execute(select(Enrollments.student_id, Enrollments.status).where(Enrollments.batch_id == e.world["batch"]))).all()
        return [(r[0], r[1]) for r in rows]
    return e.run(f)


def _req(e, public_id):  # noqa: ANN001, ANN202
    async def f(s, actor):  # noqa: ANN001, ANN202
        r = (await s.execute(select(GoogleChangeRequest).where(GoogleChangeRequest.public_id == public_id))).scalar_one()
        return r.status, r.last_error, r.decided_by_user_id
    return e.run(f)


def test_approving_an_add_enrols_the_student_through_the_ordinary_rules(env) -> None:
    e = env
    rid = e.make("ENROL_ADD")

    async def approve(s, actor):  # noqa: ANN001, ANN202
        await GoogleChangeService(s).approve(rid, actor=actor)
        return actor.id

    actor_id = e.run(approve)
    assert _enrolments(e) == [(e.world["stu"], EnrollmentStatus.CONFIRMED)]
    status, error, decided_by = _req(e, rid)
    assert (status, error, decided_by) == ("APPROVED", None, actor_id)


def test_approving_a_removal_drops_the_enrolment_and_never_deletes_it(env) -> None:
    e = env

    async def enrol(s, actor):  # noqa: ANN001, ANN202
        s.add(Enrollments(batch_id=e.world["batch"], student_id=e.world["stu"], enrollment_date=datetime.now(timezone.utc), status=EnrollmentStatus.CONFIRMED))

    e.run(enrol)
    rid = e.make("ENROL_REMOVE")

    async def approve(s, actor):  # noqa: ANN001, ANN202
        await GoogleChangeService(s).approve(rid, actor=actor)

    e.run(approve)
    assert _enrolments(e) == [(e.world["stu"], EnrollmentStatus.DROPPED)]  # history kept; fees, grades and certificates hang off it
    assert _req(e, rid)[0] == "APPROVED"


def test_when_the_enrolment_rules_refuse_the_request_stays_pending_with_the_reason(env) -> None:
    e = env

    async def fill(s, actor):  # noqa: ANN001, ANN202
        s.add(Enrollments(batch_id=e.world["batch"], student_id=e.world["other"], enrollment_date=datetime.now(timezone.utc), status=EnrollmentStatus.CONFIRMED))

    e.run(fill)  # capacity is 1, and it is now full
    rid = e.make("ENROL_ADD")

    async def approve(s, actor):  # noqa: ANN001, ANN202
        await GoogleChangeService(s).approve(rid, actor=actor)

    e.run(approve)
    status, error, decided_by = _req(e, rid)
    assert status == "PENDING" and error and decided_by is None
    assert [sid for sid, _ in _enrolments(e)] == [e.world["other"]]  # the student was NOT enrolled


def test_a_refusal_leaves_nothing_half_done(env) -> None:
    e = env

    async def close(s, actor):  # noqa: ANN001, ANN202
        await s.execute(text("UPDATE batches SET is_active = false WHERE id = :b"), {"b": e.world["batch"]})

    e.run(close)
    rid = e.make("ENROL_ADD")

    async def approve(s, actor):  # noqa: ANN001, ANN202
        await GoogleChangeService(s).approve(rid, actor=actor)

    e.run(approve)
    assert _enrolments(e) == [] and _req(e, rid)[0] == "PENDING"


def test_removing_someone_who_is_not_enrolled_is_refused_with_a_reason(env) -> None:
    e = env
    rid = e.make("ENROL_REMOVE")

    async def approve(s, actor):  # noqa: ANN001, ANN202
        await GoogleChangeService(s).approve(rid, actor=actor)

    e.run(approve)
    status, error, _ = _req(e, rid)
    assert status == "PENDING" and "not enrolled" in (error or "")


def test_rejecting_records_who_decided_and_changes_no_enrolment(env) -> None:
    e = env
    rid = e.make("ENROL_ADD")

    async def reject(s, actor):  # noqa: ANN001, ANN202
        await GoogleChangeService(s).reject(rid, actor=actor)
        return actor.id

    actor_id = e.run(reject)
    assert _req(e, rid) == ("REJECTED", None, actor_id) and _enrolments(e) == []


@pytest.mark.parametrize("first", ["approve", "reject"])
@pytest.mark.parametrize("second", ["approve", "reject"])
def test_a_decided_request_cannot_be_decided_again(env, first: str, second: str) -> None:
    e = env
    rid = e.make("ENROL_ADD")

    async def decide(s, actor, which):  # noqa: ANN001, ANN202
        await getattr(GoogleChangeService(s), which)(rid, actor=actor)

    e.run(lambda s, a: decide(s, a, first))
    with pytest.raises(ConflictError):
        e.run(lambda s, a: decide(s, a, second))


def test_an_unknown_request_is_a_404(env) -> None:
    import uuid

    async def approve(s, actor):  # noqa: ANN001, ANN202
        await GoogleChangeService(s).approve(uuid.uuid4(), actor=actor)

    with pytest.raises(NotFoundError):
        env.run(approve)


def test_the_list_filters_by_status_and_shows_who_and_where(env) -> None:
    e = env
    pending = e.make("ENROL_ADD")
    e.make("ENROL_ADD", user_key="other", status="REJECTED")

    async def lst(s, actor):  # noqa: ANN001, ANN202
        svc = GoogleChangeService(s)
        return await svc.list(status="PENDING", limit=50, offset=0), await svc.pending_count()

    (items, total), count = e.run(lst)
    mine = [i for i in items if i["batch_code"] == f"{e.tag}-A"]
    assert [i["public_id"] for i in mine] == [pending] and mine[0]["student_name"] and mine[0]["kind"] == "ENROL_ADD"
    assert total >= 1 and count >= 1

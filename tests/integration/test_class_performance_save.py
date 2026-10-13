"""Saving a class-performance sheet returns rows the response can describe.

`PUT /class-performance/sessions/{id}` answered **500 on every call**. The
service flushed newly created `ClassPerformanceMark` rows and returned them;
the route's response mapper then read `row.student` to name the student, and
on a row created moments earlier that relationship had never been loaded. In
async SQLAlchemy a lazy load there is not a slow query, it is
`MissingGreenlet` -- so the mark was written and the caller got a server
error, which looks like the save failed when it had not.

Nothing caught it because the *read* path builds its rows from enrollments
and never touches `ClassPerformanceMark.student`, so every test of the sheet
passed while the write was unusable. It surfaced only by calling the endpoint.

The consequence was not confined to this screen. PRACTICAL ("Class
performance") is one of the five weighted components of the default grading
scheme, and the performance engine withholds a final percentage until every
weighted component is assessed. With class performance impossible to record,
no transcript could reach a final result, and `finalise` refuses one without
it -- so no transcript could ever be certified, and students, guardians and
corporate managers (who are shown finalised transcripts only) saw none, ever.

These tests assert the relationship is loaded on both write paths.
"""

from __future__ import annotations

import asyncio
import random
import selectors
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from backend.core.config import get_settings
from backend.db.manager import DatabaseManager
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.services.class_performance_service import ClassPerformanceService
from backend.utils.enums import CourseStatus, EnrollmentStatus, ResultState, UserStatus

STUDENTS = 2


@pytest.fixture()
def env():
    tag = f"cps{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="class-perf-tests")
    world: dict = {}
    now = datetime.now(timezone.utc)

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)

        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}
        tutor = User(
            username=f"{tag}.tutor", slug=f"{tag}-tutor", email=f"{tag}.tutor@t.test",
            hashed_password="x", status=UserStatus.ACTIVE, roles=[roles["TUTOR"]],
        )
        students = [
            User(
                username=f"{tag}.s{i}", slug=f"{tag}-s{i}", email=f"{tag}.s{i}@t.test",
                hashed_password="x", status=UserStatus.ACTIVE, roles=[roles["STUDENT"]],
            )
            for i in range(STUDENTS)
        ]
        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([tutor, *students, course])
        await s.flush()

        batch = Batch(
            batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(),
            end_date=date.today() + timedelta(days=30), is_active=True, capacity=20,
        )
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        s.add(batch)
        await s.flush()

        for student in students:
            s.add(Enrollments(batch_id=batch.id, student_id=student.id,
                              enrollment_date=now, status=EnrollmentStatus.CONFIRMED))

        session_row = BatchSession(
            batch_id=batch.id, tutor_id=tutor.id,
            session_start_time=now - timedelta(days=1),
            session_end_time=now - timedelta(days=1) + timedelta(hours=2),
        )
        s.add(session_row)
        await s.flush()

        world.update(
            tutor=tutor, students=students, session=session_row,
            session_public_id=session_row.public_id,
            student_public_ids=[st.public_id for st in students],
        )

    run(build)
    world["run"] = run
    yield world
    loop.close()


def test_saving_a_sheet_returns_rows_that_can_name_their_student(env) -> None:
    """The regression: `row.student` must be loaded, not lazy.

    Reading it is exactly what the route's response mapper does, so if this
    raises, the endpoint is a 500.
    """

    async def save(s):  # noqa: ANN001, ANN202
        service = ClassPerformanceService(s)
        tutor = (await s.execute(select(User).where(User.username == env["tutor"].username))).scalar_one()
        rows = await service.save(
            env["session_public_id"],
            [{"student_id": pid, "overall_score": Decimal("70.00")} for pid in env["student_public_ids"]],
            actor=tutor,
            max_score=Decimal("100.00"),
        )
        # The assertion is the attribute access itself.
        return [(row.public_id, row.student.username) for row in rows]

    named = env["run"](save)
    assert len(named) == STUDENTS
    for _, username in named:
        assert username, "a saved row could not name its student"


def test_publishing_a_sheet_returns_rows_that_can_name_their_student(env) -> None:
    """`set_state` feeds the same response mapper and had the same gap."""

    async def save_then_publish(s):  # noqa: ANN001, ANN202
        service = ClassPerformanceService(s)
        tutor = (await s.execute(select(User).where(User.username == env["tutor"].username))).scalar_one()
        await service.save(
            env["session_public_id"],
            [{"student_id": pid, "overall_score": Decimal("65.00")} for pid in env["student_public_ids"]],
            actor=tutor,
            max_score=Decimal("100.00"),
        )
        rows = await service.set_state(env["session_public_id"], ResultState.PUBLISHED, actor=tutor)
        return [row.student.username for row in rows]

    names = env["run"](save_then_publish)
    assert len(names) == STUDENTS
    assert all(names), "a published row could not name its student"

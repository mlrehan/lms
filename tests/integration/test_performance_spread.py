"""The §35 statistics on the performance report: spread, and trend over time.

**The average and the spread answer different questions, and must disagree.**
The average is mark-weighted over every entry, because a 1-mark quiz and a
100-mark exam are not equal halves of anyone's performance. Lowest, median
and highest are taken across *students*, each reduced to their own weighted
percentage, because they are questions about people.

The fixture below is built so the two genuinely diverge: a cohort whose
mark-weighted average sits well above its median, which is the case a single
mean hides and the reason these columns exist.
"""

from __future__ import annotations

import asyncio
import random
import selectors
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.db.manager import DatabaseManager
from backend.models.batch import Batch
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.gradebook import GradeBookEntry
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.repositories.reporting import ReportingRepository
from backend.services.scope import WorkVisibility
from backend.utils.enums import (
    CourseStatus,
    EnrollmentStatus,
    GradeComponentType,
    UserStatus,
)

UNRESTRICTED = WorkVisibility(
    unrestricted=True, taught_course_ids=frozenset(), cared_for_student_ids=frozenset()
)


@pytest.fixture()
def env():
    tag = f"ps{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="performance-spread-tests")
    world: dict = {}
    now = datetime.now(timezone.utc)

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

        def user(name: str) -> User:
            return User(
                username=f"{tag}.{name}", slug=f"{tag}-{name}", email=f"{tag}.{name}@t.test",
                hashed_password="x", status=UserStatus.ACTIVE, roles=[roles["STUDENT"]],
            )

        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add(course)
        await s.flush()

        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=60), is_active=True, capacity=20)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        s.add(batch)
        await s.flush()

        students = {name: user(name) for name in ("alpha", "beta", "gamma", "delta", "epsilon")}
        s.add_all(list(students.values()))
        await s.flush()
        for u in students.values():
            s.add(Enrollments(batch_id=batch.id, student_id=u.id,
                              enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
        await s.flush()

        def mark(student: str, score: float, out_of: float, *, months_ago: int = 0,
                 component: GradeComponentType = GradeComponentType.ASSIGNMENT) -> GradeBookEntry:
            # A partial unique index allows one *manual* entry per component,
            # so a student's two marks must be two different components.
            return GradeBookEntry(
                student_id=students[student].id, batch_id=batch.id,
                component_type=component, reference_id=None,
                score=Decimal(str(score)), max_score=Decimal(str(out_of)),
                weight=Decimal("1.000"),
                recorded_at=now - timedelta(days=31 * months_ago),
            )

        # Mark-weighted average and the median pull apart here:
        #   alpha 190/200 = 95%   beta 180/200 = 90%
        #   gamma   5/100 =  5%   delta  92/100 = 92%
        #   cohort 467/600 = 77.83% weighted, median 91%.
        # `delta`'s mark is recorded two months earlier, so the month grouping
        # has two buckets to separate -- with one bucket the trend test would
        # pass even if the grouping were by day, or ignored entirely.
        s.add_all([
            mark("alpha", 95, 100), mark("alpha", 95, 100, component=GradeComponentType.QUIZ),
            mark("beta", 90, 100), mark("beta", 90, 100, component=GradeComponentType.QUIZ),
            mark("gamma", 5, 100),
            mark("delta", 92, 100, months_ago=2),
            # A component carrying no marks at all. `epsilon` has an entry, so
            # they are not "unmarked" -- but there is nothing to be a
            # percentage *of*, and §38 is explicit that this must not become a
            # zero. Without the NULLIF guard they enter the spread at 0% and
            # drag the cohort's lowest down with a student nobody assessed.
            mark("epsilon", 0, 0),
        ])
        await s.flush()

        world.update(course_pk=course.id, batch_pk=batch.id, students=students_ids(students))

    def students_ids(students: dict) -> dict:
        return {name: u.id for name, u in students.items()}

    run(build)

    def report(group: str, **kw):  # noqa: ANN003, ANN202
        kw.setdefault("visibility", UNRESTRICTED)
        kw.setdefault("course_id", world["course_pk"])
        return run(lambda s: ReportingRepository(s).performance_by(group, **kw))

    ns = type("Env", (), dict(tag=tag, world=world, run=staticmethod(run), report=staticmethod(report)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                for stmt in (
                    "DELETE FROM gradebook_entries WHERE student_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM batches WHERE batch_code LIKE :c",
                    "DELETE FROM courses WHERE title LIKE :t",
                    "DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM users WHERE username LIKE :u",
                ):
                    await s.execute(text(stmt), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _metrics(rows: list, label: str | None = None) -> dict:
    if label is None:
        return rows[0][2]
    return next(m for _k, lbl, m in rows if lbl == label)


def test_the_spread_is_measured_across_students_not_marks(env) -> None:
    metrics = _metrics(env.report("batch"))

    # Five students have entries; only four have a percentage.
    assert metrics["students"] == 5
    assert metrics["lowest_percent"] == 5.0
    # Four students, so the median is the mean of the middle two (90 and 92).
    assert metrics["median_percent"] == 91.0
    assert metrics["highest_percent"] == 95.0


def test_the_average_is_mark_weighted_and_disagrees_with_the_median(env) -> None:
    metrics = _metrics(env.report("batch"))

    # 467 of 600 marks = 77.83%, against a median of 91%. The gap is the
    # point: it says one student is in serious trouble, which the mean alone
    # does not.
    scored, available = metrics["scored"], metrics["available"]
    assert (scored, available) == (467.0, 600.0)
    assert round(scored / available * 100, 2) == 77.83
    assert metrics["median_percent"] > round(scored / available * 100, 2)


def test_a_trend_groups_by_the_month_a_mark_was_recorded(env) -> None:
    rows = env.report("month")

    keys = [key for key, _label, _m in rows]
    assert len(keys) == 2, keys
    assert all(len(k) == 7 and k[4] == "-" for k in keys), keys

    # The three students marked this month, and `delta` alone two months
    # back. A grouping that ignored the date would collapse these into one
    # row; one that bucketed by day would produce more than two.
    by_key = {key: m for key, _label, m in rows}
    recent, older = sorted(keys)[1], sorted(keys)[0]
    assert by_key[recent]["students"] == 4
    assert by_key[older]["students"] == 1
    assert by_key[older]["median_percent"] == 92.0

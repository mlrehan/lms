"""The Maxim Dusek case, as a regression test, against a real database.

Production: a Super Admin asked "how many enrolments does Maxim Dusek have, and
who are the tutors?". The assistant joined `tutor_courses`, found nothing for
two of three batches and said "No tutor currently assigned" -- for batches
whose every class had a tutor. The fixture reproduces every shape that answer
could have gone wrong on, with one student in five batches:

* A -- classes taught by Tess, no course-level tutor (the synced-batch shape
       that produced the false "no tutor");
* B -- Tess teaches more classes than Tom; both are course-level tutors;
* C -- Tess teaches, but the course names only Tom (SOURCE_CONFLICT);
* D -- no classes scheduled yet (NOT_APPLICABLE);
* F -- one class each by Tom and Tess, Tom's first (the tie-break).

A second student called Max sits in a batch only Tom teaches, so a name lookup
that ignored scope would be ambiguous or wrong.
"""

from __future__ import annotations

import asyncio
import selectors
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from backend.ai.tools.canonical_reads import (
    handle_get_batch_overview,
    handle_get_my_tasks,
    handle_get_student_enrollments,
)
from backend.ai.tools.registry import ToolExecutionContext
from backend.ai.tools.reporting_tools import handle_get_student_enrolled_courses
from backend.core.config import get_settings
from backend.core.errors import NotFoundError, ValidationError
from backend.db.manager import DatabaseManager
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course, TutorCourse
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.services.batch_tutors import NOT_APPLICABLE, SOURCE_CONFLICT, ASSIGNED, tutors_for_batches
from backend.utils.enums import CourseStatus, EnrollmentStatus, Platforms, UserStatus


@pytest.fixture()
def env():  # noqa: ANN201
    tag = "cnr" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="ai-canonical-reads-tests")
    now = datetime.now(UTC)

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

        def person(kind: str, role: str, first: str, last: str) -> User:
            return User(username=f"{tag}.{kind}", slug=f"{tag}-{kind}", email=f"{tag}.{kind}@t.test",
                        first_name=first, last_name=last, hashed_password="x",
                        status=UserStatus.ACTIVE, roles=[roles[role]])

        p = {k: person(k, r, f, l) for k, r, f, l in (
            ("admin", "SUPER_ADMIN", "Ada", tag), ("tess", "TUTOR", "Tess", tag), ("tom", "TUTOR", "Tom", tag),
            ("max", "STUDENT", "Maxim", f"Dusek{tag}"), ("max2", "STUDENT", "Maxim", f"Other{tag}"),
        )}
        s.add_all(p.values())
        await s.flush()
        ids = {k: v.id for k, v in p.items()}

        async def batch(code: str, course_tutors: list[str], classes: list[tuple[str, int]], pupils: list[str]) -> None:
            course = Course(title=f"{tag} course {code}", code=f"{tag}-{code}", status=CourseStatus.PUBLISHED)
            course.batches, course.resources, course.tags, course.tutors = [], [], [], []
            s.add(course)
            await s.flush()
            for t in course_tutors:
                s.add(TutorCourse(tutor_id=ids[t], course_id=course.id))
            b = Batch(batch_code=f"{tag}-{code}", course_id=course.id, is_active=True, capacity=20)
            b.sessions, b.enrollments, b.student_reviews = [], [], []
            s.add(b)
            await s.flush()
            for who, days_ago in classes:
                start = now - timedelta(days=days_ago)
                s.add(BatchSession(batch_id=b.id, tutor_id=ids[who], session_start_time=start,
                                   session_end_time=start + timedelta(hours=1), duration_minutes=60, platform=Platforms.Zoom))
            for who in pupils:
                s.add(Enrollments(batch_id=b.id, student_id=ids[who], enrollment_date=now - timedelta(days=30),
                                  status=EnrollmentStatus.CONFIRMED))
            await s.flush()
            ids[f"batch{code}"] = b.id

        await batch("A", [], [("tess", 5), ("tess", 3)], ["max"])
        await batch("B", ["tess", "tom"], [("tess", 6), ("tess", 4), ("tom", 2)], ["max"])
        await batch("C", ["tom"], [("tess", 5)], ["max"])
        await batch("D", [], [], ["max"])
        await batch("F", [], [("tom", 9), ("tess", 2)], ["max"])
        await batch("G", [], [("tom", 1)], ["max2"])
        return ids

    ids = run(build)

    def call(who, fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory() as s:
                try:
                    return await fn(ToolExecutionContext(user=await s.get(User, ids[who]), session=s))
                finally:
                    await s.rollback()
        return loop.run_until_complete(go())

    try:
        yield type("Env", (), dict(tag=tag, ids=ids, call=staticmethod(call), run=staticmethod(run)))
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"u": f"{tag}.%", "c": f"{tag}-%"}
                batches = "(SELECT id FROM batches WHERE batch_code LIKE :c)"
                for sql in (
                    f"DELETE FROM enrollments WHERE batch_id IN {batches}",
                    f"DELETE FROM batch_sessions WHERE batch_id IN {batches}",
                    f"DELETE FROM batches WHERE id IN {batches}",
                    "DELETE FROM tutor_courses WHERE course_id IN (SELECT id FROM courses WHERE code LIKE :c)",
                    "DELETE FROM courses WHERE code LIKE :c",
                    "DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM users WHERE username LIKE :u",
                ):
                    async with s.begin_nested():
                        await s.execute(text(sql), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _by_batch(env, result):  # noqa: ANN001, ANN202
    return {e["batch_code"].removeprefix(f"{env.tag}-"): e for e in result["enrollments"]}


# -- the canonical rule ---------------------------------------------------------


def test_each_batch_gets_the_batches_page_tutor_and_an_honest_status(env):  # noqa: ANN001
    async def go(s):  # noqa: ANN001, ANN202
        return await tutors_for_batches(s, [env.ids[f"batch{c}"] for c in "ABCDF"])
    t = env.run(go)
    a, b, c, d, f = (t[env.ids[f"batch{x}"]] for x in "ABCDF")
    assert (a.status, a.primary_name) == (ASSIGNED, "Tess " + env.tag)   # the false "no tutor" in production
    assert (b.status, b.primary_name) == (ASSIGNED, "Tess " + env.tag)   # most classes wins
    assert c.status == SOURCE_CONFLICT and c.course_tutors == ["Tom " + env.tag]
    assert (d.status, d.primary_name, d.classes_total) == (NOT_APPLICABLE, None, 0)
    assert f.primary_name == "Tom " + env.tag                            # tie: earliest first class


def test_the_batches_page_list_and_detail_name_the_same_tutor(env):  # noqa: ANN001
    from backend.api.v1.batches import batch_response, summarise
    from backend.services.batch_service import BatchService

    async def go(s):  # noqa: ANN001, ANN202
        rows = list((await s.execute(select(Batch).where(Batch.batch_code.like(f"{env.tag}-%")))).scalars())
        listed = {r.batch_code: r.tutor_name for r in await summarise(s, rows)}
        detailed = {b.batch_code: (await batch_response(BatchService(s), b)).tutor_name for b in rows}
        return listed, detailed
    listed, detailed = env.run(go)
    assert listed == detailed
    assert listed[f"{env.tag}-F"] == "Tom " + env.tag


# -- the Maxim Dusek regression -------------------------------------------------


def test_a_super_admin_gets_every_enrolment_with_its_real_tutor(env):  # noqa: ANN001
    result = env.call("admin", lambda c: handle_get_student_enrollments({"student": f"Maxim Dusek{env.tag}"}, c))
    rows = _by_batch(env, result)
    assert sorted(rows) == ["A", "B", "C", "D", "F"] and result["completeness"]["truncated"] is False
    assert rows["A"]["tutors"]["batch_tutor"] == "Tess " + env.tag
    assert rows["A"]["tutors"]["status"] == ASSIGNED and rows["A"]["tutors"]["course_level_tutors"] == []
    assert rows["C"]["tutors"]["status"] == SOURCE_CONFLICT
    assert rows["D"]["tutors"]["status"] == NOT_APPLICABLE
    assert all(r["enrolled_on"] for r in rows.values())


def test_a_tutor_sees_only_the_batches_they_teach(env):  # noqa: ANN001
    """The leak: a tutor asking about a student in their class was handed the student's other courses."""
    tess = _by_batch(env, env.call("tess", lambda c: handle_get_student_enrollments({"student": f"Maxim Dusek{env.tag}"}, c)))
    tom = _by_batch(env, env.call("tom", lambda c: handle_get_student_enrollments({"student": f"Maxim Dusek{env.tag}"}, c)))
    assert sorted(tess) == ["A", "B", "C", "F"]
    # Course-level tutor of C, and still not shown it: only teaching a class grants sight of a cohort
    # (ScopeResolver._taught_batch_ids), which is the rule this tool must not widen.
    assert sorted(tom) == ["B", "F"]


def test_the_older_enrolled_courses_tool_is_scoped_the_same_way(env):  # noqa: ANN001
    result = env.call("tom", lambda c: handle_get_student_enrolled_courses({"student_identifier": f"Maxim Dusek{env.tag}"}, c))
    codes = sorted(r["batch_code"].removeprefix(f"{env.tag}-") for r in result["courses"])
    assert codes == ["B", "F"]


def test_a_tutor_cannot_find_a_student_by_email_and_learns_nothing_from_trying(env):  # noqa: ANN001
    """Only a holder of user.view_contact may confirm an address exists."""
    def ask(ident):  # noqa: ANN001, ANN202
        with pytest.raises(NotFoundError) as refused:
            env.call("tess", lambda c: handle_get_student_enrolled_courses({"student_identifier": ident}, c))
        return str(refused.value)
    real, fake = f"{env.tag}.max@t.test", "nobody-at-all@t.test"
    assert ask(real).replace(real, "X") == ask(fake).replace(fake, "X")
    assert env.call("admin", lambda c: handle_get_student_enrollments({"student": f"{env.tag}.max@t.test"}, c))["enrollments"]


def test_a_name_shared_by_two_students_is_asked_about_not_guessed(env):  # noqa: ANN001
    with pytest.raises(ValidationError, match="more than one"):
        env.call("admin", lambda c: handle_get_student_enrollments({"student": "Maxim"}, c))
    # For Tess only one Maxim is visible, so there is nothing to ask.
    assert env.call("tess", lambda c: handle_get_student_enrollments({"student": "Maxim"}, c))["enrollments"]


def test_a_batch_overview_counts_live_and_refuses_a_batch_you_do_not_teach(env):  # noqa: ANN001
    over = env.call("admin", lambda c: handle_get_batch_overview({"batch_code": f"{env.tag}-B"}, c))
    assert over["enrolled_active"] == 1 and over["classes"]["total"] == 3 and over["tutors"]["batch_tutor"] == "Tess " + env.tag
    with pytest.raises(NotFoundError):
        env.call("tess", lambda c: handle_get_batch_overview({"batch_code": f"{env.tag}-G"}, c))


def test_my_tasks_lists_registers_to_take_for_classes_that_happened(env):  # noqa: ANN001
    tasks = env.call("tess", handle_get_my_tasks_for)
    codes = {r["batch_code"].removeprefix(f"{env.tag}-") for r in tasks["registers_to_take"]["items"]}
    assert tasks["registers_to_take"]["total"] >= 4 and codes <= {"A", "B", "C", "F"}
    assert tasks["scope"] == "your own classes and the courses you teach"


async def handle_get_my_tasks_for(c):  # noqa: ANN001, ANN201
    return await handle_get_my_tasks({}, c)


def test_a_sql_result_that_fills_its_limit_says_it_may_be_incomplete(env):  # noqa: ANN001
    from backend.ai.config import get_ai_settings
    from backend.ai.tools.database_tools import handle_execute_database_query

    if not get_ai_settings().sql_readonly_password.get_secret_value():
        pytest.skip("AI_SQL_READONLY_PASSWORD is not set")
    full = env.call("admin", lambda c: handle_execute_database_query({"query": "SELECT id FROM roles LIMIT 2"}, c))
    assert full["completeness"] == {"limit_applied": 2, "possibly_truncated": True}
    assert "may be more" in full["message"]
    few = env.call("admin", lambda c: handle_execute_database_query({"query": "SELECT id FROM roles LIMIT 200"}, c))
    assert few["completeness"]["possibly_truncated"] is False

"""What the assistant knows when a tutor asks "what should I teach?", against a
real database.

The fixture builds a course with a published outline, a batch of three classes
taught by one tutor, and a second tutor's batch on another course. The second
class has a register taken; the first is merely scheduled. Everything is
tagged and deleted afterwards.

The course page is never fetched over the network: a fake fetcher stands in,
and a test proves it is not even constructed for a host outside the
allowlist.
"""

from __future__ import annotations

import asyncio
import selectors
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

import backend.ai.teaching_context as teaching_context
from backend.ai.security import SecurityPolicyEngine
from backend.ai.teaching_context import build_teaching_context
from backend.ai.tools.academic_tools import handle_get_course_curriculum
from backend.ai.tools.registry import ToolExecutionContext
from backend.ai.tools.teaching_tools import get_teaching_context_tool
from backend.core.config import get_settings
from backend.core.errors import AuthorizationError, NotFoundError
from backend.db.manager import DatabaseManager
from backend.models.attendance import Attendance
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.utils.enums import AttendanceStatus, CourseStatus, EnrollmentStatus, Platforms, UserStatus

OUTLINE = "- Variables and types\n- Loops\n- Functions"


@pytest.fixture()
def env():  # noqa: ANN201
    tag = "tch" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="ai-teaching-context-tests")
    now = datetime.now(UTC)

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

        def person(kind: str, role: str) -> User:
            return User(username=f"{tag}.{kind}", slug=f"{tag}-{kind}", email=f"{tag}.{kind}@t.test",
                        first_name=kind.title(), last_name="Person", hashed_password="x",
                        status=UserStatus.ACTIVE, roles=[roles[role]], timezone="Europe/London")

        people = {k: person(k, r) for k, r in (
            ("tutor", "TUTOR"), ("other", "TUTOR"), ("student", "STUDENT"), ("guardian", "GUARDIAN"),
        )}

        def course(suffix: str, **kw) -> Course:  # noqa: ANN003
            c = Course(title=f"{tag} {suffix}", code=f"{tag}-{suffix}", status=CourseStatus.PUBLISHED, **kw)
            c.batches, c.resources, c.tags, c.tutors = [], [], [], []
            return c

        python = course("python", outline=OUTLINE, overview="A first course.", description="Learn Python.")
        history = course("history", description="Dates.", course_link="https://evil.example/page")
        s.add_all([*people.values(), python, history])
        await s.flush()

        def batch(c: Course, suffix: str) -> Batch:
            b = Batch(batch_code=f"{tag}-{suffix}", course_id=c.id, is_active=True, capacity=10)
            b.sessions, b.enrollments, b.student_reviews = [], [], []
            return b

        mine, theirs = batch(python, "A"), batch(history, "B")
        s.add_all([mine, theirs])
        await s.flush()

        def session(b: Batch, tutor: User, days: int, notes: str | None = None) -> BatchSession:
            start = now + timedelta(days=days)
            return BatchSession(batch_id=b.id, tutor_id=tutor.id, session_start_time=start,
                                session_end_time=start + timedelta(minutes=90), duration_minutes=90,
                                platform=Platforms.Zoom, tutor_notes=notes)

        scheduled_only = session(mine, people["tutor"], -14)
        delivered = session(mine, people["tutor"], -7, notes="Covered variables and types.")
        upcoming = session(mine, people["tutor"], 3)
        other = session(theirs, people["other"], 2)
        s.add_all([scheduled_only, delivered, upcoming, other])
        s.add(Enrollments(batch_id=mine.id, student_id=people["student"].id,
                          enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
        await s.flush()
        s.add(Attendance(session_id=delivered.id, student_id=people["student"].id,
                         recorded_by=people["tutor"].id, status=AttendanceStatus.PRESENT))
        return {
            **{k: v.id for k, v in people.items()},
            "upcoming": upcoming.public_id, "python": python.public_id,
        }

    ids = run(build)

    async def as_user(who, fn):  # noqa: ANN001, ANN202
        async with db.session_factory() as s:
            user = await s.get(User, ids[who])
            try:
                return await fn(s, user)
            finally:
                await s.rollback()

    ns = type("Env", (), dict(
        tag=tag, ids=ids,
        call=staticmethod(lambda who, fn: loop.run_until_complete(as_user(who, fn))),
        run=staticmethod(run),
    ))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"u": f"{tag}.%", "c": f"{tag}-%"}
                batches = "(SELECT id FROM batches WHERE batch_code LIKE :c)"
                for sql in (
                    f"DELETE FROM attendances WHERE session_id IN (SELECT id FROM batch_sessions WHERE batch_id IN {batches})",
                    f"DELETE FROM enrollments WHERE batch_id IN {batches}",
                    f"DELETE FROM batch_sessions WHERE batch_id IN {batches}",
                    "DELETE FROM batches WHERE batch_code LIKE :c",
                    "DELETE FROM courses WHERE code LIKE :c",
                    "DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM users WHERE username LIKE :u",
                ):
                    await s.execute(text(sql), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _context(env, who, **kw):  # noqa: ANN001, ANN003, ANN202
    return env.call(who, lambda s, u: build_teaching_context(s, u, **kw))


def test_the_tutors_next_class_is_found_with_its_outline_and_position(env):  # noqa: ANN001
    ctx = _context(env, "tutor", batch_code=f"{env.tag}-A")
    assert ctx["found"] is True
    assert ctx["class"]["session_id"] == str(env.ids["upcoming"])
    assert ctx["class"]["session_number"] == 3
    assert ctx["class"]["sessions_in_batch"] == 3
    assert ctx["class"]["duration_minutes"] == 90
    assert ctx["class"]["students_enrolled"] == 1
    assert ctx["official_outline"] == OUTLINE
    assert ctx["sources"]["official_outline"] == "verified_lms"
    assert ctx["lesson_basis"] == "official_outline"
    assert "class 3 of 3" in ctx["scope_note"]


def test_a_scheduled_class_is_not_reported_as_taught(env):  # noqa: ANN001
    previous = _context(env, "tutor", batch_code=f"{env.tag}-A")["previous_classes_in_batch"]
    assert [p["evidence"] for p in previous] == ["unrecorded", "verified_lms"]
    assert previous[0]["tutor_notes"] is None and previous[0]["attendance_records"] == 0
    assert previous[1]["tutor_notes"] == "Covered variables and types."
    assert previous[1]["attendance_records"] == 1


def test_another_tutors_batch_answers_exactly_like_a_missing_one(env):  # noqa: ANN001
    with pytest.raises(NotFoundError) as theirs:
        _context(env, "tutor", batch_code=f"{env.tag}-B")
    with pytest.raises(NotFoundError) as missing:
        _context(env, "tutor", batch_code=f"{env.tag}-ZZZ")
    assert theirs.value.message == missing.value.message


def test_a_session_of_another_tutor_cannot_be_named_directly(env):  # noqa: ANN001
    async def other_session(s):  # noqa: ANN001, ANN202
        return (await s.execute(
            select(BatchSession.public_id).join(Batch).where(Batch.batch_code == f"{env.tag}-B")
        )).scalar_one()
    sid = env.run(other_session)
    with pytest.raises(NotFoundError):
        _context(env, "tutor", session_id=str(sid))


def test_a_course_page_off_the_allowlist_is_never_fetched(env, monkeypatch):  # noqa: ANN001
    import backend.integrations.lait_pages as lait_pages

    # Recorded rather than raised: the fallback deliberately swallows any
    # fetch failure, so an exception here would be caught and the test could
    # never fail.
    constructed = []

    class Recording:
        def __init__(self, *a, **k):  # noqa: ANN002, ANN003
            constructed.append(a)

        async def __aenter__(self):  # noqa: ANN204
            return self

        async def __aexit__(self, *exc):  # noqa: ANN002, ANN204
            return None

        async def fetch(self, url):  # noqa: ANN001, ANN201
            return None

    monkeypatch.setattr(lait_pages, "PageFetcher", Recording)
    teaching_context._page_cache.clear()
    ctx = _context(env, "other")  # their history course links to evil.example
    assert constructed == []
    assert ctx["found"] is True
    assert ctx["official_outline"] is None
    assert ctx["sources"]["official_outline"] == "missing"
    assert ctx["lesson_basis"] == "course_description"


def test_an_unsynced_outline_is_read_from_the_institutions_course_page(env, monkeypatch):  # noqa: ANN001
    import backend.integrations.lait_pages as lait_pages

    async def relink(s):  # noqa: ANN001, ANN202
        course = (await s.execute(select(Course).where(Course.code == f"{env.tag}-history"))).scalar_one()
        course.course_link = f"https://www.londonacademyofit.co.uk/training-course/{env.tag}"
    env.run(relink)

    fetched = []

    class FakeFetcher:
        def __init__(self, hosts, **kw):  # noqa: ANN001, ANN003
            self.hosts = hosts

        async def __aenter__(self):  # noqa: ANN204
            return self

        async def __aexit__(self, *exc):  # noqa: ANN002, ANN204
            return None

        async def fetch(self, url):  # noqa: ANN001, ANN201
            fetched.append(url)
            return ('<span id="MainContent_lblCourseOutlineHTML"><ul><li>The Tudors</li><li>The Stuarts</li></ul></span>'
                    '<span id="MainContent_lblCourseOverview"><p>British history.</p></span>')

    monkeypatch.setattr(lait_pages, "PageFetcher", FakeFetcher)
    teaching_context._page_cache.clear()
    ctx = _context(env, "other")
    assert len(fetched) == 1
    assert "The Tudors" in ctx["official_outline"] and "The Stuarts" in ctx["official_outline"]
    assert ctx["sources"]["official_outline"] == "verified_course_page"
    assert ctx["course"]["overview"] == "British history."
    # Cached: a second question does not fetch the page again.
    _context(env, "other")
    assert len(fetched) == 1


@pytest.mark.parametrize("who", ["student", "guardian"])
def test_the_tool_is_refused_to_people_who_do_not_teach(env, who):  # noqa: ANN001
    async def check(s, user):  # noqa: ANN001, ANN202
        SecurityPolicyEngine.authorize_tool_invocation(tool_policy=get_teaching_context_tool.policy, user=user)
    with pytest.raises(AuthorizationError):
        env.call(who, check)
    env.call("tutor", check)  # and allowed to the tutor


def test_the_curriculum_tool_returns_the_outline_instead_of_crashing(env):  # noqa: ANN001
    async def ask(s, user):  # noqa: ANN001, ANN202
        return await handle_get_course_curriculum(
            {"course_identifier": f"{env.tag}-python"}, ToolExecutionContext(user=user, session=s)
        )
    result = env.call("tutor", ask)
    assert result["official_outline"] == OUTLINE
    assert result["sources"]["official_outline"] == "verified_lms"


def test_the_curriculum_tool_hides_a_draft_course_from_tutors_not_assigned_to_it(env):  # noqa: ANN001
    async def draft(s):  # noqa: ANN001, ANN202
        course = (await s.execute(select(Course).where(Course.code == f"{env.tag}-python"))).scalar_one()
        course.status = CourseStatus.DRAFT
    env.run(draft)

    async def ask(s, user):  # noqa: ANN001, ANN202
        return await handle_get_course_curriculum(
            {"course_identifier": f"{env.tag}-python"}, ToolExecutionContext(user=user, session=s)
        )
    with pytest.raises(NotFoundError):
        env.call("other", ask)

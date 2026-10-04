"""Assessment deadlines in the calendar feed (spec §26), and who may read them.

The feed is a **capability URL**: calendar clients cannot send an
`Authorization` header, so the token sits in the link and anyone holding the
link is the audience. That makes the scoping here the whole test. Session
events were already confined to "batches I teach or am enrolled in"; putting
assessments beside them is only safe if they are confined the same way, and
the failure mode is silent -- a student's calendar quietly listing another
cohort's exam looks like a populated calendar, not like a leak.

So each test below pairs a positive with a negative. Asserting only that
*my* assignment appears would pass just as well if the query returned every
assignment in the institution.
"""

from __future__ import annotations

import asyncio
import random
import selectors
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from backend.api.v1.integrations import _assessment_events
from backend.core.config import get_settings
from backend.db.manager import DatabaseManager
from backend.models.assignment import Assignment
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.exam import Exam
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.quiz import Quiz
from backend.utils.enums import (
    AssessmentScope,
    AssessmentState,
    CourseStatus,
    EnrollmentStatus,
    ExamType,
    Platforms,
    SubmissionType,
    UserStatus,
)


@pytest.fixture()
def env():
    tag = f"cf{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="calendar-feed-tests")
    world: dict = {}
    t0 = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(days=3)

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

        def user(name: str, role: str) -> User:
            return User(
                username=f"{tag}.{name}", slug=f"{tag}-{name}", email=f"{tag}.{name}@t.test",
                hashed_password="x", status=UserStatus.ACTIVE, roles=[roles[role]],
            )

        tutor, stu_a, stu_b = user("tutor", "TUTOR"), user("stua", "STUDENT"), user("stub", "STUDENT")
        outsider = user("outsider", "STUDENT")
        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        other = Course(title=f"{tag} Other", code=f"{tag}o", status=CourseStatus.PUBLISHED)
        other.batches, other.resources, other.tags, other.tutors = [], [], [], []
        s.add_all([tutor, stu_a, stu_b, outsider, course, other])
        await s.flush()

        batches = []
        for code, course_row in ((f"{tag}-A", course), (f"{tag}-B", course), (f"{tag}-C", other)):
            b = Batch(batch_code=code, course_id=course_row.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=60), is_active=True, capacity=10)
            b.sessions, b.enrollments, b.student_reviews = [], [], []
            s.add(b)
            batches.append(b)
        await s.flush()

        lesson = BatchSession(batch_id=batches[0].id, tutor_id=tutor.id,
                              session_start_time=t0, session_end_time=None,
                              duration_minutes=90, platform=Platforms.Zoom)
        lesson.attendances = []
        s.add(lesson)

        for batch, student in ((batches[0], stu_a), (batches[1], stu_b), (batches[2], outsider)):
            s.add(Enrollments(batch_id=batch.id, student_id=student.id,
                              enrollment_date=datetime.now(timezone.utc),
                              status=EnrollmentStatus.CONFIRMED))
        await s.flush()

        def assignment(title, *, scope, state, due_days, batch=None, course_row=None):  # noqa: ANN001, ANN202
            return Assignment(
                course_id=(course_row or course).id,
                batch_id=batch.id if batch is not None else None,
                session_id=None,
                scope=scope,
                state=state,
                title=title,
                due_date=t0 + timedelta(days=due_days),
                max_score=Decimal("100.00"),
                submission_type=SubmissionType.TEXT,
                weight=Decimal("1.00"),
            )

        s.add_all([
            assignment("Mine", scope=AssessmentScope.BATCH, batch=batches[0],
                       state=AssessmentState.PUBLISHED, due_days=2),
            assignment("Theirs", scope=AssessmentScope.BATCH, batch=batches[1],
                       state=AssessmentState.PUBLISHED, due_days=2),
            assignment("Draft", scope=AssessmentScope.BATCH, batch=batches[0],
                       state=AssessmentState.DRAFT, due_days=2),
            assignment("Course wide", scope=AssessmentScope.COURSE,
                       state=AssessmentState.PUBLISHED, due_days=3),
            assignment("Elsewhere", scope=AssessmentScope.COURSE, course_row=other,
                       state=AssessmentState.PUBLISHED, due_days=3),
        ])

        def quiz(title, *, batch, published, until=None):  # noqa: ANN001, ANN202
            return Quiz(course_id=course.id, batch_id=batch.id, scope=AssessmentScope.BATCH,
                        title=title, passing_score=Decimal("50.00"), is_published=published,
                        available_from=t0 + timedelta(days=4), available_until=until,
                        weight=Decimal("1.00"))

        s.add_all([
            quiz("My quiz", batch=batches[0], published=True, until=t0 + timedelta(days=5)),
            quiz("Their quiz", batch=batches[1], published=True),
            quiz("Unpublished quiz", batch=batches[0], published=False),
        ])

        def exam(title, *, published, days, minutes=120, venue=None):  # noqa: ANN001, ANN202
            return Exam(course_id=course.id, batch_id=batches[0].id, scope=AssessmentScope.BATCH,
                        exam_type=ExamType.MIDTERM, title=title,
                        scheduled_at=t0 + timedelta(days=days), duration_minutes=minutes,
                        total_marks=Decimal("100.00"), passing_marks=Decimal("40.00"),
                        is_published=published, is_online=False, venue_or_link=venue,
                        # Real text, deliberately: without it the assertion
                        # that no free text reaches the feed passes whatever
                        # the code does, because there is nothing to leak.
                        instructions="Closed book. Bring photographic ID.",
                        weight=Decimal("1.00"))

        for row in (exam("My exam", published=True, days=6, venue="Room 2"),
                    exam("Unpublished exam", published=False, days=7)):
            row.invigilators = []
            row.results = []
            s.add(row)
        await s.flush()

        world.update(stu_a=stu_a.id, stu_b=stu_b.id, outsider=outsider.id, tutor=tutor.id)

    run(build)

    def events_for(user_id: int, *, days: int = 90) -> list[dict]:
        now = datetime.now(timezone.utc)
        return run(lambda s: _assessment_events(
            s, user_id=user_id,
            window_start=now - timedelta(days=1),
            window_end=now + timedelta(days=days),
        ))

    ns = type("Env", (), dict(
        tag=tag, world=world, run=staticmethod(run), events_for=staticmethod(events_for),
    ))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                for stmt in (
                    "DELETE FROM exams WHERE course_id IN (SELECT id FROM courses WHERE title LIKE :t)",
                    "DELETE FROM quizzes WHERE course_id IN (SELECT id FROM courses WHERE title LIKE :t)",
                    "DELETE FROM assignments WHERE course_id IN (SELECT id FROM courses WHERE title LIKE :t)",
                    "DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
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


def _summaries(events: list[dict]) -> set[str]:
    return {e["summary"] for e in events}


def test_a_student_sees_their_own_batch_and_course_work_only(env) -> None:
    summaries = _summaries(env.events_for(env.world["stu_a"]))

    assert "Assignment due: Mine" in summaries
    assert "Assignment due: Course wide" in summaries
    # The negative is the point: batch B belongs to the same course, so
    # matching on "whichever id is populated" rather than on `scope` would
    # hand this student work set for a cohort they are not in.
    assert "Assignment due: Theirs" not in summaries
    assert "Assignment due: Elsewhere" not in summaries


def test_unpublished_work_never_reaches_the_feed(env) -> None:
    summaries = _summaries(env.events_for(env.world["stu_a"]))

    # A feed is cached by software the institution does not control and often
    # mirrored to a phone, so a draft leaking here travels further than one
    # leaking on a screen -- and cannot be withdrawn.
    assert "Assignment due: Draft" not in summaries
    assert "Quiz opens: Unpublished quiz" not in summaries
    assert "Exam: Unpublished exam" not in summaries
    assert "Quiz opens: My quiz" in summaries
    assert "Exam: My exam" in summaries


def test_a_student_in_another_course_sees_only_that_course(env) -> None:
    """The same rule read from the other side.

    This student is enrolled in a batch of the *other* course, so the one
    course-wide assignment set there is genuinely theirs -- and nothing from
    the first course is. Asserting an empty set here would have been wrong,
    and weaker: an exact set proves the boundary holds in both directions
    rather than that one person happens to see nothing.
    """
    assert _summaries(env.events_for(env.world["outsider"])) == {"Assignment due: Elsewhere"}


def test_a_tutor_sees_the_work_of_the_batch_they_teach(env) -> None:
    # The tutor is enrolled in nothing; their membership comes entirely from
    # teaching a session of batch A.
    summaries = _summaries(env.events_for(env.world["tutor"]))

    assert "Assignment due: Mine" in summaries
    assert "Assignment due: Theirs" not in summaries


def test_an_exam_carries_its_duration_and_venue_but_no_free_text(env) -> None:
    exam = next(e for e in env.events_for(env.world["stu_a"]) if e["summary"] == "Exam: My exam")

    assert (exam["end"] - exam["start"]) == timedelta(minutes=120)
    assert exam["location"] == "Room 2"
    # The link is the credential, so nothing that reads as content travels in
    # it; the detail lives behind `url`, which still asks who you are. The
    # seeded exam does carry instructions, so this fails if they are ever
    # piped through.
    assert exam["description"] is None


def test_the_window_is_honoured(env) -> None:
    # Everything seeded sits more than a day out.
    assert env.events_for(env.world["stu_a"], days=1) == []

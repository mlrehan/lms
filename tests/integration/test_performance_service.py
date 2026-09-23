"""The engine, wired to real marks.

`tests/unit/test_performance_engine.py` proves the arithmetic. This proves the
*gathering*: that a student's assignments, examinations, attendance and class
marks reach it from the tables that own them, weighted by a real scheme, and
that who is asking changes what is counted.

Three things are worth stating about what is being tested here, because each is
a way the whole feature could look right and be wrong:

* **The weight has to come from the scheme.** Before this phase the grade book
  wrote `weight = 1` on every row, so a "weighted average" was a straight
  average. A test that only checked the number was non-null would have passed.
* **A guardian must not see unreleased marking.** §14. The same student, the
  same marks, a different reader, a different answer.
* **Attendance is read from the register, never stored.** §12. Correcting a
  register has to change the result, which it cannot do if a copy was taken.
"""

from __future__ import annotations

import asyncio
import selectors
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.core.errors import NotFoundError
from backend.db.manager import DatabaseManager
from backend.models.assignment import Assignment, AssignmentSubmission
from backend.models.attendance import Attendance
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course, TutorCourse
from backend.models.enrollment import Enrollments
from backend.models.exam import Exam, ExamResult
from backend.models.gradebook import GradeBand
from backend.models.grading import GradingScheme, GradingSchemeComponent
from backend.models.guardian import StudentGuardian
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.services.performance_service import PerformanceService
from backend.utils.enums import (
    AssessmentScope,
    AttendanceStatus,
    CourseStatus,
    EnrollmentStatus,
    ExamType,
    GradeComponentType as C,
    Platforms,
    SubmissionState as St,
    SubmissionType,
    UserStatus,
)

D = Decimal


@pytest.fixture()
def env():
    tag = "pf" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="performance-tests")

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

        def user(kind: str, role: str) -> User:
            return User(username=f"{tag}.{kind}", slug=f"{tag}-{kind}",
                        email=f"{tag}.{kind}@t.test", hashed_password="x",
                        status=UserStatus.ACTIVE, roles=[roles[role]])

        tutor = user("tutor", "TUTOR")
        alice = user("alice", "STUDENT")
        parent = user("parent", "GUARDIAN")

        # A scheme with the spec's own example weighting, so the arithmetic
        # below can be checked by hand against §37.
        scheme = GradingScheme(name=f"{tag} scheme", created_at=datetime.now(UTC),
                               is_default=False, is_active=True)
        scheme.components = [
            GradingSchemeComponent(component_type=C.ASSIGNMENT, weight_percentage=D("40")),
            GradingSchemeComponent(component_type=C.FINAL_EXAM, weight_percentage=D("40")),
            GradingSchemeComponent(component_type=C.ATTENDANCE, weight_percentage=D("20")),
        ]
        scheme.bands = [
            GradeBand(min_score=D("70"), max_score=D("100"), letter_grade=f"{tag[:2]}A",
                      gpa_points=D("4"), is_pass=True),
            GradeBand(min_score=D("0"), max_score=D("69.99"), letter_grade=f"{tag[:2]}F",
                      gpa_points=D("0"), is_pass=False),
        ]
        s.add_all([tutor, alice, parent, scheme])
        await s.flush()

        course = Course(title=f"{tag} course", code=f"{tag}-C",
                        status=CourseStatus.PUBLISHED, grading_scheme_id=scheme.id)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add(course)
        await s.flush()
        s.add(TutorCourse(tutor_id=tutor.id, course_id=course.id))
        s.add(StudentGuardian(guardian_id=parent.id, student_id=alice.id,
                              relationship_type="Parent", is_primary=True,
                              created_at=datetime.now(UTC)))

        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=60), is_active=True, capacity=20)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        s.add(batch)
        await s.flush()
        s.add(Enrollments(batch_id=batch.id, student_id=alice.id,
                          enrollment_date=datetime.now(UTC),
                          status=EnrollmentStatus.CONFIRMED))

        now = datetime.now(UTC)
        # Four sessions; Alice attends three -> 75% attendance.
        sessions = []
        for i in range(4):
            row = BatchSession(batch_id=batch.id, tutor_id=tutor.id,
                               session_start_time=now - timedelta(days=10 - i),
                               session_end_time=now - timedelta(days=10 - i) + timedelta(hours=2),
                               duration_minutes=120, platform=Platforms.Zoom)
            row.attendances = []
            sessions.append(row)
        s.add_all(sessions)
        await s.flush()
        for row in sessions[:3]:
            s.add(Attendance(session_id=row.id, student_id=alice.id, recorded_by=tutor.id,
                             status=AttendanceStatus.PRESENT, recorded_at=now))
        # An explicit ABSENT row for the fourth, and it is not decoration: with
        # only PRESENT rows in the fixture, deleting the status filter entirely
        # changes no count, so every attendance assertion below passed whether
        # or not the filter existed. A register that records absences is also
        # what a real one looks like.
        s.add(Attendance(session_id=sessions[3].id, student_id=alice.id, recorded_by=tutor.id,
                         status=AttendanceStatus.ABSENT, recorded_at=now))

        # Assignment: 80/100, published.
        assignment = Assignment(course_id=course.id, scope=AssessmentScope.COURSE,
                                title=f"{tag} Essay", due_date=now - timedelta(days=5),
                                max_score=D("100"), submission_type=SubmissionType.TEXT,
                                allow_late_submissions=False)
        assignment.submissions = []
        s.add(assignment)
        await s.flush()
        s.add(AssignmentSubmission(assignment_id=assignment.id, student_id=alice.id,
                                   submitted_at=now - timedelta(days=6), content="x",
                                   grade=D("80"), raw_grade=D("80"),
                                   state=St.PUBLISHED, graded_by_id=tutor.id, graded_at=now))

        # Examination: 60/100, NOT published -- the mark a guardian must not see.
        exam = Exam(course_id=course.id, batch_id=batch.id, scope=AssessmentScope.BATCH,
                    exam_type=ExamType.FINAL, title=f"{tag} Final",
                    scheduled_at=now - timedelta(days=2), total_marks=D("100"),
                    passing_marks=D("40"), is_published=True)
        exam.invigilators, exam.results = [], []
        s.add(exam)
        await s.flush()
        s.add(ExamResult(exam_id=exam.id, student_id=alice.id, marks_obtained=D("60"),
                         is_published=False, state=St.GRADED))
        await s.flush()

        return {"tutor": tutor, "alice": alice, "parent": parent, "course": course,
                "batch": batch, "exam": exam, "scheme": scheme}

    ns = type("Env", (), dict(tag=tag, run=staticmethod(run), build=staticmethod(build)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"u": f"{tag}.%", "c": f"{tag}-%", "t": f"{tag}%"}
                b = "(SELECT id FROM batches WHERE batch_code LIKE :c)"
                a = "(SELECT id FROM assignments WHERE title LIKE :t)"
                e = "(SELECT id FROM exams WHERE title LIKE :t)"
                await s.execute(text(f"DELETE FROM assignment_submissions WHERE assignment_id IN {a}"), p)
                await s.execute(text("DELETE FROM assignments WHERE title LIKE :t"), p)
                await s.execute(text(f"DELETE FROM exam_results WHERE exam_id IN {e}"), p)
                await s.execute(text("DELETE FROM exams WHERE title LIKE :t"), p)
                await s.execute(text(f"DELETE FROM attendances WHERE session_id IN (SELECT id FROM batch_sessions WHERE batch_id IN {b})"), p)
                await s.execute(text(f"DELETE FROM batch_sessions WHERE batch_id IN {b}"), p)
                await s.execute(text(f"DELETE FROM enrollments WHERE batch_id IN {b}"), p)
                await s.execute(text("DELETE FROM batches WHERE batch_code LIKE :c"), p)
                await s.execute(text("DELETE FROM student_guardians WHERE guardian_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM tutor_courses WHERE course_id IN (SELECT id FROM courses WHERE code LIKE :c)"), p)
                await s.execute(text("UPDATE courses SET grading_scheme_id = NULL WHERE code LIKE :c"), p)
                await s.execute(text("DELETE FROM courses WHERE code LIKE :c"), p)
                await s.execute(text("DELETE FROM grade_bands WHERE scheme_id IN (SELECT id FROM grading_schemes WHERE name LIKE :t)"), p)
                await s.execute(text("DELETE FROM grading_scheme_components WHERE scheme_id IN (SELECT id FROM grading_schemes WHERE name LIKE :t)"), p)
                await s.execute(text("DELETE FROM grading_schemes WHERE name LIKE :t"), p)
                await s.execute(text("DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM users WHERE username LIKE :u"), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _perf(env, who: str):
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            return await PerformanceService(s).for_student(
                student_id=made["alice"].id, batch_id=made["batch"].id, actor=made[who]
            )
        return go()
    return env.run(f)


# --------------------------------------------------- the weighted result ---


def test_a_tutor_sees_every_component_weighted_by_the_scheme(env) -> None:
    """Assignment 80x40% = 32, Exam 60x40% = 24, Attendance 75x20% = 15 -> 71.

    The arithmetic is checkable by hand on purpose. Before this phase every
    entry carried `weight = 1`, so this would have come out as the straight
    mean of 80, 60 and 75 -- 71.67, close enough to look right and wrong.
    """
    result = _perf(env, "tutor")
    lines = {c.component_type: c for c in result.performance.components}

    assert lines[C.ASSIGNMENT].contribution == D("32.00")
    assert lines[C.FINAL_EXAM].contribution == D("24.00")
    assert lines[C.ATTENDANCE].contribution == D("15.00")
    assert result.performance.final_percentage == D("71.00")
    assert result.performance.is_pass is True


def test_the_breakdown_explains_the_headline(env) -> None:
    """§37. If the lines and the total disagree, one is lying and nobody can
    tell which."""
    result = _perf(env, "tutor")
    total = sum(c.contribution for c in result.performance.components if c.contribution)
    assert total == result.performance.final_percentage


def test_the_scheme_that_applies_is_the_courses_own(env) -> None:
    """§13's override. Without it every course would be graded on the
    institution default, and the override column would be decorative."""
    assert _perf(env, "tutor").scheme_name == f"{env.tag} scheme"


# ------------------------------------------------ who sees unreleased work ---


def test_a_guardian_does_not_see_an_unreleased_examination_mark(env) -> None:
    """§14. Same student, same marks, different reader, different answer.

    The examination is graded but not published, so for the guardian it is not
    yet assessed -- and the total is out of the 60% that has been, not
    silently including a mark the family has not been given.
    """
    result = _perf(env, "parent")
    exam = next(c for c in result.performance.components if c.component_type is C.FINAL_EXAM)

    assert exam.counted is False
    assert exam.percentage is None
    assert result.performance.assessed_weight == D("60.00")
    # 32 + 15 = 47 out of the 60 assessed -> 78.33%
    assert result.performance.current_percentage == D("78.33")
    # And no final mark, because 40% of the scheme is still unassessed for them.
    assert result.performance.final_percentage is None


def test_the_tutor_and_the_guardian_genuinely_differ(env) -> None:
    """Guards against both paths quietly returning the same thing, which would
    make the test above pass for the wrong reason.

    Both readers are evaluated against **one** world. Calling the fixture's
    builder twice would create the scheme twice and violate its unique name --
    and, worse, would compare two different worlds while appearing to compare
    two readers.
    """
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = PerformanceService(s)
            tutor = await svc.for_student(
                student_id=made["alice"].id, batch_id=made["batch"].id, actor=made["tutor"])
            parent = await svc.for_student(
                student_id=made["alice"].id, batch_id=made["batch"].id, actor=made["parent"])
            return tutor.performance.final_percentage, parent.performance.final_percentage
        return go()

    tutor_final, parent_final = env.run(f)
    assert tutor_final == D("71.00")
    assert parent_final is None


# ------------------------------------------------------------- attendance ---


def test_attendance_is_read_from_the_register(env) -> None:
    """§12: the register is the single source of truth, never copied. Three of
    four sessions attended is 75%, and correcting the register would change
    this figure -- which a stored copy could not do."""
    result = _perf(env, "tutor")
    assert result.sessions_total == 4
    assert result.sessions_attended == 3
    assert result.attendance_percentage == D("75")
    attendance = next(
        c for c in result.performance.components if c.component_type is C.ATTENDANCE
    )
    assert attendance.percentage == D("75.00")


# ---------------------------------------------------------- authorisation ---


def test_a_stranger_cannot_read_a_students_performance(env) -> None:
    """§32: grade book data must not be reachable by manipulating ids -- and
    404, not 403, so the id is not confirmed to exist either."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}
            stranger = User(username=f"{env.tag}.stranger", slug=f"{env.tag}-stranger",
                            email=f"{env.tag}.stranger@t.test", hashed_password="x",
                            status=UserStatus.ACTIVE, roles=[roles["STUDENT"]])
            s.add(stranger)
            await s.flush()
            with pytest.raises(NotFoundError):
                await PerformanceService(s).for_student(
                    student_id=made["alice"].id, batch_id=made["batch"].id, actor=stranger
                )
            return True
        return go()

    assert env.run(f)


def test_a_student_may_read_their_own(env) -> None:
    """The counterpart: without it the refusal above could be passing because
    nobody can read anything."""
    result = _perf(env, "alice")
    assert result.student_id is not None
    # A student is not staff, so the unreleased examination is excluded for
    # them too -- the same rule as the guardian, applied to themselves.
    assert result.performance.final_percentage is None

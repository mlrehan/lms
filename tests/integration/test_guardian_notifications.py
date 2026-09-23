"""A guardian is told about their ward's progress.

Before this, guardians received nothing at all -- not one notification row existed for any guardian in the
database, because every emitter addressed only the student. The whole point of the role is oversight, so the
gap was the feature missing rather than a bug in it.

Driven against real Postgres: the defect was in resolving `student_guardians`, and a fake link table would
only assert that the code called the fake.
"""

from __future__ import annotations

import asyncio
import selectors
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.core.notification_types import NotificationType
from backend.db.manager import DatabaseManager
from backend.models.assignment import Assignment, AssignmentSubmission
from backend.models.course import Course, TutorCourse
from backend.models.guardian import StudentGuardian
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.notification import Notification, NotificationPreference
from backend.schemas.assignment import GradeSubmissionRequest
from backend.services.assignment_service import AssignmentService
from backend.utils.enums import CourseStatus, SubmissionType, UserStatus


@pytest.fixture()
def env():
    tag = "gn" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="guardian-notification-tests")

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        """A tutor with a course, a student on it, and that student's guardian."""
        roles = {
            n: (await s.execute(select(Role).where(Role.name == n))).scalar_one()
            for n in ("TUTOR", "STUDENT", "GUARDIAN")
        }

        def user(kind: str, role: str, first: str, last: str) -> User:
            return User(
                username=f"{tag}.{kind}", slug=f"{tag}-{kind}", email=f"{tag}.{kind}@t.test",
                first_name=first, last_name=last, hashed_password="x",
                status=UserStatus.ACTIVE, roles=[roles[role]],
            )

        tutor = user("tutor", "TUTOR", "Tess", "Tutor")
        student = user("student", "STUDENT", "Sam", "Student")
        guardian = user("guardian", "GUARDIAN", "Gwen", "Guardian")
        course = Course(title=f"{tag} course", code=f"{tag}-C", status=CourseStatus.PUBLISHED)
        s.add_all([tutor, student, guardian, course])
        await s.flush()

        s.add_all([
            TutorCourse(tutor_id=tutor.id, course_id=course.id),
            StudentGuardian(guardian_id=guardian.id, student_id=student.id, relationship_type="Parent"),
        ])
        assignment = Assignment(
            course_id=course.id, title=f"{tag} homework",
            due_date=datetime.now(UTC) + timedelta(days=7),
            max_score=100, submission_type=SubmissionType.TEXT,
        )
        s.add(assignment)
        await s.flush()
        submission = AssignmentSubmission(
            assignment_id=assignment.id, student_id=student.id,
            submitted_at=datetime.now(UTC), content="my work",
        )
        s.add(submission)
        await s.flush()
        return dict(tutor=tutor, student=student, guardian=guardian, course=course,
                    assignment=assignment, submission=submission)

    async def rows_for(s, user_id: int):  # noqa: ANN001, ANN202
        return (await s.execute(
            select(Notification).where(Notification.user_id == user_id)
        )).scalars().all()

    ns = type("Env", (), dict(tag=tag, run=staticmethod(run), build=staticmethod(build),
                              rows_for=staticmethod(rows_for)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                users = "(SELECT id FROM users WHERE username LIKE :u)"
                p = {"u": f"{tag}.%", "c": f"{tag}-%"}
                await s.execute(text(f"DELETE FROM notifications WHERE user_id IN {users}"), p)
                await s.execute(text(f"DELETE FROM notification_preferences WHERE user_id IN {users}"), p)
                await s.execute(text(f"DELETE FROM student_guardians WHERE guardian_id IN {users} OR student_id IN {users}"), p)
                courses = "(SELECT id FROM courses WHERE code LIKE :c)"
                await s.execute(text(f"DELETE FROM assignment_submissions WHERE assignment_id IN (SELECT id FROM assignments WHERE course_id IN {courses})"), p)
                await s.execute(text(f"DELETE FROM assignments WHERE course_id IN {courses}"), p)
                await s.execute(text(f"DELETE FROM tutor_courses WHERE course_id IN {courses}"), p)
                await s.execute(text("DELETE FROM courses WHERE code LIKE :c"), p)
                await s.execute(text("DELETE FROM users WHERE username LIKE :u"), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


async def _grade(s, made):  # noqa: ANN001, ANN202
    """Mark the work **and release it**.

    Grading alone used to notify. It no longer does: spec §14 separates
    recording a mark from releasing it, and a guardian must not be told about
    a result the family has not been given. Publishing is now what announces,
    so these tests -- which are about the *content* of a guardian's
    notification and their ability to switch it off -- do both.

    `test_grading_alone_tells_nobody` below covers the new timing directly,
    rather than leaving it as an invisible side effect of this helper.
    """
    service = AssignmentService(s)
    await service.grade(
        made["submission"].public_id,
        GradeSubmissionRequest(grade=72, feedback="good"),
        actor=made["tutor"],
    )
    await s.flush()
    return await service.publish_results(made["assignment"].public_id, actor=made["tutor"])


def test_a_guardian_is_told_when_their_ward_is_graded(env) -> None:
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            await _grade(s, made)
            await s.flush()
            return (
                await env.rows_for(s, made["guardian"].id),
                await env.rows_for(s, made["student"].id),
            )
        return go()

    guardian_rows, student_rows = env.run(f)
    assert [r.type for r in guardian_rows] == [NotificationType.WARD_SUBMISSION_GRADED]
    # The student's own notification is untouched and still second person.
    assert [r.type for r in student_rows] == [NotificationType.SUBMISSION_GRADED]
    assert "You scored" in student_rows[0].body


def test_grading_alone_tells_nobody(env) -> None:
    """§14: recording a mark and releasing it are separate acts.

    A tutor marking thirty scripts over a week must not be telling thirty
    families one at a time as they go. This is the property that changed the
    helper above, so it gets a test of its own rather than being an invisible
    consequence of one.
    """
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            await AssignmentService(s).grade(
                made["submission"].public_id,
                GradeSubmissionRequest(grade=72, feedback="good"),
                actor=made["tutor"],
            )
            await s.flush()
            return (
                await env.rows_for(s, made["guardian"].id),
                await env.rows_for(s, made["student"].id),
            )
        return go()

    guardian_rows, student_rows = env.run(f)
    assert guardian_rows == []
    assert student_rows == []


def test_the_guardians_copy_names_the_child_and_is_not_written_in_the_second_person(env) -> None:
    """A parent of two told only that "a student in your care" was graded has to go and find out which."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            await _grade(s, made)
            await s.flush()
            return await env.rows_for(s, made["guardian"].id)
        return go()

    row = env.run(f)[0]
    assert "Sam Student" in row.body
    assert "You scored" not in row.body
    assert row.meta and "student_id" in row.meta


def test_a_guardian_who_switches_the_type_off_stops_receiving_it(env) -> None:
    """The separate `ward_*` codes exist so this switch is the guardian's own -- turning it off must not
    disturb the student's notification, which is a different type."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            s.add(NotificationPreference(
                user_id=made["guardian"].id,
                notification_type=NotificationType.WARD_SUBMISSION_GRADED,
                enabled=False,
            ))
            await s.flush()
            await _grade(s, made)
            await s.flush()
            return (
                await env.rows_for(s, made["guardian"].id),
                await env.rows_for(s, made["student"].id),
            )
        return go()

    guardian_rows, student_rows = env.run(f)
    assert guardian_rows == []
    assert len(student_rows) == 1


def test_a_student_with_no_guardian_produces_no_extra_rows(env) -> None:
    """The common case: most students have no linked guardian, and the grade path must not change for them."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            await s.execute(text("DELETE FROM student_guardians WHERE student_id = :s"),
                            {"s": made["student"].id})
            await _grade(s, made)
            await s.flush()
            return (
                await env.rows_for(s, made["guardian"].id),
                await env.rows_for(s, made["student"].id),
            )
        return go()

    guardian_rows, student_rows = env.run(f)
    assert guardian_rows == []
    assert len(student_rows) == 1

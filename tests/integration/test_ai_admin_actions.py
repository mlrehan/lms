"""The academic office's actions through the assistant, against a real database.

Grade book sync, transcripts, guardian/manager links, course, batch and tutor
set-up. Driven the way the registry drives a confirmed tool: preview, bound
parameters merged in, handler. A tutor is in the fixture to prove the handlers
refuse anyone but a Super Admin even when the permission alone would pass.
"""

from __future__ import annotations

import asyncio
import selectors
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from backend.ai.tools.admin_actions import (
    handle_assign_course_tutors,
    handle_create_batch,
    handle_create_course,
    handle_finalise_transcripts,
    handle_generate_transcripts,
    handle_link_person,
    handle_sync_gradebook,
    preview_assign_course_tutors,
    preview_create_batch,
    preview_create_course,
    preview_finalise_transcripts,
    preview_generate_transcripts,
    preview_link_person,
    preview_sync_gradebook,
)
from backend.ai.tools.registry import BOUND_PREFIX, ToolExecutionContext
from backend.core.config import get_settings
from backend.core.errors import AuthorizationError, ConflictError, ValidationError
from backend.db.manager import DatabaseManager
from backend.models.batch import Batch
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.schemas.assignment import AssignmentCreateRequest, GradeSubmissionRequest, SubmitAssignmentRequest
from backend.services.assignment_service import AssignmentService
from backend.utils.enums import AssessmentScope, CourseStatus, EnrollmentStatus, SubmissionType, UserStatus


@pytest.fixture()
def env():  # noqa: ANN201
    tag = "aac" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="ai-admin-actions-tests")
    now = datetime.now(UTC)

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

        def person(kind: str, role: str, first: str) -> User:
            return User(username=f"{tag}.{kind}", slug=f"{tag}-{kind}", email=f"{tag}.{kind}@t.test",
                        first_name=first, last_name=tag, hashed_password="x",
                        status=UserStatus.ACTIVE, roles=[roles[role]])

        people = {k: person(k, r, f) for k, r, f in (
            ("admin", "SUPER_ADMIN", "Ada"), ("tutor", "TUTOR", "Tess"), ("tutor2", "TUTOR", "Tom"),
            ("student", "STUDENT", "Sam"), ("guardian", "GUARDIAN", "Gwen"), ("manager", "CORPORATE_MANAGER", "Mira"),
        )}
        s.add_all(people.values())
        course = Course(title=f"{tag} course", code=f"{tag}-C", status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], [people["tutor"]]
        s.add(course)
        await s.flush()
        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, is_active=True, capacity=10)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        s.add(batch)
        await s.flush()
        s.add(Enrollments(batch_id=batch.id, student_id=people["student"].id, enrollment_date=now,
                          status=EnrollmentStatus.CONFIRMED))
        await s.flush()
        svc = AssignmentService(s)
        asg = await svc.create(course.public_id, AssignmentCreateRequest(
            title=f"{tag} work", description="x", due_date=now + timedelta(days=2), max_score=Decimal("20"),
            submission_type=SubmissionType.TEXT, scope=AssessmentScope.BATCH, batch_id=batch.public_id,
        ), actor=people["tutor"])
        sub = await svc.submit(asg.public_id, SubmitAssignmentRequest(content="done"), actor=people["student"])
        await svc.grade(sub.public_id, GradeSubmissionRequest(grade=Decimal("15"), feedback="ok"), actor=people["tutor"])
        return {k: v.id for k, v in people.items()} | {"course": course.public_id, "batch": batch.public_id}

    ids = run(build)

    def call(who, fn, commit=False):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory() as s:
                user = await s.get(User, ids[who])
                try:
                    result = await fn(ToolExecutionContext(user=user, session=s))
                    if commit:
                        await s.commit()
                    return result
                finally:
                    await s.rollback()
        return loop.run_until_complete(go())

    try:
        yield type("Env", (), dict(tag=tag, ids=ids, call=staticmethod(call), run=staticmethod(run)))
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"u": f"{tag}.%", "c": f"{tag}%"}
                courses = "(SELECT id FROM courses WHERE code LIKE :c OR title LIKE :c)"
                batches = "(SELECT id FROM batches WHERE batch_code LIKE :c)"
                people = "(SELECT id FROM users WHERE username LIKE :u)"
                for sql in (
                    f"DELETE FROM transcripts WHERE student_id IN {people}",
                    f"DELETE FROM gradebook_entries WHERE student_id IN {people}",
                    f"DELETE FROM notifications WHERE user_id IN {people}",
                    f"DELETE FROM assignment_submissions WHERE student_id IN {people}",
                    f"DELETE FROM assignments WHERE course_id IN {courses}",
                    f"DELETE FROM student_guardians WHERE student_id IN {people}",
                    f"DELETE FROM manager_students WHERE student_id IN {people}",
                    f"DELETE FROM enrollments WHERE batch_id IN {batches}",
                    f"DELETE FROM tutor_courses WHERE course_id IN {courses}",
                    f"DELETE FROM batches WHERE id IN {batches} OR course_id IN {courses}",
                    f"DELETE FROM courses WHERE id IN {courses}",
                    f"DELETE FROM user_roles WHERE user_id IN {people}",
                    f"DELETE FROM users WHERE id IN {people}",
                ):
                    try:
                        async with s.begin_nested():
                            await s.execute(text(sql), p)
                    except Exception:  # noqa: BLE001 -- a table this run did not touch
                        pass
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _confirm(env, preview_fn, handler, args, who="admin"):  # noqa: ANN001, ANN202
    async def go(c):  # noqa: ANN001, ANN202
        preview = await preview_fn(args, c)
        bound = args | {f"{BOUND_PREFIX}{k}": v for k, v in (preview.bound_parameters or {}).items()}
        return preview, await handler(bound, c)
    return env.call(who, go, commit=True)


def _one(env, sql, **params):  # noqa: ANN001, ANN202
    async def go(s):  # noqa: ANN001, ANN202
        return (await s.execute(text(sql), params)).all()
    return env.run(go)


# -- authority -----------------------------------------------------------------


@pytest.mark.parametrize("preview_fn,args", [
    (preview_sync_gradebook, {"batch_code": "x"}),
    (preview_generate_transcripts, {"batch_code": "x"}),
    (preview_link_person, {"kind": "guardian", "person": "x", "student": "y"}),
    (preview_create_course, {"title": "Something new"}),
])
def test_a_tutor_is_refused_even_where_a_permission_would_pass(env, preview_fn, args):  # noqa: ANN001
    with pytest.raises(AuthorizationError):
        env.call("tutor", lambda c: preview_fn(args, c))


# -- grade book and transcripts ------------------------------------------------


def test_the_grade_book_is_rebuilt_and_a_second_run_changes_nothing(env):  # noqa: ANN001
    args = {"batch_code": f"{env.tag}-A"}
    _, first = _confirm(env, preview_sync_gradebook, handle_sync_gradebook, args)
    _, second = _confirm(env, preview_sync_gradebook, handle_sync_gradebook, args)
    rows = _one(env, "SELECT count(*) FROM gradebook_entries WHERE student_id = :s", s=env.ids["student"])
    assert rows[0][0] >= 1
    assert second["result"].get("created", 0) == 0


def test_transcripts_without_a_final_percentage_are_named_not_finalised(env):  # noqa: ANN001
    _confirm(env, preview_generate_transcripts, handle_generate_transcripts, {"batch_code": f"{env.tag}-A"})
    assert _one(env, "SELECT count(*) FROM transcripts WHERE student_id = :s", s=env.ids["student"])[0][0] == 1
    _one(env, "UPDATE transcripts SET final_percentage = NULL WHERE student_id = :s RETURNING id", s=env.ids["student"])
    with pytest.raises(ValidationError, match="Sam .*no final percentage"):
        env.call("admin", lambda c: preview_finalise_transcripts({"batch_code": f"{env.tag}-A"}, c))


def test_a_complete_transcript_is_finalised_and_becomes_final(env):  # noqa: ANN001
    _confirm(env, preview_generate_transcripts, handle_generate_transcripts, {"batch_code": f"{env.tag}-A"})
    # Stands in for a student whose every weighted component is assessed.
    _one(env, "UPDATE transcripts SET final_percentage = 75 WHERE student_id = :s RETURNING id", s=env.ids["student"])
    preview, result = _confirm(env, preview_finalise_transcripts, handle_finalise_transcripts,
                               {"batch_code": f"{env.tag}-A"})
    assert "Sam" in preview.summary and "visible to the student" in preview.summary
    assert result["finalised"] == 1
    assert _one(env, "SELECT is_final FROM transcripts WHERE student_id = :s", s=env.ids["student"])[0][0] is True


# -- links ----------------------------------------------------------------------


def test_a_guardian_is_linked_with_the_access_spelled_out_then_unlinked(env):  # noqa: ANN001
    args = {"kind": "guardian", "person": f"Gwen {env.tag}", "student": f"Sam {env.tag}", "relationship": "Mother"}
    preview, _ = _confirm(env, preview_link_person, handle_link_person, args)
    assert "grades, attendance" in preview.summary
    assert _one(env, "SELECT relationship_type FROM student_guardians WHERE guardian_id = :g", g=env.ids["guardian"]) == [("Mother",)]
    with pytest.raises(ConflictError, match="already linked"):
        env.call("admin", lambda c: preview_link_person(args, c))
    _confirm(env, preview_link_person, handle_link_person, args | {"unlink": True})
    assert _one(env, "SELECT count(*) FROM student_guardians WHERE guardian_id = :g", g=env.ids["guardian"])[0][0] == 0


def test_a_manager_is_linked_and_a_wrong_role_is_refused(env):  # noqa: ANN001
    _confirm(env, preview_link_person, handle_link_person,
             {"kind": "manager", "person": f"Mira {env.tag}", "student": f"Sam {env.tag}"})
    assert _one(env, "SELECT count(*) FROM manager_students WHERE manager_id = :m", m=env.ids["manager"])[0][0] == 1
    with pytest.raises(ValidationError, match="does not hold the GUARDIAN role"):
        env.call("admin", lambda c: preview_link_person(
            {"kind": "guardian", "person": f"Tess {env.tag}", "student": f"Sam {env.tag}"}, c))


def test_a_changed_target_after_confirmation_is_refused(env):  # noqa: ANN001
    args = {"kind": "manager", "person": f"Mira {env.tag}", "student": f"Sam {env.tag}"}

    async def go(c):  # noqa: ANN001, ANN202
        preview = await preview_link_person(args, c)
        bound = {f"{BOUND_PREFIX}{k}": v for k, v in preview.bound_parameters.items()}
        return await handle_link_person(args | {"kind": "guardian", "person": f"Gwen {env.tag}"} | bound, c)
    with pytest.raises(ValidationError, match="no longer matches"):
        env.call("admin", go)


# -- courses, batches, tutors ---------------------------------------------------


def test_a_course_is_created_as_a_draft_and_a_duplicate_title_is_refused_before_confirming(env):  # noqa: ANN001
    args = {"title": f"{env.tag} Data Basics", "level": "beginner", "price": 120}
    preview, result = _confirm(env, preview_create_course, handle_create_course, args)
    assert "DRAFT" in preview.summary
    assert _one(env, "SELECT status FROM courses WHERE public_id = :p", p=result["course_id"]) == [("DRAFT",)]
    with pytest.raises(ConflictError):
        env.call("admin", lambda c: preview_create_course(args, c))


def test_a_batch_is_created_on_a_course_and_bad_dates_or_duplicates_are_refused(env):  # noqa: ANN001
    args = {"course": f"{env.tag}-C", "batch_code": f"{env.tag}-B", "capacity": 12,
            "start_date": "2026-11-02", "end_date": "2026-12-14"}
    _confirm(env, preview_create_batch, handle_create_batch, args)
    assert _one(env, "SELECT capacity FROM batches WHERE batch_code = :b", b=f"{env.tag}-B") == [(12,)]
    with pytest.raises(ConflictError, match="already exists"):
        env.call("admin", lambda c: preview_create_batch(args, c))
    with pytest.raises(ValidationError, match="earlier than start_date"):
        env.call("admin", lambda c: preview_create_batch(
            args | {"batch_code": f"{env.tag}-Z", "end_date": "2026-10-01"}, c))


def test_tutors_are_added_without_dropping_the_existing_ones(env):  # noqa: ANN001
    args = {"course": f"{env.tag}-C", "add": [f"Tom {env.tag}"]}
    preview, _ = _confirm(env, preview_assign_course_tutors, handle_assign_course_tutors, args)
    assert "Tess" in preview.summary and "Tom" in preview.summary
    rows = _one(env, "SELECT u.first_name FROM tutor_courses tc JOIN users u ON u.id = tc.tutor_id "
                     "WHERE tc.course_id = (SELECT id FROM courses WHERE code = :c) ORDER BY 1", c=f"{env.tag}-C")
    assert [r[0] for r in rows] == ["Tess", "Tom"]
    with pytest.raises(ValidationError, match="TUTOR role"):
        env.call("admin", lambda c: preview_assign_course_tutors(
            {"course": f"{env.tag}-C", "add": [f"Sam {env.tag}"]}, c))

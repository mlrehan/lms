"""The tutor's other actions through the assistant, against a real database.

Resubmission, absence/exemption, class performance, publishing a recording and
sharing files. Everything is created through the real services, and every
confirmed action is driven the way the registry drives it: preview, bound
parameters merged in, handler. Two tutors: one teaches the class, the other
teaches elsewhere and must reach nothing. A second student called "Ben" sits in
the other tutor's class, so a name matched across the directory instead of
within the class would pick the wrong person.
"""

from __future__ import annotations

import asyncio
import io
import selectors
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from starlette.datastructures import Headers, UploadFile

from backend.ai.tools.registry import BOUND_PREFIX, ToolExecutionContext
from backend.ai.tools.teaching_actions import (
    handle_publish_class_recording,
    handle_record_class_performance,
    handle_request_resubmission,
    handle_set_submission_status,
    handle_share_files,
    preview_publish_class_recording,
    preview_record_class_performance,
    preview_request_resubmission,
    preview_set_submission_status,
    preview_share_files,
)
from backend.core.config import get_settings
from backend.core.errors import AuthorizationError, NotFoundError, ValidationError
from backend.db.manager import DatabaseManager
from backend.models.assignment import AssignmentSubmission
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.guardian import StudentGuardian
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.schemas.assignment import AssignmentCreateRequest, GradeSubmissionRequest, SubmitAssignmentRequest
from backend.services.assignment_service import AssignmentService
from backend.services.resource_service import ResourceService
from backend.utils.enums import (
    AssessmentScope,
    CourseStatus,
    EnrollmentStatus,
    Platforms,
    ResourceType,
    SubmissionState,
    SubmissionType,
    UserStatus,
)


@pytest.fixture()
def env():  # noqa: ANN201
    tag = "tac" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="ai-teaching-actions-tests")
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
            ("tutor", "TUTOR", "Tess"), ("other", "TUTOR", "Otto"), ("ada", "STUDENT", "Ada"),
            ("ben", "STUDENT", "Ben"), ("ben2", "STUDENT", "Ben"), ("guardian", "GUARDIAN", "Gina"),
        )}
        ids = {}
        s.add_all(people.values())
        for code, teacher, pupils in (("A", "tutor", ("ada", "ben")), ("B", "other", ("ben2",))):
            course = Course(title=f"{tag} course {code}", code=f"{tag}-{code}", status=CourseStatus.PUBLISHED)
            course.batches, course.resources, course.tags, course.tutors = [], [], [], []
            s.add(course)
            await s.flush()
            batch = Batch(batch_code=f"{tag}-{code}", course_id=course.id, is_active=True, capacity=10)
            batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
            s.add(batch)
            await s.flush()
            klass = BatchSession(batch_id=batch.id, tutor_id=people[teacher].id,
                                 session_start_time=now - timedelta(hours=2), session_end_time=now - timedelta(hours=1),
                                 duration_minutes=60, platform=Platforms.Zoom)
            s.add(klass)
            for who in pupils:
                s.add(Enrollments(batch_id=batch.id, student_id=people[who].id, enrollment_date=now,
                                  status=EnrollmentStatus.CONFIRMED))
            await s.flush()
            ids[f"course{code}"], ids[f"batch{code}"], ids[f"session{code}"] = course.public_id, batch.public_id, klass.public_id
        s.add(StudentGuardian(guardian_id=people["guardian"].id, student_id=people["ada"].id, is_primary=True, created_at=now))
        await s.flush()
        return ids | {k: v.id for k, v in people.items()}

    ids = run(build)
    keys: list[str] = []

    async def work(s):  # noqa: ANN001, ANN202
        tutor = await s.get(User, ids["tutor"])
        svc = AssignmentService(s)
        asg = await svc.create(ids["courseA"], AssignmentCreateRequest(
            title=f"{tag} loops", description="Write a loop.", due_date=now + timedelta(days=3),
            max_score=Decimal("20"), submission_type=SubmissionType.TEXT, allow_resubmission=True,
            scope=AssessmentScope.BATCH, batch_id=ids["batchA"],
        ), actor=tutor)
        sub = await svc.submit(asg.public_id, SubmitAssignmentRequest(content="for i in range(5): print(i)"),
                               actor=await s.get(User, ids["ada"]))
        await svc.grade(sub.public_id, GradeSubmissionRequest(grade=Decimal("11"), feedback="Off by one."), actor=tutor)
        video = UploadFile(io.BytesIO(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64), filename="week1.mp4",
                           headers=Headers({"content-type": "video/mp4"}))
        res = await ResourceService(s).upload(upload=video, actor=tutor, name=f"{tag} week 1 recording",
                                              resource_type=ResourceType.recordings, folder_public_id=None,
                                              course_public_id=ids["courseA"], batch_public_id=ids["batchA"])
        keys.append(res.path)
        return {"submission": str(sub.public_id), "resource": str(res.public_id)}

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
        made = run(work)
        yield type("Env", (), dict(tag=tag, ids=ids, made=made, call=staticmethod(call), run=staticmethod(run)))
    finally:
        async def cleanup() -> None:
            from backend.storage import get_storage

            for key in keys:
                try:
                    await get_storage().delete(key)
                except Exception:  # noqa: BLE001
                    pass
            async with db.session_factory.begin() as s:
                p = {"u": f"{tag}.%", "c": f"{tag}-%"}
                courses = "(SELECT id FROM courses WHERE code LIKE :c)"
                people = "(SELECT id FROM users WHERE username LIKE :u)"
                resources = f"(SELECT id FROM resources WHERE course_id IN {courses})"
                sessions = "(SELECT id FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c))"
                for sql in (
                    f"DELETE FROM class_performance_marks WHERE session_id IN {sessions}",
                    f"DELETE FROM gradebook_entries WHERE student_id IN {people}",
                    f"DELETE FROM notifications WHERE user_id IN {people}",
                    f"DELETE FROM shared_resources WHERE resource_id IN {resources}",
                    f"UPDATE batch_sessions SET recording_resource_id = NULL WHERE id IN {sessions}",
                    f"DELETE FROM resource_versions WHERE resource_id IN {resources}",
                    f"DELETE FROM resources WHERE id IN {resources}",
                    f"DELETE FROM assignment_submissions WHERE assignment_id IN (SELECT id FROM assignments WHERE course_id IN {courses})",
                    f"DELETE FROM assignments WHERE course_id IN {courses}",
                    f"DELETE FROM student_guardians WHERE student_id IN {people}",
                    "DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM batches WHERE batch_code LIKE :c",
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


def _confirm(env, who, preview_fn, handler, args):  # noqa: ANN001, ANN202
    async def go(c):  # noqa: ANN001, ANN202
        preview = await preview_fn(args, c)
        bound = args | {f"{BOUND_PREFIX}{k}": v for k, v in (preview.bound_parameters or {}).items()}
        return preview, await handler(bound, c)
    return env.call(who, go, commit=True)


def _submission(env):  # noqa: ANN001, ANN202
    async def go(s):  # noqa: ANN001, ANN202
        return (await s.execute(select(AssignmentSubmission).where(
            AssignmentSubmission.public_id == uuid.UUID(env.made["submission"])))).scalar_one()
    return env.run(go)


# -- resubmission ---------------------------------------------------------------


def test_resubmission_is_requested_by_name_with_the_reason_and_the_student_is_told(env):  # noqa: ANN001
    args = {"assignment_title": f"{env.tag} loops", "student_name": "Ada", "reason": "Print 1 to 5, not 0 to 4."}
    preview, result = _confirm(env, "tutor", preview_request_resubmission, handle_request_resubmission, args)
    assert "Ada" in preview.summary and "hidden" in preview.summary  # the current 11 stops showing
    assert result["state"] == "RESUBMISSION_REQUIRED"
    row = _submission(env)
    assert row.state is SubmissionState.RESUBMISSION_REQUIRED and row.feedback == "Print 1 to 5, not 0 to 4."

    async def told(s):  # noqa: ANN001, ANN202
        return (await s.execute(text("SELECT count(*) FROM notifications WHERE user_id = :u AND title LIKE 'Resubmission%'"),
                                {"u": env.ids["ada"]})).scalar_one()
    assert env.run(told) == 1


def test_a_changed_reason_after_confirmation_is_refused(env):  # noqa: ANN001
    args = {"assignment_title": f"{env.tag} loops", "student_name": "Ada", "reason": "Fix the range."}

    async def go(c):  # noqa: ANN001, ANN202
        preview = await preview_request_resubmission(args, c)
        bound = {f"{BOUND_PREFIX}{k}": v for k, v in preview.bound_parameters.items()}
        return await handle_request_resubmission(args | {"reason": "Something else entirely."} | bound, c)
    with pytest.raises(ValidationError, match="no longer matches"):
        env.call("tutor", go)


def test_another_tutor_cannot_hand_the_work_back(env):  # noqa: ANN001
    with pytest.raises(NotFoundError):
        env.call("other", lambda c: preview_request_resubmission(
            {"assignment_title": f"{env.tag} loops", "student_name": "Ada", "reason": "Redo it please."}, c))


# -- absence and exemption ------------------------------------------------------


def test_an_exemption_needs_a_reason_and_is_recorded(env):  # noqa: ANN001
    base = {"assignment_title": f"{env.tag} loops", "student_name": "Ada", "status": "EXEMPTED"}
    with pytest.raises(ValidationError, match="reason"):
        env.call("tutor", lambda c: preview_set_submission_status(base, c))
    _, result = _confirm(env, "tutor", preview_set_submission_status, handle_set_submission_status,
                         base | {"reason": "Medical certificate"})
    assert result["state"] == "EXEMPTED" and _submission(env).state is SubmissionState.EXEMPTED


def test_absence_for_work_never_handed_in_is_explained_not_faked(env):  # noqa: ANN001
    with pytest.raises(ValidationError, match="no submission"):
        env.call("tutor", lambda c: preview_set_submission_status(
            {"assignment_title": f"{env.tag} loops", "student_name": "Ben", "status": "ABSENT"}, c))


# -- class performance ----------------------------------------------------------


def test_class_performance_is_matched_within_the_class_and_saved_as_a_draft(env):  # noqa: ANN001
    """'Ben' also exists in the other tutor's class; only this class's Ben may be matched."""
    args = {"batch_code": f"{env.tag}-A", "entries": [
        {"student_name": "Ada", "overall_score": 8, "comment": "Led the pair exercise."},
        {"student_name": "Ben", "participation": 6, "teamwork": 7},
    ]}
    preview, result = _confirm(env, "tutor", preview_record_class_performance, handle_record_class_performance, args)
    assert "draft" in preview.summary.lower() and result["saved"] == 2

    async def marks(s):  # noqa: ANN001, ANN202
        return (await s.execute(text(
            "SELECT u.username, m.state FROM class_performance_marks m JOIN users u ON u.id = m.student_id "
            "WHERE m.session_id = (SELECT id FROM batch_sessions WHERE public_id = :p) ORDER BY u.username"),
            {"p": env.ids["sessionA"]})).all()
    rows = env.run(marks)
    assert [r[0] for r in rows] == [f"{env.tag}.ada", f"{env.tag}.ben"]  # not ben2
    assert {r[1] for r in rows} == {"DRAFT"}


def test_a_name_outside_the_class_refuses_the_whole_grid(env):  # noqa: ANN001
    args = {"batch_code": f"{env.tag}-A", "entries": [
        {"student_name": "Ada", "overall_score": 8}, {"student_name": "Gina", "overall_score": 5}]}
    with pytest.raises(ValidationError, match="Nobody called 'Gina'"):
        env.call("tutor", lambda c: preview_record_class_performance(args, c))


def test_a_mark_above_the_scale_is_refused(env):  # noqa: ANN001
    args = {"batch_code": f"{env.tag}-A", "entries": [{"student_name": "Ada", "overall_score": 11}]}
    with pytest.raises(ValidationError, match="between 0 and 10"):
        env.call("tutor", lambda c: preview_record_class_performance(args, c))


def test_another_tutor_cannot_mark_this_class(env):  # noqa: ANN001
    args = {"batch_code": f"{env.tag}-A", "entries": [{"student_name": "Ada", "overall_score": 8}]}
    with pytest.raises((NotFoundError, AuthorizationError)):
        env.call("other", lambda c: preview_record_class_performance(args, c))


# -- recordings -----------------------------------------------------------------


def test_a_recording_link_is_validated_and_published(env):  # noqa: ANN001
    with pytest.raises(ValidationError, match="cannot be used"):
        env.call("tutor", lambda c: preview_publish_class_recording(
            {"batch_code": f"{env.tag}-A", "link": "javascript:alert(1)"}, c))
    args = {"batch_code": f"{env.tag}-A", "link": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    preview, _ = _confirm(env, "tutor", preview_publish_class_recording, handle_publish_class_recording, args)
    assert "guardians" in preview.summary

    async def link(s):  # noqa: ANN001, ANN202
        return (await s.execute(text("SELECT recording_link FROM batch_sessions WHERE public_id = :p"),
                                {"p": env.ids["sessionA"]})).scalar_one()
    assert "youtube" in env.run(link)


def test_a_library_video_is_published_as_the_recording(env):  # noqa: ANN001
    args = {"batch_code": f"{env.tag}-A", "file_name": f"{env.tag} week 1 recording"}
    _confirm(env, "tutor", preview_publish_class_recording, handle_publish_class_recording, args)

    async def attached(s):  # noqa: ANN001, ANN202
        return (await s.execute(text(
            "SELECT r.public_id FROM batch_sessions b JOIN resources r ON r.id = b.recording_resource_id "
            "WHERE b.public_id = :p"), {"p": env.ids["sessionA"]})).scalar_one()
    assert str(env.run(attached)) == env.made["resource"]


def test_another_tutor_cannot_publish_to_this_class(env):  # noqa: ANN001
    with pytest.raises(NotFoundError):
        env.call("other", lambda c: preview_publish_class_recording(
            {"batch_code": f"{env.tag}-A", "link": "https://vimeo.com/76979871"}, c))


# -- sharing --------------------------------------------------------------------


def test_files_are_shared_with_the_whole_batch_and_its_guardians_view_only(env):  # noqa: ANN001
    args = {"file_names": [f"{env.tag} week 1 recording"], "batch_code": f"{env.tag}-A", "include_guardians": True}
    preview, _ = _confirm(env, "tutor", preview_share_files, handle_share_files, args)
    assert "view only" in preview.summary

    async def shared(s):  # noqa: ANN001, ANN202
        return (await s.execute(text(
            "SELECT u.username, sr.level FROM shared_resources sr JOIN users u ON u.id = sr.shared_with_user_id "
            "WHERE sr.resource_id = (SELECT id FROM resources WHERE public_id = :r) ORDER BY u.username"),
            {"r": env.made["resource"]})).all()
    rows = env.run(shared)
    assert [r[0] for r in rows] == [f"{env.tag}.ada", f"{env.tag}.ben", f"{env.tag}.guardian"]
    assert {r[1] for r in rows} == {"VIEW"}


def test_nobody_outside_the_tutors_audience_can_be_named(env):  # noqa: ANN001
    """The other tutor's 'Ben' is outside this tutor's audience; the name must reach only their own Ben."""
    args = {"file_names": [f"{env.tag} week 1 recording"], "people": ["Otto"]}
    with pytest.raises(ValidationError, match="Nobody called 'Otto'"):
        env.call("tutor", lambda c: preview_share_files(args, c))


def test_a_student_cannot_share_anything(env):  # noqa: ANN001
    with pytest.raises(AuthorizationError):
        env.call("ada", lambda c: preview_share_files(
            {"file_names": [f"{env.tag} week 1 recording"], "batch_code": f"{env.tag}-A"}, c))


def test_a_cover_tutor_who_can_see_the_batch_cannot_mark_a_class_they_did_not_teach(env):  # noqa: ANN001
    """The rule `may_record` exists for: seeing the batch is not having observed this class.
    Refused at the preview, so the tutor is never asked to confirm something that cannot happen."""
    async def cover(s):  # noqa: ANN001, ANN202
        batch = (await s.execute(select(Batch).where(Batch.public_id == env.ids["batchA"]))).scalar_one()
        s.add(BatchSession(batch_id=batch.id, tutor_id=env.ids["other"],
                           session_start_time=datetime.now(UTC) - timedelta(days=3),
                           session_end_time=datetime.now(UTC) - timedelta(days=3, hours=-1),
                           duration_minutes=60, platform=Platforms.Zoom))
    env.run(cover)
    args = {"session_id": str(env.ids["sessionA"]), "entries": [{"student_name": "Ada", "overall_score": 8}]}
    with pytest.raises(AuthorizationError, match="assigned tutor"):
        env.call("other", lambda c: preview_record_class_performance(args, c))


def test_zero_padded_criteria_beside_an_overall_mark_are_not_stored_as_zeros(env):  # noqa: ANN001
    """Live finding: the model sent every criterion as 0 next to 'Ada 8/10', and the preview showed only the 8."""
    from backend.ai.tools.teaching_actions import _CRITERIA

    padded = {"student_name": "Ada", "overall_score": 8, **{c: 0 for c in _CRITERIA}}
    preview, _ = _confirm(env, "tutor", preview_record_class_performance, handle_record_class_performance,
                          {"batch_code": f"{env.tag}-A", "entries": [padded]})
    assert "participation" not in preview.summary

    async def stored(s):  # noqa: ANN001, ANN202
        return (await s.execute(text(
            "SELECT overall_score, participation, teamwork FROM class_performance_marks "
            "WHERE session_id = (SELECT id FROM batch_sessions WHERE public_id = :p)"), {"p": env.ids["sessionA"]})).one()
    assert env.run(stored) == (Decimal("8.00"), None, None)


def test_criteria_given_with_an_overall_mark_are_all_shown_before_confirming(env):  # noqa: ANN001
    args = {"batch_code": f"{env.tag}-A", "entries": [
        {"student_name": "Ada", "overall_score": 8, "participation": 9, "teamwork": 0}]}
    preview = env.call("tutor", lambda c: preview_record_class_performance(args, c))
    assert "overall 8.00" in preview.summary and "participation 9.00" in preview.summary and "teamwork 0.00" in preview.summary


def test_criteria_are_taken_from_one_object_holding_only_what_was_given(env):  # noqa: ANN001
    args = {"batch_code": f"{env.tag}-A", "entries": [
        {"student_name": "Ada", "overall_score": 8, "criteria": {"participation": 9, "teamwork": 7}}]}
    preview, _ = _confirm(env, "tutor", preview_record_class_performance, handle_record_class_performance, args)
    assert "interaction" not in preview.summary

    async def stored(s):  # noqa: ANN001, ANN202
        return (await s.execute(text(
            "SELECT participation, teamwork, interaction FROM class_performance_marks "
            "WHERE session_id = (SELECT id FROM batch_sessions WHERE public_id = :p)"), {"p": env.ids["sessionA"]})).one()
    assert env.run(stored) == (Decimal("9.00"), Decimal("7.00"), None)
    with pytest.raises(ValidationError, match="Unknown criteria"):
        env.call("tutor", lambda c: preview_record_class_performance(
            {"batch_code": f"{env.tag}-A", "entries": [{"student_name": "Ada", "criteria": {"charm": 5}}]}, c))

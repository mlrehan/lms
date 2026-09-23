"""Official transcripts (spec §5).

The test this file exists for is `test_a_super_admin_cannot_put_a_draft_mark_on_a_transcript`.

§5 says draft marks must never appear on an official transcript. The obvious
implementation routes transcript generation through the ordinary performance
call, which decides what to include from *who is asking* -- and a Super Admin
has permission to see unreleased marking. So the obvious implementation puts
draft marks on official documents for the one person most likely to be issuing
them, and every other test in this file would still pass.

The rest covers what makes a transcript a record rather than a view: it does not
restate itself when the underlying marks change, a course still in progress has
no final result to certify, and a finalised one is not quietly rewritten.
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
from backend.core.errors import ConflictError
from backend.db.manager import DatabaseManager
from backend.models.assignment import Assignment, AssignmentSubmission
from backend.models.batch import Batch
from backend.models.course import Course, TutorCourse
from backend.models.enrollment import Enrollments
from backend.models.exam import Exam, ExamResult
from backend.models.gradebook import GradeBand, Transcript
from backend.models.grading import GradingScheme, GradingSchemeComponent
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.services.transcript_service import TranscriptService
from backend.utils.enums import (
    AssessmentScope,
    CourseStatus,
    EnrollmentStatus,
    ExamType,
    GradeComponentType as C,
    SubmissionState as St,
    SubmissionType,
    UserStatus,
)

D = Decimal


@pytest.fixture()
def env():
    tag = "tr" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="transcript-tests")

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s, *, exam_published: bool = True):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}
        admin = (
            await s.execute(select(User).where(User.username == "superadmin"))
        ).scalar_one()

        def user(kind: str, role: str) -> User:
            return User(username=f"{tag}.{kind}", slug=f"{tag}-{kind}",
                        email=f"{tag}.{kind}@t.test", hashed_password="x",
                        status=UserStatus.ACTIVE, roles=[roles[role]])

        tutor, alice = user("tutor", "TUTOR"), user("alice", "STUDENT")

        scheme = GradingScheme(name=f"{tag} scheme", created_at=datetime.now(UTC),
                               is_default=False, is_active=True)
        scheme.components = [
            GradingSchemeComponent(component_type=C.ASSIGNMENT, weight_percentage=D("50")),
            GradingSchemeComponent(component_type=C.FINAL_EXAM, weight_percentage=D("50")),
        ]
        scheme.bands = [
            GradeBand(min_score=D("70"), max_score=D("100"), letter_grade=f"{tag[:2]}A",
                      gpa_points=D("4"), is_pass=True),
            GradeBand(min_score=D("0"), max_score=D("69.99"), letter_grade=f"{tag[:2]}F",
                      gpa_points=D("0"), is_pass=False),
        ]
        s.add_all([tutor, alice, scheme])
        await s.flush()

        course = Course(title=f"{tag} course", code=f"{tag}-C",
                        status=CourseStatus.PUBLISHED, grading_scheme_id=scheme.id)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add(course)
        await s.flush()
        s.add(TutorCourse(tutor_id=tutor.id, course_id=course.id))

        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=60), is_active=True, capacity=10)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        s.add(batch)
        await s.flush()
        s.add(Enrollments(batch_id=batch.id, student_id=alice.id,
                          enrollment_date=datetime.now(UTC),
                          status=EnrollmentStatus.CONFIRMED))

        now = datetime.now(UTC)
        assignment = Assignment(course_id=course.id, scope=AssessmentScope.COURSE,
                                title=f"{tag} Essay", due_date=now - timedelta(days=5),
                                max_score=D("100"), submission_type=SubmissionType.TEXT,
                                allow_late_submissions=False)
        assignment.submissions = []
        s.add(assignment)
        await s.flush()
        s.add(AssignmentSubmission(assignment_id=assignment.id, student_id=alice.id,
                                   submitted_at=now, content="x", grade=D("90"),
                                   raw_grade=D("90"), state=St.PUBLISHED,
                                   graded_by_id=tutor.id, graded_at=now))

        exam = Exam(course_id=course.id, batch_id=batch.id, scope=AssessmentScope.BATCH,
                    exam_type=ExamType.FINAL, title=f"{tag} Final",
                    scheduled_at=now - timedelta(days=1), total_marks=D("100"),
                    passing_marks=D("40"), is_published=True)
        exam.invigilators, exam.results = [], []
        s.add(exam)
        await s.flush()
        # 50/100, and whether it has been *released* is the variable this
        # fixture exists to control.
        s.add(ExamResult(exam_id=exam.id, student_id=alice.id, marks_obtained=D("50"),
                         is_published=exam_published,
                         state=St.PUBLISHED if exam_published else St.GRADED))
        await s.flush()
        return {"admin": admin, "tutor": tutor, "alice": alice,
                "course": course, "batch": batch, "exam": exam}

    ns = type("Env", (), dict(tag=tag, run=staticmethod(run), build=staticmethod(build)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"u": f"{tag}.%", "c": f"{tag}-%", "t": f"{tag}%"}
                b = "(SELECT id FROM batches WHERE batch_code LIKE :c)"
                await s.execute(text(f"DELETE FROM transcripts WHERE batch_id IN {b}"), p)
                await s.execute(text("DELETE FROM assignment_submissions WHERE assignment_id IN (SELECT id FROM assignments WHERE title LIKE :t)"), p)
                await s.execute(text("DELETE FROM assignments WHERE title LIKE :t"), p)
                await s.execute(text("DELETE FROM exam_results WHERE exam_id IN (SELECT id FROM exams WHERE title LIKE :t)"), p)
                await s.execute(text("DELETE FROM exams WHERE title LIKE :t"), p)
                await s.execute(text(f"DELETE FROM enrollments WHERE batch_id IN {b}"), p)
                await s.execute(text("DELETE FROM batches WHERE batch_code LIKE :c"), p)
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


def _generate(env, *, exam_published: bool = True):
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s, exam_published=exam_published)
            row = await TranscriptService(s).generate(
                student_id=made["alice"].id, batch_id=made["batch"].id, actor=made["admin"]
            )
            await s.flush()
            return row, made
        return go()
    return env.run(f)


# ------------------------------------------- the rule this file exists for ---


def test_a_super_admin_cannot_put_a_draft_mark_on_a_transcript(env) -> None:
    """§5, and the trap underneath it.

    The examination is marked 50 but **not released**. A Super Admin has
    permission to see unreleased marking, so a transcript generated through the
    ordinary actor-aware path would include it — silently, and for exactly the
    person most likely to be issuing official documents.

    Assignment 90 is published; the examination is not. With the rule working,
    only 50% of the scheme has been assessed, so there is no final result to
    certify. Without it, the transcript would read 70% and a pass.
    """
    row, _ = _generate(env, exam_published=False)

    assert row.final_percentage is None, (
        "A draft examination mark reached an official transcript."
    )
    counted = [c for c in (row.breakdown or []) if c["counted"]]
    assert [c["component"] for c in counted] == ["ASSIGNMENT"]
    assert row.total_marks_possible == D("50.00")


def test_and_once_it_is_released_it_does_appear(env) -> None:
    """The counterpart, without which the test above could be passing because
    transcripts never include anything.

    Assignment 90 x 50% + Examination 50 x 50% = 70.
    """
    row, _ = _generate(env, exam_published=True)

    assert row.final_percentage == D("70.00")
    assert row.is_pass is True
    assert row.overall_grade == f"{env.tag[:2]}A"


# ------------------------------------------------------------ the record ---


def test_it_records_the_scheme_that_produced_it(env) -> None:
    """Schemes change. A transcript that cannot say which policy produced its
    figures cannot be defended in an appeal."""
    row, _ = _generate(env)
    assert row.scheme_name == f"{env.tag} scheme"


def test_it_freezes_the_breakdown(env) -> None:
    """§37's arithmetic, kept. A student querying this in three years is shown
    what produced their grade, not a fresh sum against today's scheme."""
    row, _ = _generate(env)
    lines = {c["component"]: c for c in row.breakdown}
    assert lines["ASSIGNMENT"]["contribution"] == "45.00"
    assert lines["FINAL_EXAM"]["contribution"] == "25.00"


def test_it_does_not_restate_itself_when_a_mark_later_changes(env) -> None:
    """The reason these figures are stored rather than derived.

    A transcript that silently updated when a tutor corrected a register would
    invalidate a document somebody has already relied on.
    """
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = TranscriptService(s)
            row = await svc.generate(student_id=made["alice"].id,
                                     batch_id=made["batch"].id, actor=made["admin"])
            await s.flush()
            issued = row.final_percentage

            # The examination mark is corrected downwards afterwards.
            result = (
                await s.execute(
                    select(ExamResult).where(ExamResult.exam_id == made["exam"].id)
                )
            ).scalar_one()
            result.marks_obtained = D("10")
            await s.flush()

            stored = (
                await s.execute(
                    select(Transcript).where(Transcript.id == row.id)
                )
            ).scalar_one()
            return issued, stored.final_percentage
        return go()

    issued, after = env.run(f)
    assert issued == D("70.00")
    assert after == D("70.00")   # unchanged until somebody re-issues it


# --------------------------------------------------------------- finalising ---


def test_an_incomplete_course_cannot_be_certified(env) -> None:
    """§38: a document certifying a mid-course standing as a final result is
    the error the whole missing-marks rule exists to prevent."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s, exam_published=False)
            svc = TranscriptService(s)
            row = await svc.generate(student_id=made["alice"].id,
                                     batch_id=made["batch"].id, actor=made["admin"])
            await s.flush()
            with pytest.raises(ConflictError) as refused:
                await svc.finalise(row.public_id, actor=made["admin"])
            return str(refused.value)
        return go()

    assert "not complete" in env.run(f).lower()


def test_finalising_records_who_stood_behind_it(env) -> None:
    """§5's administrator verification. `generated_at` says when the figures
    were computed; `issued_by` says who is prepared to defend them."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = TranscriptService(s)
            row = await svc.generate(student_id=made["alice"].id,
                                     batch_id=made["batch"].id, actor=made["admin"])
            await s.flush()
            final = await svc.finalise(row.public_id, actor=made["admin"])
            return final.is_final, final.issued_by == made["admin"].id, final.issued_at is not None
        return go()

    assert env.run(f) == (True, True, True)


def test_a_finalised_transcript_is_not_quietly_rewritten(env) -> None:
    """Re-issuing is a deliberate act, not a side effect of somebody pressing
    "generate" on a batch."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = TranscriptService(s)
            row = await svc.generate(student_id=made["alice"].id,
                                     batch_id=made["batch"].id, actor=made["admin"])
            await s.flush()
            await svc.finalise(row.public_id, actor=made["admin"])
            await s.flush()

            with pytest.raises(ConflictError):
                await svc.generate(student_id=made["alice"].id,
                                   batch_id=made["batch"].id, actor=made["admin"])

            # But an explicit re-issue is allowed.
            again = await svc.generate(student_id=made["alice"].id,
                                       batch_id=made["batch"].id,
                                       actor=made["admin"], reissue=True)
            return again.final_percentage
        return go()

    assert env.run(f) == D("70.00")


# ------------------------------------------------------- the batch path ---
#
# `POST /batches/{id}/transcripts/generate` is the endpoint an administrator
# actually presses, and it used to reach a *second* implementation -- an
# aggregation over `gradebook_entries` at a flat weight with no publication
# filter at all. Every test above passed while that route existed, because
# every test above called `generate` directly. So the batch path gets its own
# §5 test rather than being assumed to inherit one.


def test_the_batch_run_also_refuses_draft_marks(env) -> None:
    """§5 through the path the console uses.

    Same fixture as the single-student case: assignment 90 published,
    examination 50 withheld. A batch run must reach the same answer -- no final
    result -- and not a 70% pass assembled from an unreleased mark.
    """
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s, exam_published=False)
            stats = await TranscriptService(s).generate_for_batch(
                batch_id=made["batch"].id, actor=made["admin"]
            )
            await s.flush()
            row = (
                await s.execute(
                    select(Transcript).where(Transcript.batch_id == made["batch"].id)
                )
            ).scalar_one()
            return stats, row.final_percentage, row.total_marks_possible
        return go()

    stats, percentage, assessed = env.run(f)
    assert stats["issued"] == 1
    assert percentage is None, "A draft examination mark reached a batch-generated transcript."
    assert assessed == D("50.00")


def test_the_batch_run_issues_a_full_result_when_everything_is_released(env) -> None:
    """Without this the test above could be passing because the batch run
    issues nothing at all."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s, exam_published=True)
            stats = await TranscriptService(s).generate_for_batch(
                batch_id=made["batch"].id, actor=made["admin"]
            )
            await s.flush()
            row = (
                await s.execute(
                    select(Transcript).where(Transcript.batch_id == made["batch"].id)
                )
            ).scalar_one()
            return stats, row.final_percentage, row.overall_grade
        return go()

    stats, percentage, grade = env.run(f)
    assert stats == {"issued": 1, "updated": 0, "skipped_final": 0, "skipped_no_marks": 0}
    assert percentage == D("70.00")
    assert grade == f"{env.tag[:2]}A"


def test_a_batch_run_skips_a_finalised_transcript_rather_than_refusing(env) -> None:
    """Skipped, not refused. An administrator re-running a batch must not be
    blocked by the records that are already closed -- and silently rewriting
    them would be worse than either."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = TranscriptService(s)
            row = await svc.generate(student_id=made["alice"].id,
                                     batch_id=made["batch"].id, actor=made["admin"])
            await s.flush()
            await svc.finalise(row.public_id, actor=made["admin"])
            await s.flush()

            # The mark is corrected afterwards, so a rewrite would be visible.
            result = (
                await s.execute(
                    select(ExamResult).where(ExamResult.exam_id == made["exam"].id)
                )
            ).scalar_one()
            result.marks_obtained = D("10")
            await s.flush()

            stats = await svc.generate_for_batch(
                batch_id=made["batch"].id, actor=made["admin"]
            )
            await s.flush()
            stored = (
                await s.execute(select(Transcript).where(Transcript.id == row.id))
            ).scalar_one()
            return stats, stored.final_percentage
        return go()

    stats, percentage = env.run(f)
    assert stats["skipped_final"] == 1
    assert stats["issued"] == 0 and stats["updated"] == 0
    assert percentage == D("70.00"), "A finalised transcript was rewritten by a batch run."

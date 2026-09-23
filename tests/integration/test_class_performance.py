"""Tutor class-performance marks (spec §11).

The test this file exists for is
`test_class_performance_marks_make_a_transcript_completable`.

`PRACTICAL` was a weighted component with no write path anywhere. That reads like
a missing feature and was worse than one: under the seeded default scheme class
performance carries 10% of the mark, an unassessed component is excluded rather
than zeroed (§38), and a result is only *final* once every weighted component has
been assessed -- so the missing write path made it impossible to complete a
transcript at all. The gap in §11 silently disabled §5.

The rest covers the three ways this feature could look right and be wrong:

* **A blank criterion is not a zero.** A tutor who assessed participation only
  must not have seven zeros averaged into their student's figure.
* **A draft is not a result.** The same marks, a guardian asking, a different
  answer -- and a guardian who could read a tutor's working notes on how their
  child behaved in one class is the failure this lifecycle exists to prevent.
* **Only the assigned tutor may record.** A colleague who was not in the room
  cannot make a statement about what happened in it.
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
from backend.core.errors import AuthorizationError, NotFoundError, ValidationError
from backend.db.manager import DatabaseManager
from backend.models.assignment import Assignment, AssignmentSubmission
from backend.models.batch import Batch, BatchSession
from backend.models.class_performance import ClassPerformanceMark
from backend.models.course import Course, TutorCourse
from backend.models.enrollment import Enrollments
from backend.models.gradebook import GradeBand
from backend.models.grading import GradingScheme, GradingSchemeComponent
from backend.models.guardian import StudentGuardian
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.services.class_performance_service import ClassPerformanceService
from backend.services.performance_service import PerformanceService
from backend.services.transcript_service import TranscriptService
from backend.utils.enums import (
    AssessmentScope,
    CourseStatus,
    EnrollmentStatus,
    GradeComponentType as C,
    Platforms,
    ResultState,
    SubmissionState as St,
    SubmissionType,
    UserStatus,
)

D = Decimal


@pytest.fixture()
def env():
    tag = "cp" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="class-perf-tests")

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}
        admin = (
            await s.execute(select(User).where(User.username == "superadmin"))
        ).scalar_one()

        def user(kind: str, role: str) -> User:
            return User(username=f"{tag}.{kind}", slug=f"{tag}-{kind}",
                        email=f"{tag}.{kind}@t.test", hashed_password="x",
                        status=UserStatus.ACTIVE, roles=[roles[role]])

        tutor = user("tutor", "TUTOR")
        other_tutor = user("other", "TUTOR")
        alice = user("alice", "STUDENT")
        bob = user("bob", "STUDENT")
        # Enrolled in nothing, so genuinely outside every scope.
        outsider = user("outsider", "STUDENT")
        parent = user("parent", "GUARDIAN")

        # Assignments 50%, class performance 50%. Two components, so "complete"
        # is reachable in this fixture and the §5 claim above can actually be
        # demonstrated rather than asserted.
        scheme = GradingScheme(name=f"{tag} scheme", created_at=datetime.now(UTC),
                               is_default=False, is_active=True)
        scheme.components = [
            GradingSchemeComponent(component_type=C.ASSIGNMENT, weight_percentage=D("50")),
            GradingSchemeComponent(component_type=C.PRACTICAL, weight_percentage=D("50")),
        ]
        scheme.bands = [
            GradeBand(min_score=D("70"), max_score=D("100"), letter_grade=f"{tag[:2]}A",
                      gpa_points=D("4"), is_pass=True),
            GradeBand(min_score=D("0"), max_score=D("69.99"), letter_grade=f"{tag[:2]}F",
                      gpa_points=D("0"), is_pass=False),
        ]
        s.add_all([tutor, other_tutor, alice, bob, outsider, parent, scheme])
        await s.flush()

        course = Course(title=f"{tag} course", code=f"{tag}-C",
                        status=CourseStatus.PUBLISHED, grading_scheme_id=scheme.id)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add(course)
        await s.flush()
        s.add_all([
            TutorCourse(tutor_id=tutor.id, course_id=course.id),
            TutorCourse(tutor_id=other_tutor.id, course_id=course.id),
        ])
        s.add(StudentGuardian(guardian_id=parent.id, student_id=alice.id,
                              relationship_type="Parent", is_primary=True,
                              created_at=datetime.now(UTC)))

        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=60), is_active=True, capacity=20)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        s.add(batch)
        await s.flush()
        for student in (alice, bob):
            s.add(Enrollments(batch_id=batch.id, student_id=student.id,
                              enrollment_date=datetime.now(UTC),
                              status=EnrollmentStatus.CONFIRMED))

        now = datetime.now(UTC)
        batch_session = BatchSession(
            batch_id=batch.id, tutor_id=tutor.id,
            session_start_time=now - timedelta(days=2),
            session_end_time=now - timedelta(days=2) + timedelta(hours=2),
            duration_minutes=120, platform=Platforms.Zoom,
        )
        batch_session.attendances = []
        second = BatchSession(
            batch_id=batch.id, tutor_id=tutor.id,
            session_start_time=now - timedelta(days=1),
            session_end_time=now - timedelta(days=1) + timedelta(hours=2),
            duration_minutes=120, platform=Platforms.Zoom,
        )
        second.attendances = []
        s.add_all([batch_session, second])
        await s.flush()

        # A published assignment at 80, so the other half of the scheme is
        # assessed and a completed transcript is only waiting on §11.
        assignment = Assignment(course_id=course.id, scope=AssessmentScope.COURSE,
                                title=f"{tag} Essay", due_date=now - timedelta(days=5),
                                max_score=D("100"), submission_type=SubmissionType.TEXT,
                                allow_late_submissions=False)
        assignment.submissions = []
        s.add(assignment)
        await s.flush()
        s.add(AssignmentSubmission(assignment_id=assignment.id, student_id=alice.id,
                                   submitted_at=now, content="x", grade=D("80"),
                                   raw_grade=D("80"), state=St.PUBLISHED,
                                   graded_by_id=tutor.id, graded_at=now))
        await s.flush()
        return {"admin": admin, "tutor": tutor, "other_tutor": other_tutor,
                "alice": alice, "bob": bob, "outsider": outsider, "parent": parent,
                "batch": batch, "session": batch_session, "second": second}

    ns = type("Env", (), dict(tag=tag, run=staticmethod(run), build=staticmethod(build)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"u": f"{tag}.%", "c": f"{tag}-%", "t": f"{tag}%"}
                b = "(SELECT id FROM batches WHERE batch_code LIKE :c)"
                sess = f"(SELECT id FROM batch_sessions WHERE batch_id IN {b})"
                await s.execute(text(f"DELETE FROM class_performance_marks WHERE session_id IN {sess}"), p)
                await s.execute(text(f"DELETE FROM transcripts WHERE batch_id IN {b}"), p)
                await s.execute(text("DELETE FROM assignment_submissions WHERE assignment_id IN (SELECT id FROM assignments WHERE title LIKE :t)"), p)
                await s.execute(text("DELETE FROM assignments WHERE title LIKE :t"), p)
                await s.execute(text(f"DELETE FROM attendances WHERE session_id IN {sess}"), p)
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
                # `audit_logs` is deliberately not cleaned: a database trigger
                # makes it append-only (the Phase 8 repudiation control), and
                # `actor_user_id` carries no FK, so the rows outlive the users.
                await s.execute(text("DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM users WHERE username LIKE :u"), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _entry(student: User, **scores: object) -> dict[str, object]:
    row: dict[str, object] = {
        "student_id": student.public_id,
        "participation": None, "interaction": None, "preparation": None,
        "practical": None, "presentation": None, "teamwork": None,
        "communication": None, "professionalism": None,
        "overall_score": None, "comment": None, "custom_scores": None,
    }
    row.update(scores)
    return row


# ------------------------------------------- the rule this file exists for ---


def test_class_performance_marks_make_a_transcript_completable(env) -> None:
    """§11's absence silently disabled §5.

    The scheme is assignments 50% / class performance 50%. The assignment is
    published at 80, so before any class-performance mark exists only half the
    scheme is assessed and there is no final result to certify. Recording and
    releasing the other half is what completes it -- which nothing in the
    product could do until this service existed.

    80 x 50% + (8/10 = 80%) x 50% = 80.
    """
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = ClassPerformanceService(s)
            transcripts = TranscriptService(s)

            before = await transcripts.generate(
                student_id=made["alice"].id, batch_id=made["batch"].id, actor=made["admin"]
            )
            await s.flush()
            incomplete = before.final_percentage

            await svc.save(
                made["session"].public_id,
                [_entry(made["alice"], overall_score=D("8"))],
                actor=made["tutor"],
            )
            await svc.set_state(
                made["session"].public_id, ResultState.PUBLISHED, actor=made["tutor"]
            )
            await s.flush()

            after = await transcripts.generate(
                student_id=made["alice"].id, batch_id=made["batch"].id,
                actor=made["admin"], reissue=True,
            )
            await s.flush()
            return incomplete, after.final_percentage, after.overall_grade, after.is_pass
        return go()

    incomplete, complete, grade, is_pass = env.run(f)
    assert incomplete is None, (
        "Half a scheme assessed should not produce a final result (§38)."
    )
    assert complete == D("80.00")
    assert grade == f"{env.tag[:2]}A"
    assert is_pass is True


# ------------------------------------------------- missing data is not zero ---


def test_a_blank_criterion_is_excluded_not_counted_as_zero(env) -> None:
    """§38, at the criterion level.

    A tutor who assessed participation 8/10 and nothing else has recorded 80%,
    not 8 out of a possible 80. Averaging seven blanks in as zeros would give
    10% and fail a student the tutor never assessed.
    """
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            rows = await ClassPerformanceService(s).save(
                made["session"].public_id,
                [_entry(made["alice"], participation=D("8"))],
                actor=made["tutor"],
            )
            await s.flush()
            return ClassPerformanceService.average(rows[0]), rows[0].max_score
        return go()

    average, ceiling = env.run(f)
    assert ceiling == D("10.00")
    assert average == D("8"), "A blank criterion was averaged in as a zero."


def test_the_tutors_own_figure_wins_over_the_criteria(env) -> None:
    """A tutor who writes an overall mark has made a judgement; averaging their
    criteria instead would silently overrule it."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            rows = await ClassPerformanceService(s).save(
                made["session"].public_id,
                [_entry(made["alice"], participation=D("2"), teamwork=D("2"),
                        overall_score=D("9"))],
                actor=made["tutor"],
            )
            await s.flush()
            return ClassPerformanceService.average(rows[0])
        return go()

    assert env.run(f) == D("9")


def test_a_student_with_nothing_assessed_has_no_figure_at_all(env) -> None:
    """Not zero. A row created and left blank must not contribute, or opening
    the sheet and saving it would fail the whole class."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = ClassPerformanceService(s)
            rows = await svc.save(
                made["session"].public_id, [_entry(made["alice"])], actor=made["tutor"]
            )
            await svc.set_state(
                made["session"].public_id, ResultState.PUBLISHED, actor=made["tutor"]
            )
            await s.flush()
            blank = ClassPerformanceService.average(rows[0])

            # And it reaches the engine as "unassessed", so the component is
            # excluded from the weighted total rather than dragging it to zero.
            result = await PerformanceService(s).for_transcript(
                student_id=made["alice"].id, batch_id=made["batch"].id
            )
            practical = [c for c in result.performance.components
                         if c.component_type is C.PRACTICAL]
            return blank, practical[0].counted, result.performance.final_percentage
        return go()

    blank, counted, final = env.run(f)
    assert blank is None
    assert counted is False
    assert final is None


# ----------------------------------------------------------- the lifecycle ---


def test_a_guardian_cannot_read_a_draft_mark(env) -> None:
    """§14, and the reason this lifecycle is not optional.

    A tutor's working note on how somebody's child participated in one class is
    not a result. The same marks, a different reader, a different answer.
    """
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = ClassPerformanceService(s)
            await svc.save(
                made["session"].public_id,
                [_entry(made["alice"], overall_score=D("8"), comment="Quiet today")],
                actor=made["tutor"],
            )
            await s.flush()

            as_guardian = await svc.for_student(
                student_public_id=made["alice"].public_id,
                batch_public_id=None, actor=made["parent"],
            )
            as_tutor = await svc.for_student(
                student_public_id=made["alice"].public_id,
                batch_public_id=None, actor=made["tutor"],
            )

            await svc.set_state(
                made["session"].public_id, ResultState.PUBLISHED, actor=made["tutor"]
            )
            await s.flush()
            after_release = await svc.for_student(
                student_public_id=made["alice"].public_id,
                batch_public_id=None, actor=made["parent"],
            )
            return len(as_guardian), len(as_tutor), len(after_release)
        return go()

    guardian_draft, tutor_draft, guardian_released = env.run(f)
    assert guardian_draft == 0, "A guardian read a tutor's draft class-performance note."
    assert tutor_draft == 1, "The tutor who wrote it cannot see it -- the filter is too broad."
    assert guardian_released == 1


def test_a_released_mark_is_not_silently_amended(env) -> None:
    """Somebody has already seen that figure, so changing it is deliberate.

    The refusal names the students it applies to, because a tutor saving a class
    of twenty needs to know which rows were refused rather than discovering them
    one failed save at a time.
    """
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = ClassPerformanceService(s)
            await svc.save(
                made["session"].public_id,
                [_entry(made["alice"], overall_score=D("8"))],
                actor=made["tutor"],
            )
            await svc.set_state(
                made["session"].public_id, ResultState.PUBLISHED, actor=made["tutor"]
            )
            await s.flush()

            with pytest.raises(ValidationError) as refused:
                await svc.save(
                    made["session"].public_id,
                    [_entry(made["alice"], overall_score=D("3"))],
                    actor=made["tutor"],
                )

            # Withdraw it, and the correction goes through.
            await svc.set_state(
                made["session"].public_id, ResultState.DRAFT, actor=made["tutor"]
            )
            await s.flush()
            corrected = await svc.save(
                made["session"].public_id,
                [_entry(made["alice"], overall_score=D("3"))],
                actor=made["tutor"],
            )
            await s.flush()
            return refused.value.details, corrected[0].overall_score
        return go()

    details, corrected = env.run(f)
    assert str(details).count("-") > 0, "The refusal did not name which students were locked."
    assert corrected == D("3.00")


def test_a_refused_save_leaves_the_other_rows_untouched(env) -> None:
    """The published-row check runs before anything is written.

    Refusing halfway would leave Bob's new mark saved and Alice's refused -- a
    tutor who has to work out which half of their sheet landed.
    """
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = ClassPerformanceService(s)
            await svc.save(
                made["session"].public_id,
                [_entry(made["alice"], overall_score=D("8"))],
                actor=made["tutor"],
            )
            await svc.set_state(
                made["session"].public_id, ResultState.PUBLISHED, actor=made["tutor"]
            )
            await s.flush()

            with pytest.raises(ValidationError):
                await svc.save(
                    made["session"].public_id,
                    [
                        _entry(made["alice"], overall_score=D("1")),
                        _entry(made["bob"], overall_score=D("7")),
                    ],
                    actor=made["tutor"],
                )
            s.expunge_all()
            rows = list(
                (
                    await s.execute(
                        select(ClassPerformanceMark).where(
                            ClassPerformanceMark.session_id == made["session"].id
                        )
                    )
                ).scalars().unique().all()
            )
            return len(rows), rows[0].overall_score
        return go()

    count, alice_score = env.run(f)
    assert count == 1, "A refused save still inserted a row for the unaffected student."
    assert alice_score == D("8.00")


# ------------------------------------------------------------- authority ---


def test_only_the_assigned_tutor_may_record(env) -> None:
    """A colleague who teaches the course but was not in the room cannot make a
    statement about what happened in it."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            with pytest.raises(AuthorizationError):
                await ClassPerformanceService(s).save(
                    made["session"].public_id,
                    [_entry(made["alice"], overall_score=D("9"))],
                    actor=made["other_tutor"],
                )
            return True
        return go()

    assert env.run(f)


def test_the_academic_office_may_record_and_it_is_recorded_as_such(env) -> None:
    """Without this the test above could be passing because nobody can record.

    An administrator holding `institution.view_all` may enter a mark, and
    `recorded_by` names them rather than the tutor -- which is why no separate
    override permission exists.
    """
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            rows = await ClassPerformanceService(s).save(
                made["session"].public_id,
                [_entry(made["alice"], overall_score=D("9"))],
                actor=made["admin"],
            )
            await s.flush()
            return rows[0].recorded_by == made["admin"].id
        return go()

    assert env.run(f) is True


def test_a_student_who_is_not_enrolled_is_refused(env) -> None:
    """The roster is the authority on who can be marked. A mark against somebody
    outside the batch would be invisible everywhere it mattered and would sit in
    the table for ever."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            with pytest.raises(ValidationError):
                await ClassPerformanceService(s).save(
                    made["session"].public_id,
                    [_entry(made["parent"], overall_score=D("9"))],
                    actor=made["tutor"],
                )
            return True
        return go()

    assert env.run(f)


def test_a_score_above_the_stated_maximum_is_refused(env) -> None:
    """15 out of 10 is a typo, and it would inflate a weighted result somebody
    later has to defend. The ceiling is per-row, so a CHECK constraint cannot
    see it."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            with pytest.raises(ValidationError) as refused:
                await ClassPerformanceService(s).save(
                    made["session"].public_id,
                    [_entry(made["alice"], participation=D("15"))],
                    actor=made["tutor"],
                )
            return str(refused.value)
        return go()

    assert "between 0 and 10" in env.run(f)


def test_a_higher_maximum_admits_a_higher_score(env) -> None:
    """Without this the test above could be passing because of a hard-coded 10.
    A tutor marking practical work out of 20 is doing something ordinary."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            rows = await ClassPerformanceService(s).save(
                made["session"].public_id,
                [_entry(made["alice"], participation=D("15"))],
                actor=made["tutor"],
                max_score=D("20"),
            )
            await s.flush()
            return rows[0].max_score, rows[0].participation
        return go()

    assert env.run(f) == (D("20.00"), D("15.00"))


def test_re_saving_corrects_rather_than_duplicating(env) -> None:
    """Two rows for one student would double their class-performance
    contribution, which is the failure the unique constraint exists to
    prevent -- and a tutor fixing a typo expects a correction."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = ClassPerformanceService(s)
            await svc.save(made["session"].public_id,
                           [_entry(made["alice"], overall_score=D("4"))],
                           actor=made["tutor"])
            await s.flush()
            await svc.save(made["session"].public_id,
                           [_entry(made["alice"], overall_score=D("7"))],
                           actor=made["tutor"])
            await s.flush()
            rows = list(
                (
                    await s.execute(
                        select(ClassPerformanceMark).where(
                            ClassPerformanceMark.session_id == made["session"].id
                        )
                    )
                ).scalars().unique().all()
            )
            return len(rows), rows[0].overall_score, rows[0].updated_by == made["tutor"].id
        return go()

    assert env.run(f) == (1, D("7.00"), True)


def test_a_mark_entered_in_error_is_deleted_not_zeroed(env) -> None:
    """Zero is itself a mark: it would be averaged into the student's figure and
    pull it down. Removing the row is the only correction that does not invent a
    result."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = ClassPerformanceService(s)
            rows = await svc.save(made["session"].public_id,
                                  [_entry(made["bob"], overall_score=D("5"))],
                                  actor=made["tutor"])
            await s.flush()
            await svc.delete(rows[0].public_id, actor=made["tutor"])
            await s.flush()
            remaining = list(
                (
                    await s.execute(
                        select(ClassPerformanceMark).where(
                            ClassPerformanceMark.session_id == made["session"].id
                        )
                    )
                ).scalars().unique().all()
            )
            return len(remaining)
        return go()

    assert env.run(f) == 0


def test_a_session_the_caller_cannot_see_is_reported_as_absent(env) -> None:
    """Not forbidden. A session somebody has no access to must not be provable
    to exist -- confirming it would leak the timetable of a batch they are not
    part of.

    The caller is a student enrolled in nothing. Using Bob here -- who *is*
    enrolled in this batch -- would have passed with the scope check removed
    entirely, since he can legitimately see the session either way.
    """
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            with pytest.raises(NotFoundError):
                await ClassPerformanceService(s).sheet(
                    made["session"].public_id, actor=made["outsider"]
                )
            return True
        return go()

    assert env.run(f)


def test_the_sheet_lists_every_enrolled_student_even_unmarked_ones(env) -> None:
    """The roster comes from enrollments, not from who has been assessed -- a
    grid a tutor cannot see the unmarked names in is a grid they cannot fill
    in. And an unmarked student carries `mark=None`, never a zero."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = ClassPerformanceService(s)
            await svc.save(made["session"].public_id,
                           [_entry(made["alice"], overall_score=D("6"))],
                           actor=made["tutor"])
            await s.flush()
            _bs, roster, marks, can_edit = await svc.sheet(
                made["session"].public_id, actor=made["tutor"]
            )
            return len(roster), len(marks), can_edit
        return go()

    assert env.run(f) == (2, 1, True)

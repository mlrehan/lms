"""A marked result reaches the grade book on its own (spec §9, §47).

§47 describes the flow as "Tutor publishes result -> result automatically
enters Gradebook -> Student Performance automatically recalculates". The
first arrow did not exist: `sync_batch` was the only writer and a person had
to press it, so between marking and the next sweep the grade book disagreed
with the marks it was derived from, and nothing said so.

What the tests below pin is not just "a row appears" but the three things
that make the automatic and manual paths safe to run side by side:

* the automatic write produces the row the sweep would have produced, so a
  later sweep reports it *unchanged* rather than rewriting it;
* an attempt still awaiting a human stays out, because a score of `None` is
  not a score of zero;
* a grade-book failure cannot undo a mark.

All three marking paths are covered -- quizzes, coursework and exams -- because
they were wired one at a time and the tests for the first two would have gone
on passing with the third missing.
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
from backend.models.assignment import Assignment, AssignmentSubmission
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.exam import Exam, ExamResult
from backend.models.gradebook import GradeBookEntry
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.quiz import Question, QuestionOption, Quiz, QuizAttempt
from backend.schemas.assignment import GradeSubmissionRequest
from backend.schemas.exam import ExamResultEntry
from backend.schemas.quiz import AnswerInput
from backend.services.assignment_service import AssignmentService
from backend.services.exam_service import ExamService
from backend.services.quiz_service import QuizService
from backend.utils.enums import (
    AssessmentScope,
    CourseStatus,
    EnrollmentStatus,
    ExamType,
    GradeComponentType,
    Platforms,
    QuestionType,
    SubmissionState,
    SubmissionType,
    UserStatus,
)


@pytest.fixture()
def env():
    tag = f"gs{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="gradebook-autosync-tests")
    world: dict = {}
    now = datetime.now(timezone.utc)

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}
        student = User(
            username=f"{tag}.student", slug=f"{tag}-student", email=f"{tag}.student@t.test",
            hashed_password="x", status=UserStatus.ACTIVE, roles=[roles["STUDENT"]],
        )
        tutor = User(
            username=f"{tag}.tutor", slug=f"{tag}-tutor", email=f"{tag}.tutor@t.test",
            hashed_password="x", status=UserStatus.ACTIVE, roles=[roles["TUTOR"]],
        )
        # A classmate who sat nothing. `record_results` rewrites the whole
        # mark sheet, so their empty row is handed to the grade-book hook on
        # every save -- which is where "ungraded is absent, not zero" has to
        # hold.
        peer = User(
            username=f"{tag}.peer", slug=f"{tag}-peer", email=f"{tag}.peer@t.test",
            hashed_password="x", status=UserStatus.ACTIVE, roles=[roles["STUDENT"]],
        )
        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([student, tutor, peer, course])
        await s.flush()

        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=60), is_active=True, capacity=20)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        s.add(batch)
        await s.flush()
        # A second active cohort of the same course, which the student is
        # also in. Without it, "use the quiz's own batch" and "look up every
        # batch the student is in" give the same answer and the test cannot
        # tell them apart.
        second = Batch(batch_code=f"{tag}-B", course_id=course.id, start_date=date.today(),
                       end_date=date.today() + timedelta(days=60), is_active=True, capacity=20)
        second.sessions, second.enrollments, second.student_reviews = [], [], []
        s.add(second)
        await s.flush()
        for target in (batch, second):
            s.add(Enrollments(batch_id=target.id, student_id=student.id,
                              enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
        s.add(Enrollments(batch_id=batch.id, student_id=peer.id,
                          enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
        # Tutors are set per session of a batch, and that is the only thing
        # that puts this cohort -- and so this coursework -- in their scope.
        session_row = BatchSession(
            batch_id=batch.id, tutor_id=tutor.id,
            session_start_time=now + timedelta(days=1),
            session_end_time=now + timedelta(days=1, hours=1),
            duration_minutes=60, platform=Platforms.Zoom,
        )
        session_row.attendances = []
        s.add(session_row)

        def make_quiz(name: str) -> Quiz:
            return Quiz(
                course_id=course.id, batch_id=batch.id, scope=AssessmentScope.BATCH,
                title=f"{tag} {name}", passing_score=Decimal("50.00"), is_published=True,
                attempts_allowed=5, weight=Decimal("1.00"),
            )

        auto, mixed = make_quiz("auto"), make_quiz("mixed")
        s.add_all([auto, mixed])
        await s.flush()

        def mcq(quiz: Quiz, text_: str) -> Question:
            return Question(quiz_id=quiz.id, question_text=text_,
                            question_type=QuestionType.MCQ_SINGLE,
                            points=Decimal("1.00"), order=0)

        right, also_right = mcq(auto, "Auto Q"), mcq(mixed, "Mixed Q")
        essay = Question(quiz_id=mixed.id, question_text="Explain",
                         question_type=QuestionType.ESSAY, points=Decimal("1.00"), order=1)
        s.add_all([right, also_right, essay])
        await s.flush()

        options: dict[int, list[QuestionOption]] = {}
        for q in (right, also_right):
            rows = [
                QuestionOption(question_id=q.id, option_text="correct", is_correct=True, order=0),
                QuestionOption(question_id=q.id, option_text="wrong", is_correct=False, order=1),
            ]
            s.add_all(rows)
            options[q.id] = rows
        await s.flush()

        # Coursework and an exam, both set for the first cohort, so the
        # three marking paths can be driven through their real services.
        assignment = Assignment(
            course_id=course.id, batch_id=batch.id, scope=AssessmentScope.BATCH,
            title=f"{tag} Coursework", due_date=now + timedelta(days=7),
            max_score=Decimal("40.00"), submission_type=SubmissionType.TEXT,
        )
        exam = Exam(
            course_id=course.id, batch_id=batch.id, scope=AssessmentScope.BATCH,
            title=f"{tag} Final", scheduled_at=now + timedelta(days=14),
            total_marks=Decimal("80.00"), passing_marks=Decimal("40.00"),
            exam_type=ExamType.FINAL, is_published=True,
        )
        s.add_all([assignment, exam])
        await s.flush()

        submission = AssignmentSubmission(
            assignment_id=assignment.id, student_id=student.id,
            submitted_at=now, content="Submitted for marking.",
            state=SubmissionState.SUBMITTED,
        )
        s.add(submission)
        # Recorded as a candidate, no mark entered.
        s.add(ExamResult(exam_id=exam.id, student_id=peer.id, is_published=False))
        await s.flush()

        world.update(
            tutor=tutor.id, student_public=student.public_id, peer=peer.id,
            assignment_pk=assignment.id, submission=submission.public_id,
            submission_pk=submission.id,
            exam=exam.public_id, exam_pk=exam.id,
        )
        world.update(
            student=student.id, course_pk=course.id, batch_pk=batch.id,
            auto=auto.public_id, mixed=mixed.public_id,
            auto_pk=auto.id, mixed_pk=mixed.id,
            auto_q=right.public_id, mixed_q=also_right.public_id, essay_q=essay.public_id,
            second_pk=second.id,
            auto_correct=options[right.id][0].id,
            mixed_correct=options[also_right.id][0].id,
            course_title=course.title,
        )

    run(build)

    def sit(quiz_public_id, *, question_public_id, option_id, text_answer=None, essay_public_id=None):  # noqa: ANN001, ANN202
        """Start and submit an attempt as the student, through the real service."""
        async def go(s):  # noqa: ANN001, ANN202
            student = await s.get(User, world["student"])
            service = QuizService(s)
            attempt = await service.start_attempt(quiz_public_id, actor=student)
            answers = [AnswerInput(question_id=question_public_id, selected_option_ids=[option_id])]
            if essay_public_id is not None:
                answers.append(AnswerInput(question_id=essay_public_id, text_answer=text_answer))
            return await service.submit_attempt(attempt.public_id, answers, actor=student)
        return run(go)

    def entries(component: GradeComponentType = GradeComponentType.QUIZ) -> list[GradeBookEntry]:
        async def go(s):  # noqa: ANN001, ANN202
            rows = await s.execute(
                select(GradeBookEntry).where(
                    GradeBookEntry.student_id == world["student"],
                    GradeBookEntry.component_type == component,
                )
            )
            return list(rows.scalars())
        return run(go)

    def mark_coursework(grade: str = "32.00"):  # noqa: ANN202
        """Mark the submission as the tutor, through the real service."""
        async def go(s):  # noqa: ANN001, ANN202
            tutor = await s.get(User, world["tutor"])
            return await AssignmentService(s).grade(
                world["submission"],
                GradeSubmissionRequest(grade=Decimal(grade)),
                actor=tutor,
            )
        return run(go)

    def mark_exam(marks: str = "64.00"):  # noqa: ANN202
        async def go(s):  # noqa: ANN001, ANN202
            tutor = await s.get(User, world["tutor"])
            entry = ExamResultEntry(
                student_id=world["student_public"], marks_obtained=Decimal(marks)
            )
            return await ExamService(s).record_results(
                world["exam"], [entry], actor=tutor
            )
        return run(go)

    ns = type("Env", (), dict(
        tag=tag, world=world, run=staticmethod(run),
        sit=staticmethod(sit), entries=staticmethod(entries),
        mark_coursework=staticmethod(mark_coursework),
        mark_exam=staticmethod(mark_exam),
    ))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                for stmt in (
                    "DELETE FROM gradebook_entries WHERE student_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM exam_results WHERE exam_id IN (SELECT id FROM exams WHERE title LIKE :t)",
                    "DELETE FROM exams WHERE title LIKE :t",
                    "DELETE FROM assignment_submissions WHERE assignment_id IN (SELECT id FROM assignments WHERE title LIKE :t)",
                    "DELETE FROM assignments WHERE title LIKE :t",
                    "DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM quiz_answers WHERE attempt_id IN (SELECT id FROM quiz_attempts WHERE student_id IN (SELECT id FROM users WHERE username LIKE :u))",
                    "DELETE FROM quiz_attempts WHERE student_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM question_options WHERE question_id IN (SELECT id FROM questions WHERE quiz_id IN (SELECT id FROM quizzes WHERE title LIKE :t))",
                    "DELETE FROM questions WHERE quiz_id IN (SELECT id FROM quizzes WHERE title LIKE :t)",
                    "DELETE FROM quizzes WHERE title LIKE :t",
                    "DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM batches WHERE batch_code LIKE :c",
                    "DELETE FROM tutor_courses WHERE course_id IN (SELECT id FROM courses WHERE title LIKE :t)",
                    "DELETE FROM courses WHERE title LIKE :t",
                    "DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM users WHERE username LIKE :u",
                ):
                    await s.execute(text(stmt), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def test_an_auto_graded_quiz_reaches_the_grade_book_with_nobody_pressing_sync(env) -> None:
    attempt = env.sit(
        env.world["auto"],
        question_public_id=env.world["auto_q"],
        option_id=env.world["auto_correct"],
    )
    assert attempt.score == Decimal("100.00")

    rows = env.entries()
    assert len(rows) == 1
    # A percentage out of 100, matching what `_sync_quizzes` writes -- if the
    # two disagreed, the next sweep would rewrite every row this path created.
    assert Decimal(str(rows[0].score)) == Decimal("100.00")
    assert Decimal(str(rows[0].max_score)) == Decimal("100")
    assert rows[0].batch_id == env.world["batch_pk"]


def test_an_attempt_awaiting_a_person_stays_out_of_the_grade_book(env) -> None:
    attempt = env.sit(
        env.world["mixed"],
        question_public_id=env.world["mixed_q"],
        option_id=env.world["mixed_correct"],
        essay_public_id=env.world["essay_q"],
        text_answer="Because it groups rows.",
    )

    # The essay is unmarked, so the attempt has no score at all -- and an
    # entry here would be the understated mark §38 forbids.
    assert attempt.score is None
    assert env.entries() == []


def test_the_sweep_finds_the_automatic_row_unchanged(env) -> None:
    env.sit(
        env.world["auto"],
        question_public_id=env.world["auto_q"],
        option_id=env.world["auto_correct"],
    )

    async def sweep(s):  # noqa: ANN001, ANN202
        from backend.models.identity.role import Role as _Role  # noqa: F401
        from backend.services.gradebook_service import GradeBookService
        batch = await s.get(Batch, env.world["batch_pk"])
        service = GradeBookService(s)
        students = await service._enrolled_student_ids(batch.id)
        stats = {"created": 0, "updated": 0, "unchanged": 0, "skipped_ungraded": 0}
        await service._sync_quizzes(batch, students, stats)
        return stats

    stats = env.run(sweep)

    # The point of writing the *same* row: the manual reconciler agrees with
    # the automatic writer instead of overwriting it on every run.
    assert stats["unchanged"] == 1
    assert stats["created"] == 0
    assert stats["updated"] == 0
    assert len(env.entries()) == 1


def test_a_grade_book_failure_does_not_undo_the_mark(env, monkeypatch) -> None:
    from backend.services.gradebook_service import GradeBookService

    async def explode(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("grade book unavailable")

    monkeypatch.setattr(GradeBookService, "record_component", explode)

    attempt = env.sit(
        env.world["auto"],
        question_public_id=env.world["auto_q"],
        option_id=env.world["auto_correct"],
    )

    # The student sat the quiz and it was marked. Losing a derived row must
    # not discard that -- `sync_batch` is what repairs it.
    assert attempt.score == Decimal("100.00")
    assert env.entries() == []


def test_a_batch_scoped_quiz_lands_only_in_its_own_batch(env) -> None:
    """The student is in two cohorts of this course; the quiz is set for one.

    Falling back to "every batch they are enrolled in" would put the mark in
    a cohort the quiz was never set for, and double it in the course's
    aggregate.
    """
    env.sit(
        env.world["auto"],
        question_public_id=env.world["auto_q"],
        option_id=env.world["auto_correct"],
    )

    rows = env.entries()
    assert len(rows) == 1
    assert rows[0].batch_id == env.world["batch_pk"]
    assert rows[0].batch_id != env.world["second_pk"]


def test_marked_coursework_reaches_the_grade_book_without_a_sweep(env) -> None:
    """The assignment path (§47), wired after quizzes.

    Out of the assignment's own `max_score`, not rescaled to 100 -- which is
    what `_sync_assignments` writes, and the two must agree or each would
    rewrite the other's rows.
    """
    submission = env.mark_coursework("32.00")
    assert Decimal(str(submission.grade)) == Decimal("32.00")

    rows = env.entries(GradeComponentType.ASSIGNMENT)
    assert len(rows) == 1
    assert Decimal(str(rows[0].score)) == Decimal("32.00")
    assert Decimal(str(rows[0].max_score)) == Decimal("40.00")
    assert rows[0].batch_id == env.world["batch_pk"]
    assert rows[0].reference_id == env.world["submission_pk"]


def test_a_recorded_exam_mark_reaches_the_grade_book_without_a_sweep(env) -> None:
    """The exam path (§47), the last of the three.

    Recorded, not published: `_sync_exams` writes every result that has a
    mark, so withholding it here until publication would mean the next sweep
    introduced rows this path had declined to write.
    """
    env.mark_exam("64.00")

    rows = env.entries(GradeComponentType.FINAL_EXAM)
    assert len(rows) == 1
    assert Decimal(str(rows[0].score)) == Decimal("64.00")
    assert Decimal(str(rows[0].max_score)) == Decimal("80.00")
    assert rows[0].batch_id == env.world["batch_pk"]


def test_remarking_moves_the_grade_book_row_rather_than_adding_one(env) -> None:
    """A corrected mark must not leave the old one behind.

    Both marks are for the same submission, so they are the same grade-book
    row -- an insert-only hook would double the component and halve the
    student's average on it.
    """
    env.mark_coursework("32.00")
    env.run(lambda s: _regrade(s, env))

    rows = env.entries(GradeComponentType.ASSIGNMENT)
    assert len(rows) == 1
    assert Decimal(str(rows[0].score)) == Decimal("36.00")


async def _regrade(s, env):  # noqa: ANN001, ANN202
    """Re-mark through the service, with the reason §24 requires."""
    from backend.schemas.assignment import GradeSubmissionRequest as _Req
    tutor = await s.get(User, env.world["tutor"])
    return await AssignmentService(s).grade(
        env.world["submission"],
        _Req(grade=Decimal("36.00"), override_reason="Arithmetic error on question 3."),
        actor=tutor,
    )


def test_the_sweep_finds_the_coursework_and_exam_rows_unchanged(env) -> None:
    """The property that makes the automatic and manual writers safe together.

    Driven over all four component sweeps rather than `_sync_assignments`
    alone: `sync_batch` is what an operator actually presses, and a hook that
    agreed with one sweep while another rewrote its rows would still drift.
    """
    env.sit(
        env.world["auto"],
        question_public_id=env.world["auto_q"],
        option_id=env.world["auto_correct"],
    )
    env.mark_coursework("32.00")
    env.mark_exam("64.00")

    async def sweep(s):  # noqa: ANN001, ANN202
        from backend.services.gradebook_service import GradeBookService
        batch = await s.get(Batch, env.world["batch_pk"])
        service = GradeBookService(s)
        students = await service._enrolled_student_ids(batch.id)
        stats = {"created": 0, "updated": 0, "unchanged": 0, "skipped_ungraded": 0}
        await service._sync_assignments(batch, students, stats)
        await service._sync_quizzes(batch, students, stats)
        await service._sync_exams(batch, students, stats)
        return stats

    stats = env.run(sweep)

    # Three marks, three rows already present, nothing to do.
    assert stats["unchanged"] == 3
    assert stats["created"] == 0
    assert stats["updated"] == 0


def test_a_grade_book_failure_does_not_undo_a_coursework_mark(env, monkeypatch) -> None:
    from backend.services.gradebook_service import GradeBookService

    async def explode(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("grade book unavailable")

    monkeypatch.setattr(GradeBookService, "record_component", explode)

    submission = env.mark_coursework("32.00")

    # The tutor marked the work and said so to the student. A derived row
    # that could not be written must not take the mark with it.
    assert Decimal(str(submission.grade)) == Decimal("32.00")
    assert env.entries(GradeComponentType.ASSIGNMENT) == []


def test_a_grade_book_failure_does_not_undo_an_exam_mark(env, monkeypatch) -> None:
    from backend.services.gradebook_service import GradeBookService

    async def explode(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("grade book unavailable")

    monkeypatch.setattr(GradeBookService, "record_component", explode)

    results = env.mark_exam("64.00")

    marked = [r for r in results if r.student_id == env.world["student"]]
    assert [Decimal(str(r.marks_obtained)) for r in marked] == [Decimal("64.00")]
    assert env.entries(GradeComponentType.FINAL_EXAM) == []


def test_a_candidate_with_no_mark_stays_out_of_the_grade_book(env, caplog) -> None:
    """§38: unmarked is absent, not zero -- and not an error either.

    `record_results` rewrites the whole mark sheet, so saving one student's
    mark hands every other candidate's row to the hook as well. A zero for a
    classmate nobody has marked would drag their average down for work that
    has not been looked at.

    The log is asserted because that is what the guard is actually buying.
    Without it the hook reaches `Decimal(str(None))`, which raises and is
    swallowed by the fail-open handler -- so no wrong row appears either way,
    and a test checking only the rows would pass against an implementation
    that logs a marking failure for every unmarked candidate on every save.
    An operator reading that log chases an incident that is not one.
    """
    with caplog.at_level("ERROR", logger="backend.services.exam_service"):
        env.mark_exam("64.00")

    async def peer_rows(s):  # noqa: ANN001, ANN202
        rows = await s.execute(
            select(GradeBookEntry).where(GradeBookEntry.student_id == env.world["peer"])
        )
        return list(rows.scalars())

    assert env.run(peer_rows) == []
    assert "Failed to record exam result" not in caplog.text
    # The marked student still landed, so the assertions above are not passing
    # because the hook stopped working altogether.
    assert len(env.entries(GradeComponentType.FINAL_EXAM)) == 1

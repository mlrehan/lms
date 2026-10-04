"""A marked quiz reaches the grade book on its own (spec §9, §47).

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
from backend.models.batch import Batch
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.gradebook import GradeBookEntry
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.quiz import Question, QuestionOption, Quiz, QuizAttempt
from backend.schemas.quiz import AnswerInput
from backend.services.quiz_service import QuizService
from backend.utils.enums import (
    AssessmentScope,
    CourseStatus,
    EnrollmentStatus,
    GradeComponentType,
    QuestionType,
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
        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([student, course])
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

    ns = type("Env", (), dict(
        tag=tag, world=world, run=staticmethod(run),
        sit=staticmethod(sit), entries=staticmethod(entries),
    ))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                for stmt in (
                    "DELETE FROM gradebook_entries WHERE student_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM quiz_answers WHERE attempt_id IN (SELECT id FROM quiz_attempts WHERE student_id IN (SELECT id FROM users WHERE username LIKE :u))",
                    "DELETE FROM quiz_attempts WHERE student_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM question_options WHERE question_id IN (SELECT id FROM questions WHERE quiz_id IN (SELECT id FROM quizzes WHERE title LIKE :t))",
                    "DELETE FROM questions WHERE quiz_id IN (SELECT id FROM quizzes WHERE title LIKE :t)",
                    "DELETE FROM quizzes WHERE title LIKE :t",
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

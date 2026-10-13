"""The quiz settings that were stored and read by nothing (spec §9).

Five columns were written at creation and never looked at again:
`questions_per_attempt`, `auto_submit_on_expiry`, `show_result_immediately`,
`show_correct_answers` and `show_explanations`. The console offered switches
for them. A switch that does nothing is worse than an absent one -- somebody
sets it and believes the paper is a random draw, or that marks are withheld
until they release them, and neither was true.

Each test below pins the thing that makes the setting *real* rather than
merely present:

* a drawn paper is marked out of the questions it drew, not out of the bank
  (the failure that would have halved every score);
* an expired attempt is closed, so it stops blocking the attempts the
  student is still entitled to;
* a withheld mark is withheld from the student **and** their care circle, and
  withholding the total while listing every per-question mark beside it is
  not withholding anything.
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
from backend.core.errors import AuthorizationError, ConflictError, ValidationError
from backend.db.manager import DatabaseManager
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.quiz import Question, QuestionOption, Quiz, QuizAttempt
from backend.schemas.quiz import AnswerInput
from backend.services.quiz_service import QuizService
from backend.utils.enums import (
    AssessmentScope,
    CourseStatus,
    EnrollmentStatus,
    Platforms,
    QuestionType,
    UserStatus,
)

# A bank of twenty rather than ten, drawing four. Two students drawing the
# same four from ten is a 1-in-210 coincidence, which is often enough to
# fail a suite that runs repeatedly -- it happened twice during mutation
# testing. From twenty it is 1 in 4,845.
BANK = 20
DRAW = 4


@pytest.fixture()
def env():
    tag = f"qc{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="quiz-settings-tests")
    world: dict = {}
    now = datetime.now(timezone.utc)

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

        def user(name: str, role: str) -> User:
            return User(
                username=f"{tag}.{name}", slug=f"{tag}-{name}",
                email=f"{tag}.{name}@t.test", hashed_password="x",
                status=UserStatus.ACTIVE, roles=[roles[role]],
            )

        alice, bob, tutor = user("alice", "STUDENT"), user("bob", "STUDENT"), user("tutor", "TUTOR")
        guardian = user("guardian", "GUARDIAN")
        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([alice, bob, tutor, guardian, course])
        await s.flush()

        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=60), is_active=True, capacity=20)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        s.add(batch)
        await s.flush()
        for u in (alice, bob):
            s.add(Enrollments(batch_id=batch.id, student_id=u.id,
                              enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
        # Tutors are set per session of a batch, and that is the only route
        # that puts this cohort's work in their scope -- being tutor of record
        # for the course grants nothing (see test_tutor_batch_scope).
        session_row = BatchSession(
            batch_id=batch.id, tutor_id=tutor.id,
            session_start_time=now + timedelta(days=1),
            session_end_time=now + timedelta(days=1, hours=1),
            duration_minutes=60, platform=Platforms.Zoom,
        )
        session_row.attendances = []
        s.add(session_row)
        # The guardian is linked to Alice, so "withheld from the student"
        # can be checked against the other half of the audience §14 releases
        # to. Releasing to one and not the other is a leak in one direction
        # and a bug in the other.
        await s.execute(
            text("INSERT INTO student_guardians "
                 "(student_id, guardian_id, relationship_type, public_id, created_at) "
                 "VALUES (:s, :g, 'Parent', gen_random_uuid(), now())"),
            {"s": alice.id, "g": guardian.id},
        )

        def quiz(name: str, **kwargs) -> Quiz:
            row = Quiz(
                course_id=course.id, batch_id=batch.id, scope=AssessmentScope.BATCH,
                title=f"{tag} {name}", passing_score=Decimal("50.00"), is_published=True,
                attempts_allowed=5, weight=Decimal("1.00"),
            )
            for field, value in kwargs.items():
                setattr(row, field, value)
            return row

        # `shuffle_questions` is explicitly off, and that is load-bearing:
        # `bool_column()` defaults to **true**, so a quiz built without it
        # shuffles its display order -- and the first version of the test
        # below passed against an implementation that drew the front of the
        # bank every time, because the display shuffle scrambled the result
        # anyway. With it off, the draw is the only thing that can.
        pool = quiz("pool", questions_per_attempt=DRAW, shuffle_questions=False)
        timed = quiz("timed", duration_minutes=10, auto_submit_on_expiry=True)
        advisory = quiz("advisory", duration_minutes=10, auto_submit_on_expiry=False)
        withheld = quiz(
            "withheld",
            show_result_immediately=False,
            show_correct_answers=True,
            show_explanations=True,
        )
        plain = quiz("plain")
        typed = quiz("typed")
        s.add_all([pool, timed, advisory, withheld, plain, typed])
        await s.flush()

        correct: dict[int, int] = {}

        def mcq(q: Quiz, index: int, *, explanation: str | None = None) -> Question:
            row = Question(
                quiz_id=q.id, question_text=f"Q{index}",
                question_type=QuestionType.MCQ_SINGLE,
                points=Decimal("1.00"), order=index, explanation=explanation,
            )
            return row

        async def with_options(q: Question) -> None:
            s.add(q)
            await s.flush()
            right = QuestionOption(question_id=q.id, option_text=f"right-{q.order}",
                                   is_correct=True, order=0)
            wrong = QuestionOption(question_id=q.id, option_text=f"wrong-{q.order}",
                                   is_correct=False, order=1)
            s.add_all([right, wrong])
            await s.flush()
            correct[q.id] = right.id

        for index in range(BANK):
            await with_options(mcq(pool, index))
        for target in (timed, advisory, plain):
            await with_options(mcq(target, 0))
        await with_options(mcq(withheld, 0, explanation="Because the first option is right."))

        # One of each of the four new types (spec §9), on their own quiz.
        blank = Question(quiz_id=typed.id, question_text="Capital of France?",
                         question_type=QuestionType.FILL_BLANK, points=Decimal("1.00"),
                         order=0, settings={"accepted": ["Paris"]})
        numeric = Question(quiz_id=typed.id, question_text="Pi to 2dp?",
                           question_type=QuestionType.NUMERIC, points=Decimal("1.00"),
                           order=1, settings={"answer": "3.14", "tolerance": "0.01"})
        ordering = Question(quiz_id=typed.id, question_text="Order these",
                            question_type=QuestionType.ORDERING, points=Decimal("1.00"),
                            order=2)
        matching = Question(quiz_id=typed.id, question_text="Match these",
                            question_type=QuestionType.MATCHING, points=Decimal("1.00"),
                            order=3)
        s.add_all([blank, numeric, ordering, matching])
        await s.flush()
        order_ids = []
        for position, label in enumerate(("first", "second", "third")):
            opt = QuestionOption(question_id=ordering.id, option_text=label,
                                 is_correct=False, order=position)
            s.add(opt)
            await s.flush()
            order_ids.append(opt.id)
        match_ids = {}
        for position, (left, right_text) in enumerate(
            (("France", "Paris"), ("Japan", "Tokyo"), ("Peru", "Lima"))
        ):
            opt = QuestionOption(question_id=matching.id, option_text=left,
                                 is_correct=False, order=position, match_text=right_text)
            s.add(opt)
            await s.flush()
            match_ids[left] = opt.id
        await s.flush()

        world.update(
            alice=alice.id, bob=bob.id, tutor=tutor.id, guardian=guardian.id,
            correct=correct,
            pool=pool.public_id, pool_pk=pool.id,
            timed=timed.public_id, timed_pk=timed.id,
            advisory=advisory.public_id, advisory_pk=advisory.id,
            withheld=withheld.public_id, withheld_pk=withheld.id,
            plain=plain.public_id, plain_pk=plain.id,
            typed=typed.public_id, typed_pk=typed.id,
            blank=blank.public_id, numeric=numeric.public_id,
            ordering=ordering.public_id, matching=matching.public_id,
            order_ids=order_ids, match_ids=match_ids,
        )

    run(build)

    def start(quiz_public_id, who: str = "alice"):  # noqa: ANN202
        async def go(s):  # noqa: ANN001, ANN202
            student = await s.get(User, world[who])
            return await QuizService(s).start_attempt(quiz_public_id, actor=student)
        return run(go)

    def paper(quiz_public_id, who: str = "alice"):  # noqa: ANN202
        async def go(s):  # noqa: ANN001, ANN202
            student = await s.get(User, world[who])
            rows = await QuizService(s).questions_for_attempt(quiz_public_id, actor=student)
            return [(q.question_text, [o.id for o in opts]) for q, opts in rows]
        return run(go)

    def submit(attempt_public_id, answers, who: str = "alice"):  # noqa: ANN001, ANN202
        async def go(s):  # noqa: ANN001, ANN202
            student = await s.get(User, world[who])
            return await QuizService(s).submit_attempt(attempt_public_id, answers, actor=student)
        return run(go)

    def backdate(attempt_public_id, minutes: int) -> None:
        """Move an attempt's start into the past, so its timer has expired."""
        async def go(s):  # noqa: ANN001, ANN202
            await s.execute(
                text("UPDATE quiz_attempts SET started_at = started_at - make_interval(mins => :m) "
                     "WHERE public_id = :p"),
                {"m": minutes, "p": str(attempt_public_id)},
            )
        run(go)

    ns = type("Env", (), dict(
        tag=tag, world=world, run=staticmethod(run), start=staticmethod(start),
        paper=staticmethod(paper), submit=staticmethod(submit),
        backdate=staticmethod(backdate),
    ))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                for stmt in (
                    "DELETE FROM notifications WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM gradebook_entries WHERE student_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM quiz_answers WHERE attempt_id IN (SELECT id FROM quiz_attempts WHERE student_id IN (SELECT id FROM users WHERE username LIKE :u))",
                    "DELETE FROM quiz_attempts WHERE student_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM question_options WHERE question_id IN (SELECT id FROM questions WHERE quiz_id IN (SELECT id FROM quizzes WHERE title LIKE :t))",
                    "DELETE FROM questions WHERE quiz_id IN (SELECT id FROM quizzes WHERE title LIKE :t)",
                    "DELETE FROM quizzes WHERE title LIKE :t",
                    "DELETE FROM student_guardians WHERE student_id IN (SELECT id FROM users WHERE username LIKE :u) OR guardian_id IN (SELECT id FROM users WHERE username LIKE :u)",
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


# =============================================================================
# questions_per_attempt
# =============================================================================


def test_a_pool_serves_only_as_many_questions_as_it_draws(env) -> None:
    env.start(env.world["pool"])
    served = env.paper(env.world["pool"])

    assert len(served) == DRAW
    # Not the first four in authored order: taking the front of the bank
    # would hand every student the same subset, and a pool nobody draws
    # differently from is not a pool. (This quiz does not shuffle its
    # display order, so the draw is the only thing that can have moved
    # them, and drawing exactly Q0-Q3 is a 1-in-210 coincidence.)
    assert [t for t, _ in served] != [f"Q{i}" for i in range(DRAW)]


def test_two_students_draw_different_questions(env) -> None:
    env.start(env.world["pool"], "alice")
    env.start(env.world["pool"], "bob")

    assert {t for t, _ in env.paper(env.world["pool"], "alice")} != {
        t for t, _ in env.paper(env.world["pool"], "bob")
    }


def test_the_same_attempt_draws_the_same_questions_back(env) -> None:
    env.start(env.world["pool"])

    # The property a draw made at request time fails. A student who reloads
    # mid-quiz must not be handed a different paper, or every answer they
    # have already chosen is silently remapped.
    assert env.paper(env.world["pool"]) == env.paper(env.world["pool"])


def test_a_drawn_paper_is_marked_out_of_what_it_drew(env) -> None:
    """The defect that made this setting unusable rather than merely inert.

    Submission graded every question in the bank, so a student who answered
    all four of their four questions correctly scored four marks out of ten.
    """
    attempt = env.start(env.world["pool"])
    served = env.paper(env.world["pool"])
    answers = [
        AnswerInput(
            question_id=q_id,
            selected_option_ids=[env.world["correct"][q_pk]],
        )
        for q_id, q_pk in _pool_ids(env, served)
    ]

    done = env.submit(attempt.public_id, answers)

    assert done.score == Decimal("100.00")
    assert len(done.answers) == DRAW


def _pool_ids(env, served):  # noqa: ANN001, ANN202
    """Map the served question texts back to public and primary ids."""
    async def go(s):  # noqa: ANN001, ANN202
        rows = (
            await s.execute(
                select(Question).where(Question.quiz_id == env.world["pool_pk"])
            )
        ).scalars().all()
        by_text = {q.question_text: q for q in rows}
        return [(by_text[t].public_id, by_text[t].id) for t, _ in served]
    return env.run(go)


def test_answering_a_question_that_was_not_on_your_paper_is_refused(env) -> None:
    attempt = env.start(env.world["pool"])
    served = {t for t, _ in env.paper(env.world["pool"])}

    async def other(s):  # noqa: ANN001, ANN202
        rows = (
            await s.execute(
                select(Question).where(Question.quiz_id == env.world["pool_pk"])
            )
        ).scalars().all()
        return next(q.public_id for q in rows if q.question_text not in served)

    stranger = env.run(other)

    with pytest.raises(ValidationError):
        env.submit(attempt.public_id, [AnswerInput(question_id=stranger)])


# =============================================================================
# auto_submit_on_expiry
# =============================================================================


def test_a_submission_after_the_time_limit_is_refused(env) -> None:
    attempt = env.start(env.world["timed"])
    env.backdate(attempt.public_id, 30)

    with pytest.raises(ConflictError):
        env.submit(attempt.public_id, [])


def test_an_expired_attempt_stops_blocking_the_next_one(env) -> None:
    """The trap this setting was supposed to prevent and did not.

    An attempt whose timer ran out while the tab was shut stayed "in
    progress" for ever: the student was refused every further attempt they
    were entitled to, and the tutor saw a result that never arrived.
    """
    first = env.start(env.world["timed"])
    env.backdate(first.public_id, 30)

    second = env.start(env.world["timed"])

    assert second.public_id != first.public_id
    assert second.attempt_number == 2

    async def reread(s):  # noqa: ANN001, ANN202
        row = await s.get(QuizAttempt, first.id)
        return row.finished_at, row.auto_submitted, row.score, row.started_at

    finished_at, auto, score, started_at = env.run(reread)

    assert auto is True
    # Closed at the cutoff, not at the moment somebody noticed -- otherwise
    # the record carries a false duration.
    assert finished_at is not None and finished_at < datetime.now(timezone.utc)
    assert finished_at - started_at < timedelta(minutes=11)
    # Nothing was submitted, so nothing was earned. Harsh, and the honest
    # outcome of a paper that never arrived.
    assert score == Decimal("0.00")


def test_an_advisory_timer_still_accepts_a_late_submission(env) -> None:
    attempt = env.start(env.world["advisory"])
    env.backdate(attempt.public_id, 30)

    done = env.submit(attempt.public_id, [])

    # With `auto_submit_on_expiry` off the limit is guidance, and a network
    # blip must not destroy somebody's work -- but the tutor is told.
    assert done.finished_at is not None
    assert done.submitted_late is True
    assert done.auto_submitted is False


def test_an_advisory_timer_leaves_an_abandoned_attempt_alone(env) -> None:
    first = env.start(env.world["advisory"])
    env.backdate(first.public_id, 30)

    # Still theirs to submit, so starting a second would be the attempt-limit
    # bypass the in-progress check exists to stop.
    with pytest.raises(ConflictError):
        env.start(env.world["advisory"])


def test_a_marker_can_close_expired_attempts(env) -> None:
    attempt = env.start(env.world["timed"])
    env.backdate(attempt.public_id, 30)

    async def close(s):  # noqa: ANN001, ANN202
        tutor = await s.get(User, env.world["tutor"])
        return await QuizService(s).close_expired_attempts(env.world["timed"], actor=tutor)

    assert env.run(close) == 1
    # Idempotent: the second sweep finds nothing left in progress.
    assert env.run(close) == 0


def test_a_student_cannot_close_other_peoples_attempts(env) -> None:
    async def close(s):  # noqa: ANN001, ANN202
        student = await s.get(User, env.world["alice"])
        return await QuizService(s).close_expired_attempts(env.world["timed"], actor=student)

    with pytest.raises(AuthorizationError):
        env.run(close)


# =============================================================================
# show_result_immediately / show_correct_answers / show_explanations
# =============================================================================


def _sit_withheld(env):  # noqa: ANN001, ANN202
    attempt = env.start(env.world["withheld"])

    async def go(s):  # noqa: ANN001, ANN202
        question = (
            await s.execute(
                select(Question).where(Question.quiz_id == env.world["withheld_pk"])
            )
        ).scalars().first()
        return question.public_id, env.world["correct"][question.id]

    question_id, option_id = env.run(go)
    return env.submit(
        attempt.public_id,
        [AnswerInput(question_id=question_id, selected_option_ids=[option_id])],
    )


def _rendered(env, attempt_public_id: object, who: str):  # noqa: ANN001, ANN202
    """The attempt as this reader's response would carry it."""
    async def go(s):  # noqa: ANN001, ANN202
        from backend.api.v1.quizzes import _attempt_response
        service = QuizService(s)
        actor = await s.get(User, env.world[who])
        attempt = await service.get_attempt(attempt_public_id, actor=actor)
        visible = await service.results_visible_to(attempt, actor=actor)
        return _attempt_response(attempt, results_visible=visible)
    return env.run(go)


def test_a_withheld_mark_is_withheld_from_the_student(env) -> None:
    done = _sit_withheld(env)
    # Marked: the score exists, and is simply not handed over yet.
    assert done.score == Decimal("100.00")

    body = _rendered(env, done.public_id, "alice")

    assert body.results_visible is False
    assert body.score is None
    assert body.is_passed is None
    # A total hidden while every per-question mark is listed beside it is not
    # hidden at all.
    assert [a.score_awarded for a in body.answers] == [None]
    assert [a.correct_answer for a in body.answers] == [None]
    assert [a.explanation for a in body.answers] == [None]


def test_the_marker_sees_the_mark_they_just_entered(env) -> None:
    done = _sit_withheld(env)

    body = _rendered(env, done.public_id, "tutor")

    # Withholding from the person entering the marks would make the quiz
    # unmarkable, which is how a visibility rule written as a role check
    # rather than a permission goes wrong.
    assert body.results_visible is True
    assert body.score == Decimal("100.00")


def test_a_guardian_is_held_back_with_their_ward(env) -> None:
    done = _sit_withheld(env)

    body = _rendered(env, done.public_id, "guardian")

    # Releasing to the student but not the parent is a bug; the other way
    # round is a leak.
    assert body.results_visible is False
    assert body.score is None


def test_releasing_hands_over_the_mark_the_key_and_the_reason(env) -> None:
    done = _sit_withheld(env)

    async def release(s):  # noqa: ANN001, ANN202
        tutor = await s.get(User, env.world["tutor"])
        return await QuizService(s).release_results(env.world["withheld"], True, actor=tutor)

    quiz = env.run(release)
    assert quiz.results_released_at is not None

    body = _rendered(env, done.public_id, "alice")

    assert body.results_visible is True
    assert body.score == Decimal("100.00")
    answer = body.answers[0]
    assert answer.score_awarded == Decimal("1.00")
    assert answer.points_possible == Decimal("1.00")
    # This quiz sets both switches, so the student gets the key and the
    # reason -- which is what `show_explanations` had no way to show before,
    # because no question carried one.
    assert answer.correct_answer == "right-0"
    assert answer.explanation == "Because the first option is right."


def test_the_guardian_is_released_with_the_student(env) -> None:
    done = _sit_withheld(env)

    async def release(s):  # noqa: ANN001, ANN202
        tutor = await s.get(User, env.world["tutor"])
        await QuizService(s).release_results(env.world["withheld"], True, actor=tutor)

    env.run(release)

    assert _rendered(env, done.public_id, "guardian").score == Decimal("100.00")


def test_releasing_notifies_the_student_who_sat_it(env) -> None:
    _sit_withheld(env)

    async def release(s):  # noqa: ANN001, ANN202
        tutor = await s.get(User, env.world["tutor"])
        await QuizService(s).release_results(env.world["withheld"], True, actor=tutor)

    env.run(release)

    async def codes(s):  # noqa: ANN001, ANN202
        rows = await s.execute(
            text("SELECT user_id, type FROM notifications WHERE user_id IN (:a, :g, :b)"),
            {"a": env.world["alice"], "g": env.world["guardian"], "b": env.world["bob"]},
        )
        return {(r[0], r[1]) for r in rows}

    sent = env.run(codes)

    assert (env.world["alice"], "quiz_result_published") in sent
    assert (env.world["guardian"], "ward_quiz_result_published") in sent
    # Bob never sat it, so there is nothing for him to read -- and a
    # notification pointing at nothing is a worse message than none.
    assert not any(user == env.world["bob"] for user, _ in sent)


def test_a_quiz_that_shows_marks_immediately_has_nothing_to_release(env) -> None:
    async def release(s):  # noqa: ANN001, ANN202
        tutor = await s.get(User, env.world["tutor"])
        return await QuizService(s).release_results(env.world["plain"], True, actor=tutor)

    # Refused rather than quietly accepted: a tutor pressing a button that
    # does nothing would believe marks had just gone out.
    with pytest.raises(ConflictError):
        env.run(release)


def test_a_student_cannot_release_their_own_result(env) -> None:
    async def release(s):  # noqa: ANN001, ANN202
        alice = await s.get(User, env.world["alice"])
        return await QuizService(s).release_results(env.world["withheld"], True, actor=alice)

    with pytest.raises(AuthorizationError):
        env.run(release)


def test_an_ordinary_quiz_still_shows_its_marks_at_once(env) -> None:
    """The regression guard. Every quiz that exists today has
    `show_result_immediately` on, and must behave exactly as it did."""
    attempt = env.start(env.world["plain"])

    async def go(s):  # noqa: ANN001, ANN202
        question = (
            await s.execute(
                select(Question).where(Question.quiz_id == env.world["plain_pk"])
            )
        ).scalars().first()
        return question.public_id, env.world["correct"][question.id]

    question_id, option_id = env.run(go)
    done = env.submit(
        attempt.public_id,
        [AnswerInput(question_id=question_id, selected_option_ids=[option_id])],
    )

    body = _rendered(env, done.public_id, "alice")
    assert body.results_visible is True
    assert body.score == Decimal("100.00")
    # This quiz sets neither switch, so the key and the reason stay back even
    # though the mark is visible -- that is what makes reusing a quiz next
    # term possible.
    assert body.answers[0].correct_answer is None
    assert body.answers[0].explanation is None

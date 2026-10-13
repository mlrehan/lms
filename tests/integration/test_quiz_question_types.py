"""The four question types §9 asks for and the quiz engine did not have.

Fill in the blank, matching, ordering and numeric. Each needs its own answer
key, its own marking rule and -- the part that is easy to miss -- its own care
over what reaches the person sitting the quiz:

* **ordering**'s key is `question_options.order`, and that column was being
  sent to the student with every option. The sequence they were being asked
  to reconstruct was in the payload.
* **matching**'s key is the pairing, so the right-hand column has to arrive
  detached from the prompts it belongs to.
* **fill in the blank** and **numeric** keep their keys in
  `questions.settings`, which was served to students verbatim because it also
  carries innocuous things like a code question's language.

So the leak tests here matter as much as the marking ones: a type that marks
correctly and ships its own answer key is not a working question type.
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
from backend.core.errors import ValidationError
from backend.db.manager import DatabaseManager
from backend.models.batch import Batch
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.quiz import Question, QuestionOption, Quiz
from backend.schemas.quiz import AnswerInput, QuestionCreateRequest
from backend.services.quiz_service import QuizService
from backend.utils.enums import (
    AssessmentScope,
    CourseStatus,
    EnrollmentStatus,
    QuestionType,
    UserStatus,
)


@pytest.fixture()
def env():
    tag = f"qt{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="quiz-type-tests")
    world: dict = {}
    now = datetime.now(timezone.utc)

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}
        alice = User(
            username=f"{tag}.alice", slug=f"{tag}-alice", email=f"{tag}.alice@t.test",
            hashed_password="x", status=UserStatus.ACTIVE, roles=[roles["STUDENT"]],
        )
        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([alice, course])
        await s.flush()

        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=60), is_active=True, capacity=20)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        s.add(batch)
        await s.flush()
        s.add(Enrollments(batch_id=batch.id, student_id=alice.id,
                          enrollment_date=now, status=EnrollmentStatus.CONFIRMED))

        quiz = Quiz(
            course_id=course.id, batch_id=batch.id, scope=AssessmentScope.BATCH,
            title=f"{tag} Typed", passing_score=Decimal("50.00"), is_published=True,
            attempts_allowed=20, weight=Decimal("1.00"),
        )
        s.add(quiz)
        await s.flush()

        # One question of each type, each worth one mark so a score reads as
        # a percentage of the questions answered correctly.
        blank = Question(
            quiz_id=quiz.id, question_text="Capital of France?",
            question_type=QuestionType.FILL_BLANK, points=Decimal("1.00"), order=0,
            settings={"accepted": ["Paris", "City of Paris"]},
        )
        cased = Question(
            quiz_id=quiz.id, question_text="Symbol for sodium?",
            question_type=QuestionType.FILL_BLANK, points=Decimal("1.00"), order=1,
            settings={"accepted": ["Na"], "case_sensitive": True},
        )
        numeric = Question(
            quiz_id=quiz.id, question_text="Pi to 2dp?",
            question_type=QuestionType.NUMERIC, points=Decimal("1.00"), order=2,
            settings={"answer": "3.14", "tolerance": "0.01"},
        )
        exact = Question(
            quiz_id=quiz.id, question_text="How many sides has a hexagon?",
            question_type=QuestionType.NUMERIC, points=Decimal("1.00"), order=3,
            settings={"answer": "6"},
        )
        ordering = Question(
            quiz_id=quiz.id, question_text="Put these in order",
            question_type=QuestionType.ORDERING, points=Decimal("1.00"), order=4,
        )
        matching = Question(
            quiz_id=quiz.id, question_text="Match country to capital",
            question_type=QuestionType.MATCHING, points=Decimal("1.00"), order=5,
        )
        s.add_all([blank, cased, numeric, exact, ordering, matching])
        await s.flush()

        order_ids: list[int] = []
        # Six, not three: the display shuffle is seeded from a random
        # attempt id, so "it came back scrambled" is only a real assertion
        # when an accidental authored order is a 1-in-720 coincidence rather
        # than a 1-in-6 one.
        for position, label in enumerate(
            ("alpha", "beta", "gamma", "delta", "epsilon", "zeta")
        ):
            opt = QuestionOption(question_id=ordering.id, option_text=label,
                                 is_correct=False, order=position)
            s.add(opt)
            await s.flush()
            order_ids.append(opt.id)

        match_ids: dict[str, int] = {}
        # Six pairs for the same reason the ordering question has six items:
        # the right-hand column is sorted by its own text, so it aligning
        # with the shuffled prompts by chance is a 1-in-720 coincidence
        # rather than a 1-in-6 one. (With three pairs this test failed on its
        # first run against a correct implementation.)
        pairs = {
            "France": "Paris", "Japan": "Tokyo", "Peru": "Lima",
            "Kenya": "Nairobi", "Norway": "Oslo", "Chile": "Santiago",
        }
        for position, (left, right) in enumerate(pairs.items()):
            opt = QuestionOption(question_id=matching.id, option_text=left,
                                 is_correct=False, order=position, match_text=right)
            s.add(opt)
            await s.flush()
            match_ids[left] = opt.id
        await s.flush()

        world.update(
            alice=alice.id, quiz=quiz.public_id, quiz_pk=quiz.id,
            blank=blank.public_id, cased=cased.public_id,
            numeric=numeric.public_id, exact=exact.public_id,
            ordering=ordering.public_id, matching=matching.public_id,
            order_ids=order_ids, match_ids=match_ids, pairs=pairs,
        )

    run(build)

    def sit(*answers: AnswerInput):  # noqa: ANN202
        """One attempt, answering exactly what is passed."""
        async def go(s):  # noqa: ANN001, ANN202
            student = await s.get(User, world["alice"])
            service = QuizService(s)
            attempt = await service.start_attempt(world["quiz"], actor=student)
            return await service.submit_attempt(
                attempt.public_id, list(answers), actor=student
            )
        return run(go)

    def mark_for(attempt, question_public_id) -> Decimal | None:  # noqa: ANN001
        """What one question on a submitted attempt scored."""
        async def go(s):  # noqa: ANN001, ANN202
            question = (
                await s.execute(
                    select(Question).where(Question.public_id == question_public_id)
                )
            ).scalars().one()
            row = await s.execute(
                text("SELECT score_awarded FROM quiz_answers "
                     "WHERE attempt_id = :a AND question_id = :q"),
                {"a": attempt.id, "q": question.id},
            )
            value = row.scalar_one_or_none()
            return None if value is None else Decimal(str(value))
        return run(go)

    def served():  # noqa: ANN202
        """The paper as the student's own request would render it."""
        async def go(s):  # noqa: ANN001, ANN202
            from backend.api.v1.quizzes import _student_question
            student = await s.get(User, world["alice"])
            service = QuizService(s)
            await service.start_attempt(world["quiz"], actor=student)
            rows = await service.questions_for_attempt(world["quiz"], actor=student)
            return {
                q.question_type: _student_question(q, options) for q, options in rows
            }
        return run(go)

    ns = type("Env", (), dict(
        tag=tag, world=world, run=staticmethod(run), sit=staticmethod(sit),
        mark_for=staticmethod(mark_for), served=staticmethod(served),
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


ONE = Decimal("1.00")
ZERO = Decimal("0.00")


# =============================================================================
# fill in the blank
# =============================================================================


def test_a_typed_answer_is_marked_against_the_accepted_list(env) -> None:
    attempt = env.sit(AnswerInput(question_id=env.world["blank"], text_answer="Paris"))
    assert env.mark_for(attempt, env.world["blank"]) == ONE

    attempt = env.sit(AnswerInput(question_id=env.world["blank"], text_answer="Lyon"))
    assert env.mark_for(attempt, env.world["blank"]) == ZERO


def test_spacing_and_capitals_are_not_what_makes_an_answer_wrong(env) -> None:
    """The thing that makes automatic text marking untrustworthy.

    A student who types two spaces, or a capital, has not got the question
    wrong, and marking them wrong for it is worse than not marking at all.
    """
    for typed in ("  paris  ", "PARIS", "City  of   Paris"):
        attempt = env.sit(AnswerInput(question_id=env.world["blank"], text_answer=typed))
        assert env.mark_for(attempt, env.world["blank"]) == ONE, typed


def test_a_question_that_says_the_case_matters_is_obeyed(env) -> None:
    attempt = env.sit(AnswerInput(question_id=env.world["cased"], text_answer="Na"))
    assert env.mark_for(attempt, env.world["cased"]) == ONE

    # `NA` is sodium only if case is ignored, and this question says it is
    # not -- a chemical symbol is the standard reason to care.
    attempt = env.sit(AnswerInput(question_id=env.world["cased"], text_answer="NA"))
    assert env.mark_for(attempt, env.world["cased"]) == ZERO


# =============================================================================
# numeric
# =============================================================================


def test_a_number_within_tolerance_is_right_and_outside_it_is_wrong(env) -> None:
    for typed in ("3.14", "3.15", "3.13"):
        attempt = env.sit(AnswerInput(question_id=env.world["numeric"], text_answer=typed))
        assert env.mark_for(attempt, env.world["numeric"]) == ONE, typed

    attempt = env.sit(AnswerInput(question_id=env.world["numeric"], text_answer="3.2"))
    assert env.mark_for(attempt, env.world["numeric"]) == ZERO


def test_no_tolerance_means_exactly_right(env) -> None:
    attempt = env.sit(AnswerInput(question_id=env.world["exact"], text_answer="6"))
    assert env.mark_for(attempt, env.world["exact"]) == ONE

    # Missing tolerance is zero tolerance, not infinite: an omitted field
    # must not make every answer correct.
    attempt = env.sit(AnswerInput(question_id=env.world["exact"], text_answer="7"))
    assert env.mark_for(attempt, env.world["exact"]) == ZERO


def test_the_same_number_written_differently_is_the_same_number(env) -> None:
    attempt = env.sit(AnswerInput(question_id=env.world["exact"], text_answer=" 6.0 "))
    assert env.mark_for(attempt, env.world["exact"]) == ONE


@pytest.mark.parametrize("typed", ["3.14", " 3,14 ", "3,14"])
def test_a_comma_is_a_decimal_point_when_it_is_used_like_one(env, typed) -> None:
    """Much of the world writes 3,14.

    Stripping that comma as a thousands separator turns it into 314 -- a
    correct answer marked wrong, silently. The rule is applied by where the
    comma sits, not by a locale setting nobody has set.
    """
    attempt = env.sit(AnswerInput(question_id=env.world["numeric"], text_answer=typed))
    assert env.mark_for(attempt, env.world["numeric"]) == ONE, typed


def test_a_thousands_separator_is_still_a_thousands_separator(env) -> None:
    from backend.services.quiz_service import _numeric

    # Driven at the parser because no question in this fixture has an answer
    # in the thousands, and inventing one to assert a string transformation
    # would be the longer way round.
    assert _numeric("1,000") == "1000"
    assert _numeric("1,000.50") == "1000.50"
    assert _numeric("1,234") == "1234"


def test_words_in_a_numeric_box_are_wrong_not_unmarkable(env) -> None:
    """`None` would mean "a human must mark this", which is a different claim.

    An attempt containing one is left without a score at all, so a student
    typing "six" into a numeric question would hold their whole result up
    waiting for a tutor who has nothing to do.
    """
    attempt = env.sit(AnswerInput(question_id=env.world["exact"], text_answer="six"))

    assert env.mark_for(attempt, env.world["exact"]) == ZERO
    assert attempt.score is not None


# =============================================================================
# ordering
# =============================================================================


def test_the_right_sequence_scores_and_a_swapped_one_does_not(env) -> None:
    ids = env.world["order_ids"]

    attempt = env.sit(AnswerInput(question_id=env.world["ordering"], selected_option_ids=ids))
    assert env.mark_for(attempt, env.world["ordering"]) == ONE

    swapped = [ids[1], ids[0], *ids[2:]]
    attempt = env.sit(
        AnswerInput(question_id=env.world["ordering"], selected_option_ids=swapped)
    )
    # Two adjacent items transposed and nothing else: the one case a marker
    # comparing *sets* instead of sequences would call correct.
    assert env.mark_for(attempt, env.world["ordering"]) == ZERO


def test_the_sequence_the_student_chose_is_stored_as_they_chose_it(env) -> None:
    ids = env.world["order_ids"]
    reversed_ids = list(reversed(ids))

    attempt = env.sit(
        AnswerInput(question_id=env.world["ordering"], selected_option_ids=reversed_ids)
    )

    async def stored(s):  # noqa: ANN001, ANN202
        question = (
            await s.execute(
                select(Question).where(Question.public_id == env.world["ordering"])
            )
        ).scalars().one()
        row = await s.execute(
            text("SELECT selected_options FROM quiz_answers "
                 "WHERE attempt_id = :a AND question_id = :q"),
            {"a": attempt.id, "q": question.id},
        )
        return row.scalar_one()

    # Sorted storage would throw the answer away -- and would mark everyone
    # who got it right as wrong, because the stored order would match the
    # key by accident.
    assert env.run(stored)["ordered_option_ids"] == reversed_ids


def test_the_correct_sequence_never_reaches_the_student(env) -> None:
    """The leak. `order` is the answer, and it was in every option.

    The student is sent their position in the list they were served, so
    re-sorting by it is harmless and the authored sequence stays on the
    server.
    """
    question = env.served()[QuestionType.ORDERING]
    positions = [o.order for o in question.options]

    assert positions == list(range(len(positions)))

    async def authored(s):  # noqa: ANN001, ANN202
        rows = await s.execute(
            text("SELECT id FROM question_options WHERE question_id = "
                 "(SELECT id FROM questions WHERE public_id = :p) ORDER BY \"order\""),
            {"p": str(env.world["ordering"])},
        )
        return [r[0] for r in rows]

    # Scrambled, and not by luck: four items in authored order would be a
    # 1-in-24 coincidence, and the shuffle is seeded so this is stable.
    assert [o.id for o in question.options] != env.run(authored)


# =============================================================================
# matching
# =============================================================================


def test_the_right_pairing_scores_and_a_swapped_one_does_not(env) -> None:
    ids = env.world["match_ids"]
    right = {str(ids[left]): capital for left, capital in env.world["pairs"].items()}

    attempt = env.sit(AnswerInput(question_id=env.world["matching"], matches=right))
    assert env.mark_for(attempt, env.world["matching"]) == ONE

    wrong = dict(right)
    wrong[str(ids["France"])] = "Tokyo"
    wrong[str(ids["Japan"])] = "Paris"
    attempt = env.sit(AnswerInput(question_id=env.world["matching"], matches=wrong))
    # The same set of capitals, paired wrongly -- which is what a marker
    # comparing the values alone would accept.
    assert env.mark_for(attempt, env.world["matching"]) == ZERO


def test_a_half_finished_matching_answer_is_wrong(env) -> None:
    ids = env.world["match_ids"]
    partial = {str(ids["France"]): "Paris"}

    attempt = env.sit(AnswerInput(question_id=env.world["matching"], matches=partial))

    # All-or-nothing, like MCQ_MULTIPLE: partial credit needs a rule nobody
    # has specified, and inventing one here would silently decide how every
    # matching question in the institution is marked.
    assert env.mark_for(attempt, env.world["matching"]) == ZERO


def test_the_pairing_never_reaches_the_student(env) -> None:
    question = env.served()[QuestionType.MATCHING]

    column = [o.match_text or "" for o in question.options]
    prompts = [o.option_text for o in question.options]

    # Every right-hand item is offered -- they have to be, or the question
    # cannot be answered.
    assert sorted(column) == sorted(env.world["pairs"].values())
    # The column's order is derived from its own text, which is the property
    # that matters: it cannot encode the pairing, because it does not depend
    # on the prompts at all. A leaky implementation -- serving each option
    # beside its own `match_text` -- would align every single time.
    assert column == sorted(column)
    assert [env.world["pairs"][p] for p in prompts] != column


# =============================================================================
# what the student is sent, and what they are not
# =============================================================================


def test_the_answer_key_is_stripped_out_of_a_questions_settings(env) -> None:
    """`settings` is a general bag, and now it holds answers.

    It carries a code question's language and test cases, so it was served
    verbatim. Fill-in-the-blank and numeric keys live there too, which turned
    that convenience into the whole answer key in the payload.
    """
    served = env.served()

    for kind in (QuestionType.FILL_BLANK, QuestionType.NUMERIC):
        settings = served[kind].settings or {}
        assert "accepted" not in settings, kind
        assert "answer" not in settings, kind
        assert "tolerance" not in settings, kind


# =============================================================================
# authoring: a key that cannot be answered is refused at the door
# =============================================================================


@pytest.mark.parametrize(
    ("kind", "settings", "options", "fragment"),
    [
        (QuestionType.FILL_BLANK, {}, [], "settings.accepted"),
        (QuestionType.FILL_BLANK, {"accepted": []}, [], "settings.accepted"),
        (QuestionType.NUMERIC, {}, [], "settings.answer"),
        (QuestionType.NUMERIC, {"answer": "abc"}, [], "number"),
        (QuestionType.NUMERIC, {"answer": "1", "tolerance": "-1"}, [], "negative"),
        (
            QuestionType.ORDERING,
            None,
            [{"option_text": "a", "order": 0}],
            "at least two",
        ),
        (
            QuestionType.ORDERING,
            None,
            [{"option_text": "a", "order": 0}, {"option_text": "b", "order": 0}],
            "distinct position",
        ),
        (
            QuestionType.MATCHING,
            None,
            [{"option_text": "a", "match_text": "1", "order": 0},
             {"option_text": "b", "order": 1}],
            "a match for every item",
        ),
        (
            QuestionType.MATCHING,
            None,
            [{"option_text": "a", "match_text": "1", "order": 0},
             {"option_text": "a", "match_text": "2", "order": 1}],
            "every item to be different",
        ),
    ],
)
def test_an_unanswerable_key_is_refused_when_the_question_is_written(
    env, kind, settings, options, fragment
) -> None:
    """Caught at authoring, not discovered by the first student to sit it.

    Every case here is a question whose key makes it impossible to answer
    correctly, or ambiguous about what correct means -- which, marked
    automatically, means a student losing a mark for an author's mistake.
    """
    with pytest.raises(ValueError, match=fragment):
        QuestionCreateRequest(
            question_text="?",
            question_type=kind,
            points=Decimal("1.00"),
            settings=settings,
            options=options or [],
        )


def test_the_same_rules_apply_when_a_question_is_edited(env) -> None:
    """The copy that drifted.

    The rules were written out twice -- once in the request schema, once in
    the service -- and the service's copy only understood options. Editing a
    numeric question's answer to something unparseable went straight in.
    """
    async def edit(s):  # noqa: ANN001, ANN202
        from backend.schemas.quiz import QuestionUpdateRequest
        student = await s.get(User, env.world["alice"])
        return await QuizService(s).update_question(
            env.world["numeric"],
            QuestionUpdateRequest(settings={"answer": "not a number"}),
            actor=student,
        )

    with pytest.raises(ValidationError):
        env.run(edit)


def test_the_sequence_is_hidden_before_an_attempt_starts_too(env) -> None:
    """The browser pass found this one, and only the browser pass could.

    `questions_for_attempt` returns the authored order when nobody is sitting
    the quiz -- right for an author previewing, and for an ordering question
    it handed a student the sequence they were about to be asked for, visible
    on the quiz page before pressing Start.

    The scramble is seeded by the question rather than the attempt, because
    there is no attempt yet; every student sees the same scrambled order,
    which is fine. What has to stay hidden is the *authored* order.
    """
    async def preview(s):  # noqa: ANN001, ANN202
        student = await s.get(User, env.world["alice"])
        rows = await QuizService(s).questions_for_attempt(env.world["quiz"], actor=student)
        return {
            q.question_type: [o.option_text for o in options] for q, options in rows
        }

    seen = env.run(preview)
    authored = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]

    assert sorted(seen[QuestionType.ORDERING]) == sorted(authored)
    assert seen[QuestionType.ORDERING] != authored

    # Stable, or a student who reloads the page sees the items move.
    assert env.run(preview)[QuestionType.ORDERING] == seen[QuestionType.ORDERING]

"""Quizzes, questions and attempts (spec §13).

**`QuizAttempt.score` is a percentage, not raw points.** It is stored that
way because the only thing it is ever compared against is
`Quiz.passing_score` (documented in the model as "e.g. 70.00"), and because a
percentage stays meaningful if the question set changes -- raw points would
silently mean something different after an edit. Raw points earned per
question remain on each `QuizAnswer.score_awarded`.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.logging import get_logger
from backend.core.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from backend.models.batch import Batch
from backend.models.enrollment import Enrollments
from backend.models.identity.user import User
from backend.models.quiz import Question, QuestionOption, Quiz, QuizAnswer, QuizAttempt
from backend.repositories.enrollment import ACTIVE_STATUSES
from backend.repositories.quiz import AttemptRepository, QuizRepository
from backend.schemas.base import PageParams
from backend.schemas.quiz import (
    AUTO_GRADABLE,
    AnswerInput,
    GradeAttemptRequest,
    QuestionCreateRequest,
    QuestionUpdateRequest,
    QuizCreateRequest,
    QuizUpdateRequest,
    answer_key_problem,
)
from backend.services import audit_service
from backend.services.rich_text import sanitize_rich_text
from backend.services.audit_service import AuditAction
from backend.services.course_service import CourseService
from backend.services.gradebook_service import GradeBookService
from backend.services.assessment_scope import (
    AssessmentScopeResolver,
    AssessmentTarget,
    validate as validate_scope,
)
from backend.services.notification_service import NotificationService
from backend.core.notification_types import NotificationType
from backend.services.scope import ScopeResolver
from backend.utils.enums import GradeComponentType, QuestionType

# Wall-clock slack allowed past a quiz's `duration_minutes` before the
# submission is stamped late. Covers the round trip and a slow client; it is
# not a grace period on the exam itself.
_SUBMIT_GRACE = timedelta(seconds=30)


logger = get_logger(__name__)


def _numeric(typed: str) -> str:
    """What a person typed, as a number.

    Spaces and thousands separators are not what makes an answer wrong, and
    marking `1,000` wrong for a question whose answer is 1000 is the kind of
    thing that makes a tutor stop trusting automatic marking.

    **A comma is a decimal point when it is used like one.** Much of the
    world writes 3,14 for 3.14, and stripping that comma as a separator would
    silently turn it into 314 -- a correct answer marked wrong, with nothing
    anywhere saying why. So a single comma followed by one or two digits, in a
    string with no dot, is read as a decimal separator; every other comma is
    grouping and is removed. `1,000` is a thousand and `3,14` is three and a
    bit, which is what both writers meant.
    """
    cleaned = typed.strip().replace(" ", "").replace(" ", "")
    if "." not in cleaned and cleaned.count(",") == 1:
        whole, _, fraction = cleaned.partition(",")
        if 1 <= len(fraction) <= 2 and fraction.isdigit():
            return f"{whole}.{fraction}"
    return cleaned.replace(",", "")


def _normalise(text: str, *, fold: bool = True) -> str:
    """Compare what a person typed with what an author typed.

    Trailing spaces, a double space between words and a capital letter are
    not what makes an answer wrong -- marking them wrong is the thing that
    makes automatic text marking untrustworthy. Case folding is skipped when
    the question says the case matters (a chemical formula, a case-sensitive
    identifier), which is why it is a parameter rather than a rule.
    """
    collapsed = " ".join(text.split())
    return collapsed.casefold() if fold else collapsed


def _scrambled_options(question: Question, seed: str) -> list[QuestionOption]:
    """The options in a stable but not-authored order.

    Used wherever the authored order is itself the answer. A new list, never
    a sort in place, for the same reason as `_ordered_options`.
    """
    options = _ordered_options(question)
    random.Random(seed).shuffle(options)
    return options


def _ordered_options(question: Question) -> list[QuestionOption]:
    """The authored option order, as a new list.

    A new list rather than a sort in place: `question.options` is a mapped
    collection, and reordering it would mark the relationship dirty and
    invite SQLAlchemy to write a display choice back to the answer key.
    """
    return sorted(question.options, key=lambda o: (o.order, o.id))


class QuizService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.quizzes = QuizRepository(session)
        self.attempts = AttemptRepository(session)
        self.courses = CourseService(session)
        self.scopes = ScopeResolver(session)
        # The same shared resolver assignments use. §3's "do not create
        # duplicated implementations" is satisfied by there being exactly one.
        self.targets = AssessmentScopeResolver(session)

    # -- quizzes -------------------------------------------------------------

    async def list_quizzes(
        self,
        params: PageParams,
        *,
        actor: User,
        course_public_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[Quiz], int]:
        course_id = None
        if course_public_id is not None:
            course_id = (await self.courses.get(course_public_id, actor=actor)).id

        scope = await self.scopes.visible_course_ids(actor)
        # A student has no business seeing a quiz the tutor is still drafting;
        # anyone who can author quizzes sees unpublished ones too.
        published_only = not await self._can_author(actor)
        return await self.quizzes.search(
            params, scope=scope, course_id=course_id, published_only=published_only
        )

    async def get(self, public_id: uuid.UUID, *, actor: User) -> Quiz:
        row = await self.quizzes.get_by_public_id_full(public_id)
        if row is None:
            raise NotFoundError("Quiz not found.")

        scope = await self.scopes.visible_course_ids(actor)
        if not scope.allows(row.course_id):
            raise NotFoundError("Quiz not found.")

        if not row.is_published and not await self._can_author(actor):
            # An unpublished quiz is not merely unreadable; it is not
            # something the course admits to having yet -- 404, not 403.
            raise NotFoundError("Quiz not found.")
        return row

    async def create(
        self, course_public_id: uuid.UUID, payload: QuizCreateRequest, *, actor: User
    ) -> Quiz:
        course = await self.courses.get(course_public_id, actor=actor)

        # The same gap assignments had, and for the same reason: reads here are scoped by `visible_course_ids`
        # (see `list`/`get` above) while creation was not, so a quiz could be planted on a course the author
        # cannot afterwards open. See `AssignmentService.create` for why this is a 403 and not a 404.
        scope = await self.scopes.visible_course_ids(actor)
        if not scope.allows(course.id):
            raise AuthorizationError("You can only set coursework on a course you teach.")

        target = await self.targets.resolve_ids(
            scope=payload.scope,
            course_id=course.id,
            batch_id=await self.targets.batch_id(payload.batch_id),
            session_id=await self.targets.session_id(payload.session_id),
        )
        validate_scope(target)
        if target.course_id != course.id:
            raise ValidationError("That batch or session belongs to a different course.")

        row = Quiz(
            course_id=course.id,
            scope=target.scope,
            batch_id=target.batch_id,
            session_id=target.session_id,
            available_from=payload.available_from,
            available_until=payload.available_until,
            shuffle_answers=payload.shuffle_answers,
            questions_per_attempt=payload.questions_per_attempt,
            show_result_immediately=payload.show_result_immediately,
            show_correct_answers=payload.show_correct_answers,
            show_explanations=payload.show_explanations,
            auto_submit_on_expiry=payload.auto_submit_on_expiry,
            weight=payload.weight,
            title=payload.title,
            instructions=payload.instructions,
            duration_minutes=payload.duration_minutes,
            attempts_allowed=payload.attempts_allowed,
            passing_score=payload.passing_score,
            shuffle_questions=payload.shuffle_questions,
            is_auto_graded=payload.is_auto_graded,
            grading_policy=payload.grading_policy,
            # Always unpublished: a quiz created live would be visible to
            # students before it had a single question.
            is_published=False,
        )
        await self.quizzes.add_and_flush(row)

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="quiz",
            entity_id=row.id,
            details={"title": row.title, "course": course.title},
        )
        return await self.quizzes.get_by_public_id_full(row.public_id)  # type: ignore[return-value]

    async def update(
        self, public_id: uuid.UUID, payload: QuizUpdateRequest, *, actor: User
    ) -> Quiz:
        row = await self.get(public_id, actor=actor)
        changes = payload.model_dump(exclude_unset=True)

        if changes and await self._has_attempts(row.id):
            # Changing the pass mark, attempt limit or grading policy after
            # people have sat the quiz retroactively rewrites what their
            # results mean.
            raise ConflictError(
                "This quiz already has attempts and can no longer be modified."
            )

        for field, value in changes.items():
            setattr(row, field, value)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="quiz",
            entity_id=row.id,
            details={"fields": sorted(changes)},
        )
        return row

    async def set_published(
        self, public_id: uuid.UUID, is_published: bool, *, actor: User
    ) -> Quiz:
        row = await self.get(public_id, actor=actor)

        if is_published:
            count, _ = await self.quizzes.question_stats(row.id)
            if count == 0:
                raise ConflictError("A quiz with no questions cannot be published.")

        was_published = bool(row.is_published)
        row.is_published = is_published
        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="quiz",
            entity_id=row.id,
            details={"is_published": is_published},
        )

        # Only the transition into being published, and only once.
        #
        # Re-saving a published quiz must not re-announce it, and *withdrawing*
        # one must not announce anything at all -- "your quiz is available"
        # arriving as it is taken down is worse than silence. Retraction is
        # deliberately quiet: it is rare, and the quiz simply stops appearing.
        if is_published and not was_published:
            await self._announce(row)

        return row

    async def _announce(self, quiz: Quiz) -> None:
        """Tell the students it was set for -- and only them.

        The roster comes from the shared scope resolver, so a batch-scoped quiz
        reaches that batch rather than the whole course. Telling a course about
        work they cannot open is how a student learns about an assessment that
        is not theirs, and it is the mistake `AssessmentScopeResolver` exists
        to prevent.
        """
        roster = sorted(await self.targets.eligible_student_ids(AssessmentTarget.of(quiz)))
        if not roster:
            return

        # `Quiz.course` is `lazy="selectin"`, so the title costs no extra
        # query here.
        where = quiz.course.title if quiz.course is not None else "your course"
        meta = {"quiz_id": str(quiz.public_id)}

        notifications = NotificationService(self.session)
        await notifications.notify_many(
            roster,
            type_=NotificationType.QUIZ_PUBLISHED,
            title=f"New quiz: {quiz.title}",
            body=f"{where} — open it from your coursework.",
            meta=meta,
        )

    async def delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        row = await self.get(public_id, actor=actor)

        if await self._has_attempts(row.id):
            raise ConflictError(
                "This quiz already has attempts and cannot be deleted."
            )

        for question in await self.quizzes.questions_for(row.id):
            await self.quizzes.delete_options_for(question.id)
            await self.session.delete(question)

        entity_id = row.id
        await self.session.delete(row)
        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="quiz",
            entity_id=entity_id,
        )

    # -- questions -----------------------------------------------------------

    async def list_questions(self, public_id: uuid.UUID, *, actor: User) -> list[Question]:
        """The canonical order, for authoring."""
        quiz = await self.get(public_id, actor=actor)
        return await self.quizzes.questions_for(quiz.id)

    async def questions_for_attempt(
        self, public_id: uuid.UUID, *, actor: User
    ) -> list[tuple[Question, list[QuestionOption]]]:
        """The questions as *this* person should see them, with their options.

        **Seeded from the attempt, never from the clock.** A student who
        reloads mid-quiz, or whose connection drops, must be given the same
        paper back: an order that changed between requests would silently
        remap every answer they had already chosen. `random.Random(seed)` with
        the attempt's own id gives one stable order per sitting, and a
        different one to the next student, which is what shuffling is for.

        Nothing is stored. The question bank is frozen as soon as a quiz has
        any attempt (see `_assert_question_bank_editable`), so the inputs to
        the shuffle cannot change underneath it and a column recording the
        order would only be a second copy of something already determined.

        **Options are returned alongside rather than reordered in place.**
        `question.options` is a mapped collection; shuffling it would mark the
        relationship dirty and invite SQLAlchemy to write a display choice
        back to the answer key.
        """
        quiz = await self.get(public_id, actor=actor)
        questions = list(await self.quizzes.questions_for(quiz.id))

        attempt = await self.attempts.get_in_progress(quiz_id=quiz.id, student_id=actor.id)
        if attempt is None:
            # Not sitting it: an author previewing, or a student who has not
            # started. The canonical order is the honest answer -- inventing a
            # shuffle, or drawing a sample, here would show a different paper
            # from the one they get.
            #
            # **Except for the two types whose order is the answer.** An
            # ordering question served in its authored order hands over the
            # sequence the student is about to be asked for, and they can read
            # this before pressing start. Seeded by the question rather than
            # the attempt, because there is no attempt yet: that makes the
            # scramble the same for everybody, which is fine -- what has to
            # stay hidden is the authored order, not the fact that two
            # students saw the same one. An author who wants the real order
            # has the answer-key route, which exists for exactly that.
            return [
                (
                    q,
                    _scrambled_options(q, f"preview:{q.public_id}")
                    if q.question_type in (QuestionType.ORDERING, QuestionType.MATCHING)
                    else _ordered_options(q),
                )
                for q in questions
            ]

        return self._paper_for(quiz, attempt, questions)

    def _paper_for(
        self, quiz: Quiz, attempt: QuizAttempt, questions: Sequence[Question]
    ) -> list[tuple[Question, list[QuestionOption]]]:
        """The exact paper one sitting was served, questions and options.

        **The single definition, and it has to be**: the same list decides
        what the student is shown, what their submission is allowed to answer,
        and what their percentage is calculated out of. Two copies of this
        reasoning would eventually mark people against questions they were
        never asked.

        Three seeds, deliberately different, all derived from the attempt's
        own id and never from the clock:

        * `p:` draws the sample for `questions_per_attempt`. Separate from the
          display seed so that toggling `shuffle_questions` on an unsat quiz
          does not change *which* questions are drawn;
        * `q:` orders the questions;
        * `a:...:<question>` orders each question's options, per question, or
          every question in the paper would be permuted identically and the
          correct answer's position would be guessable from one of them.
        """
        drawn = self._drawn(quiz, attempt, questions)

        if quiz.shuffle_questions:
            random.Random(f"q:{attempt.public_id}").shuffle(drawn)

        out: list[tuple[Question, list[QuestionOption]]] = []
        for question in drawn:
            options = _ordered_options(question)
            if question.question_type in (QuestionType.ORDERING, QuestionType.MATCHING):
                # The authored order *is* the answer key for ORDERING, and the
                # authored pairing is the key for MATCHING, so these are
                # always presented scrambled -- `shuffle_answers` does not
                # come into it. Serving them in order would be serving the
                # answers.
                random.Random(f"s:{attempt.public_id}:{question.id}").shuffle(options)
            elif quiz.shuffle_answers:
                random.Random(f"a:{attempt.public_id}:{question.id}").shuffle(options)
            out.append((question, options))
        return out

    @staticmethod
    def _drawn(
        quiz: Quiz, attempt: QuizAttempt, questions: Sequence[Question]
    ) -> list[Question]:
        """`questions_per_attempt` applied: which questions this sitting got.

        Null, or a number at or above the size of the bank, means the whole
        bank -- so a tutor who sets 20 on a 12-question quiz gets 12 rather
        than an error, which is the only sensible reading of "draw 20".

        The draw is random by design even when `shuffle_questions` is off:
        taking the first N in authored order would hand every student the same
        subset, and a pool nobody draws differently from is not a pool.
        """
        pool = sorted(questions, key=lambda q: (q.order, q.id))
        wanted = quiz.questions_per_attempt
        if not wanted or wanted >= len(pool):
            return pool

        random.Random(f"p:{attempt.public_id}").shuffle(pool)
        # Back into authored order afterwards: the draw decides *which*,
        # `shuffle_questions` decides *in what order*, and conflating them
        # would make a quiz that draws a sample always appear shuffled.
        return sorted(pool[:wanted], key=lambda q: (q.order, q.id))

    async def _assert_within_total(
        self, quiz: Quiz, *, adding: Decimal, replacing: Decimal = Decimal("0")
    ) -> None:
        """Refuse marks that would take the paper past its stated total.

        Only when a total was stated: `total_marks` is nullable, and a quiz
        written before it existed has no ceiling to breach. `replacing` is the
        points the question being edited already contributed, so lowering a
        question on a full paper is allowed -- which is what makes the limit
        recoverable rather than a dead end.
        """
        if quiz.total_marks is None:
            return

        total = Decimal(str(quiz.total_marks))
        _, written = await self.quizzes.question_stats(quiz.id)
        after = Decimal(str(written)) - replacing + adding
        if after > total:
            raise ValidationError(
                "That would take this paper past its total.",
                details={
                    "total_marks": str(total),
                    "already_written": str(Decimal(str(written)) - replacing),
                    "remaining": str(total - (Decimal(str(written)) - replacing)),
                    "given": str(adding),
                },
            )

    async def add_question(
        self, public_id: uuid.UUID, payload: QuestionCreateRequest, *, actor: User
    ) -> Question:
        quiz = await self.get(public_id, actor=actor)
        await self._assert_question_bank_editable(quiz)
        await self._assert_within_total(quiz, adding=Decimal(str(payload.points)))

        question = Question(
            quiz_id=quiz.id,
            # Formatted text, re-parsed here. A question is shown to every
            # student set the quiz, so what the editor produced is a request
            # and the stored result is the only thing anybody sees.
            question_text=sanitize_rich_text(payload.question_text) or payload.question_text,
            question_type=payload.question_type,
            points=payload.points,
            order=payload.order,
            settings=payload.settings,
            explanation=payload.explanation,
        )
        self.session.add(question)
        await self.session.flush()

        for option in payload.options:
            self.session.add(
                QuestionOption(
                    question_id=question.id,
                    option_text=option.option_text,
                    is_correct=option.is_correct,
                    order=option.order,
                    match_text=option.match_text,
                )
            )
        await self.session.flush()

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="question",
            entity_id=question.id,
            details={"quiz": quiz.title, "type": payload.question_type.value},
        )
        return await self.quizzes.get_question(question.public_id)  # type: ignore[return-value]

    async def update_question(
        self, question_public_id: uuid.UUID, payload: QuestionUpdateRequest, *, actor: User
    ) -> Question:
        question = await self.quizzes.get_question(question_public_id)
        if question is None:
            raise NotFoundError("Question not found.")

        quiz = await self.get(question.quiz.public_id, actor=actor)
        await self._assert_question_bank_editable(quiz)

        changes = payload.model_dump(exclude_unset=True)
        options = changes.pop("options", None)

        if changes.get("question_text") is not None:
            # `or` the original: a question written entirely as, say, a bare
            # `<` would sanitise to nothing, and storing an empty question is
            # worse than storing the text that was typed.
            changes["question_text"] = (
                sanitize_rich_text(changes["question_text"]) or changes["question_text"]
            )

        if "points" in changes and changes["points"] is not None:
            # `replacing` is what this question already contributes, so
            # raising it is checked against the room left *after* removing
            # its own current marks -- otherwise a question could never be
            # edited at all on a paper that is exactly full.
            await self._assert_within_total(
                quiz,
                adding=Decimal(str(changes["points"])),
                replacing=Decimal(str(question.points)),
            )

        for field, value in changes.items():
            setattr(question, field, value)

        # Re-checked whenever *either* half of the key changes, because for
        # four of the types the key is not the options: editing a numeric
        # question's `settings.answer` to something unparseable, with no
        # option touched, would otherwise store a question that can never be
        # answered correctly.
        if options is not None or "settings" in changes:
            await self.session.flush()
            current = options
            if current is None:
                current = [
                    {
                        "option_text": o.option_text,
                        "is_correct": o.is_correct,
                        "order": o.order,
                        "match_text": o.match_text,
                    }
                    for o in _ordered_options(question)
                ]
            self._validate_options(question.question_type, current, question.settings)

        if options is not None:
            await self.quizzes.delete_options_for(question.id)
            await self.session.flush()
            for option in options:
                self.session.add(
                    QuestionOption(
                        question_id=question.id,
                        option_text=option["option_text"],
                        is_correct=option["is_correct"],
                        order=option["order"],
                        match_text=option.get("match_text"),
                    )
                )
            await self.session.flush()
            # Options were replaced wholesale underneath an already-loaded
            # collection; without expiring it the response would echo the
            # old answer key back.
            self.session.expire(question, ["options"])

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="question",
            entity_id=question.id,
            details={"fields": sorted(changes) + (["options"] if options is not None else [])},
        )
        return await self.quizzes.get_question(question_public_id)  # type: ignore[return-value]

    async def delete_question(self, question_public_id: uuid.UUID, *, actor: User) -> None:
        question = await self.quizzes.get_question(question_public_id)
        if question is None:
            raise NotFoundError("Question not found.")

        quiz = await self.get(question.quiz.public_id, actor=actor)
        await self._assert_question_bank_editable(quiz)

        entity_id = question.id
        await self.quizzes.delete_options_for(question.id)
        await self.session.delete(question)

        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="question",
            entity_id=entity_id,
        )

    # -- attempts ------------------------------------------------------------

    async def list_attempts(
        self,
        params: PageParams,
        *,
        actor: User,
        quiz_public_id: uuid.UUID | None = None,
        student_public_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[QuizAttempt], int]:
        quiz_id = None
        if quiz_public_id is not None:
            quiz_id = (await self.get(quiz_public_id, actor=actor)).id

        student_id = None
        if student_public_id is not None:
            student_id = (await self._load_user(student_public_id)).id

        visibility = await self.scopes.work_visibility(actor)
        return await self.attempts.search(
            params, visibility=visibility, quiz_id=quiz_id, student_id=student_id
        )

    async def get_attempt(self, public_id: uuid.UUID, *, actor: User) -> QuizAttempt:
        row = await self.attempts.get_by_public_id_full(public_id)
        if row is None:
            raise NotFoundError("Attempt not found.")

        visibility = await self.scopes.work_visibility(actor)
        if not visibility.unrestricted:
            reachable = (
                row.quiz.course_id in visibility.taught_course_ids
                or row.student_id in visibility.cared_for_student_ids
            )
            if not reachable:
                raise NotFoundError("Attempt not found.")
        return row

    async def start_attempt(self, quiz_public_id: uuid.UUID, *, actor: User) -> QuizAttempt:
        quiz = await self.get(quiz_public_id, actor=actor)

        if not quiz.is_published:
            raise ConflictError("This quiz is not open for attempts.")

        # §3: eligibility follows the quiz's own scope, so a student in another
        # batch is refused work that was never set for them.
        if not await self.targets.is_eligible(AssessmentTarget.of(quiz), actor.id):
            raise ConflictError("This quiz was not set for you.")

        # §9's availability period. `is_published` alone could not express "open
        # on Monday, closes Friday", so a quiz was either live or invisible.
        now = datetime.now(UTC)
        if quiz.available_from and now < quiz.available_from:
            raise ConflictError(
                "This quiz has not opened yet.",
                details={"opens_at": quiz.available_from.isoformat()},
            )
        if quiz.available_until and now > quiz.available_until:
            raise ConflictError(
                "This quiz has closed.",
                details={"closed_at": quiz.available_until.isoformat()},
            )

        in_progress = await self.attempts.get_in_progress(quiz_id=quiz.id, student_id=actor.id)
        if in_progress is not None and await self._auto_submit_if_expired(in_progress):
            # §9's `auto_submit_on_expiry`, and it fixes a real trap: an
            # attempt whose timer ran out while the tab was closed stayed
            # "in progress" for ever, so the student was refused every
            # further attempt and the tutor saw a result that never arrived.
            in_progress = None
        if in_progress is not None:
            # Without this, the attempt limit is trivially bypassed: open
            # several at once and submit only the best one.
            raise ConflictError(
                "You already have an attempt in progress for this quiz.",
                details={"attempt_id": str(in_progress.public_id)},
            )

        used = await self.attempts.count_for_student(quiz_id=quiz.id, student_id=actor.id)
        if used >= quiz.attempts_allowed:
            raise ConflictError(
                "You have used all attempts for this quiz.",
                details={"attempts_allowed": quiz.attempts_allowed, "used": used},
            )

        attempt = QuizAttempt(
            quiz_id=quiz.id,
            student_id=actor.id,
            started_at=datetime.now(UTC),
            attempt_number=used + 1,
        )
        await self.attempts.add_and_flush(attempt)

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="quiz_attempt",
            entity_id=attempt.id,
            details={"quiz": quiz.title, "attempt_number": attempt.attempt_number},
        )
        return await self.attempts.get_by_public_id_full(attempt.public_id)  # type: ignore[return-value]

    async def submit_attempt(
        self, public_id: uuid.UUID, answers: Sequence[AnswerInput], *, actor: User
    ) -> QuizAttempt:
        attempt = await self.attempts.get_by_public_id_full(public_id)
        if attempt is None:
            raise NotFoundError("Attempt not found.")

        if attempt.student_id != actor.id:
            # Only the sitter may submit their own attempt -- and a stranger
            # must not learn the attempt exists.
            raise NotFoundError("Attempt not found.")

        if attempt.finished_at is not None:
            raise ConflictError("This attempt has already been submitted.")

        quiz = attempt.quiz
        now = datetime.now(UTC)

        cutoff = self._cutoff(attempt)
        late = cutoff is not None and now > cutoff

        if late and quiz.auto_submit_on_expiry:
            # The timer is a limit, not a suggestion, when the quiz says so.
            # Refusing writes nothing -- the attempt is closed on the
            # student's next `start_attempt`, or by `close_expired_attempts`,
            # because recording the closure *and* raising from the same
            # transaction would roll the closure back.
            raise ConflictError(
                "The time limit for this attempt has passed and it can no longer be submitted.",
                details={"expired_at": cutoff.isoformat() if cutoff else None},
            )

        # Only the questions this sitting was actually served. A quiz drawing
        # a sample from a bank would otherwise be marked out of the whole
        # bank, so a student answering all ten of their ten questions
        # correctly would score 20% of a fifty-question quiz.
        paper = self._paper_for(quiz, attempt, await self.quizzes.questions_for(quiz.id))
        questions = {q.public_id: q for q, _options in paper}
        unknown = [str(a.question_id) for a in answers if a.question_id not in questions]
        if unknown:
            raise ValidationError(
                "Some answers reference questions that are not part of this quiz.",
                details={"unknown_questions": sorted(unknown)},
            )

        answers_by_question = {a.question_id: a for a in answers}
        negative = self._negative_marking(quiz)

        for question in questions.values():
            given = answers_by_question.get(question.public_id)
            score, stored = self._grade_one(question, given, negative_marking=negative)
            self.session.add(
                QuizAnswer(
                    attempt_id=attempt.id,
                    question_id=question.id,
                    selected_options=stored,
                    score_awarded=score,
                )
            )

        attempt.finished_at = now
        attempt.submitted_late = late
        await self.session.flush()
        await self._recompute_score(attempt)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="quiz_attempt",
            entity_id=attempt.id,
            details={"submitted_late": late, "score": str(attempt.score) if attempt.score is not None else None},
        )

        self.session.expire(attempt, ["answers"])
        return await self.attempts.get_by_public_id_full(public_id)  # type: ignore[return-value]

    async def grade_attempt(
        self, public_id: uuid.UUID, payload: GradeAttemptRequest, *, actor: User
    ) -> QuizAttempt:
        """Score the questions auto-grading cannot mark (short answer, essay)."""
        attempt = await self.get_attempt(public_id, actor=actor)

        if attempt.finished_at is None:
            raise ConflictError("This attempt has not been submitted yet.")

        questions = {q.public_id: q for q in await self.quizzes.questions_for(attempt.quiz_id)}
        answers_by_question = {a.question_id: a for a in attempt.answers}

        for entry in payload.answers:
            question = questions.get(entry.question_id)
            if question is None:
                raise ValidationError(
                    "That question is not part of this quiz.",
                    details={"question_id": str(entry.question_id)},
                )
            if entry.score_awarded > question.points:
                raise ValidationError(
                    "Score exceeds the question's points.",
                    details={
                        "question_id": str(entry.question_id),
                        "points": str(question.points),
                        "given": str(entry.score_awarded),
                    },
                )
            answer = answers_by_question.get(question.id)
            if answer is None:
                raise ValidationError(
                    "No answer recorded for that question.",
                    details={"question_id": str(entry.question_id)},
                )
            answer.score_awarded = entry.score_awarded

        if payload.feedback is not None:
            attempt.feedback = payload.feedback

        await self.session.flush()
        await self._recompute_score(attempt)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="quiz_attempt",
            entity_id=attempt.id,
            details={"manually_graded": len(payload.answers)},
        )
        return await self.attempts.get_by_public_id_full(public_id)  # type: ignore[return-value]

    # -- the clock (spec §9's `auto_submit_on_expiry`) ------------------------

    @staticmethod
    def _cutoff(attempt: QuizAttempt) -> datetime | None:
        """The last instant this attempt may still be submitted.

        `None` for an untimed quiz, which has no cutoff at all rather than an
        infinite one -- callers check for `None` instead of comparing against
        a sentinel date.

        The grace is wall-clock slack for the round trip and a slow client,
        not extra exam time: it is the same window that decides whether a
        submission is stamped late.
        """
        minutes = attempt.quiz.duration_minutes
        if not minutes:
            return None
        return attempt.started_at + timedelta(minutes=minutes) + _SUBMIT_GRACE

    async def _auto_submit_if_expired(self, attempt: QuizAttempt) -> bool:
        """Close an attempt the clock has ended. Returns whether it did.

        Only for a quiz that asked for it: with `auto_submit_on_expiry` off
        the timer is advisory, and a late submission is accepted and stamped
        `submitted_late` instead.

        **What gets marked is what the server has, which is nothing.** No
        answer is stored until the student presses submit, so an attempt
        closed this way scores zero on every machine-marked question. That is
        the honest outcome of "they did not submit in time", and it is better
        than the alternative this replaces -- an attempt stuck in progress for
        ever, blocking every further attempt the student was entitled to. It
        is also the strongest argument for saving answers as they are chosen,
        which this system does not yet do.

        `finished_at` is the cutoff, not now: the attempt ended when the time
        ran out, and recording the moment somebody happened to notice would
        put a false duration on the record.
        """
        if attempt.finished_at is not None or not attempt.quiz.auto_submit_on_expiry:
            return False
        cutoff = self._cutoff(attempt)
        if cutoff is None or datetime.now(UTC) <= cutoff:
            return False

        paper = self._paper_for(
            attempt.quiz, attempt, await self.quizzes.questions_for(attempt.quiz_id)
        )
        answered = {a.question_id for a in attempt.answers}
        negative = self._negative_marking(attempt.quiz)
        for question, _options in paper:
            if question.id in answered:
                continue
            score, stored = self._grade_one(question, None, negative_marking=negative)
            self.session.add(
                QuizAnswer(
                    attempt_id=attempt.id,
                    question_id=question.id,
                    selected_options=stored,
                    score_awarded=score,
                )
            )

        attempt.finished_at = cutoff
        attempt.auto_submitted = True
        await self.session.flush()
        await self._recompute_score(attempt)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=attempt.student_id,
            actor_email=None,
            entity_type="quiz_attempt",
            entity_id=attempt.id,
            details={"auto_submitted": True, "expired_at": cutoff.isoformat()},
        )
        return True

    async def close_expired_attempts(
        self, quiz_public_id: uuid.UUID, *, actor: User
    ) -> int:
        """Close every attempt on this quiz that the clock has ended.

        The recovery action for the gap `_auto_submit_if_expired` leaves: a
        student whose attempts are all used up never calls `start_attempt`
        again, so nothing would ever close their abandoned sitting and the
        tutor would be left marking a result that cannot arrive. There is no
        scheduler in this system, so somebody has to be able to ask.

        Gated on marking rather than authoring: it finalises results, which is
        the marker's job, and it changes no question.
        """
        quiz = await self.get(quiz_public_id, actor=actor)
        if not await self._can_mark(actor):
            raise AuthorizationError("You may not close attempts on this quiz.")

        rows = await self.attempts.list_in_progress(quiz.id)
        closed = 0
        for attempt in rows:
            if await self._auto_submit_if_expired(attempt):
                closed += 1

        if closed:
            audit_service.record(
                self.session,
                action=AuditAction.UPDATE,
                actor_user_id=actor.id,
                actor_email=actor.email,
                entity_type="quiz",
                entity_id=quiz.id,
                details={"expired_attempts_closed": closed},
            )
        return closed

    # -- releasing results (spec §9, §14) ------------------------------------

    async def release_results(
        self, public_id: uuid.UUID, is_released: bool, *, actor: User
    ) -> Quiz:
        """Release (or withhold) marks for a quiz that does not show them.

        The separate, deliberate act §14 requires, and the thing
        `show_result_immediately` was waiting for: with that setting off, a
        marked attempt's score was withheld from the student with no way for
        anybody to ever release it, because nothing could.

        Refused on a quiz that shows results immediately, rather than
        accepted and ignored: such a quiz is already released by definition,
        and a tutor pressing a button that does nothing would believe marks
        had just gone out.
        """
        quiz = await self.get(public_id, actor=actor)
        if not await self._can_mark(actor):
            raise AuthorizationError("You may not release results for this quiz.")

        if quiz.show_result_immediately:
            raise ConflictError(
                "This quiz shows results as soon as they are marked, so there is "
                "nothing to release. Turn off 'show results immediately' first."
            )

        already = quiz.results_released_at is not None
        quiz.results_released_at = datetime.now(UTC) if is_released else None

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="quiz",
            entity_id=quiz.id,
            details={"results_released": is_released},
        )

        # Only the transition into release, and only once -- the same rule
        # `set_published` follows. Withholding is deliberately quiet: "your
        # result is available" arriving as it is taken back is worse than
        # silence.
        if is_released and not already:
            await self._announce_results(quiz)
        return quiz

    async def _announce_results(self, quiz: Quiz) -> None:
        """Tell the students who actually have a marked attempt.

        Not everyone eligible: a student who never sat it has nothing to
        read, and a notification pointing at nothing is a worse message than
        none. Guardians get their own code rather than a copy, because every
        description in the catalogue is written in the second person about its
        subject.
        """
        student_ids = sorted(await self.attempts.marked_student_ids(quiz.id))
        if not student_ids:
            return

        meta = {"quiz_id": str(quiz.public_id)}
        notifications = NotificationService(self.session)
        await notifications.notify_many(
            student_ids,
            type_=NotificationType.QUIZ_RESULT_PUBLISHED,
            title=f"Result published: {quiz.title}",
            body="Your mark is now available.",
            meta=meta,
        )
        await notifications.notify_guardians_of(
            student_ids,
            type_=NotificationType.WARD_QUIZ_RESULT_PUBLISHED,
            title=f"Result published for {{student}}: {quiz.title}",
            body="The mark is now available.",
            meta=meta,
        )

    async def results_visible_to(self, attempt: QuizAttempt, *, actor: User) -> bool:
        """Whether this reader may see this attempt's mark.

        Three cases, and the middle one is the feature:

        * staff who can mark see everything, always -- they are the ones
          entering the marks;
        * a quiz with `show_result_immediately` off withholds the score from
          the student *and their care circle* until it is released, exactly as
          an exam does. Releasing to the student but not the parent, or the
          other way round, would be a leak in one direction and a bug in the
          other;
        * anything else is visible as soon as it is marked, which is what
          every quiz did before this existed.
        """
        if await self._can_mark(actor):
            return True
        if attempt.quiz.show_result_immediately:
            return True
        return attempt.quiz.results_released_at is not None

    # -- grading engine ------------------------------------------------------

    @staticmethod
    def _negative_marking(quiz: Quiz) -> Decimal:
        policy = quiz.grading_policy or {}
        if not isinstance(policy, dict):
            return Decimal("0")
        try:
            value = Decimal(str(policy.get("negative_marking", 0)))
        except Exception:  # noqa: BLE001 - a malformed policy must not break grading
            return Decimal("0")
        return value if value > 0 else Decimal("0")

    @staticmethod
    def _grade_one(
        question: Question,
        given: AnswerInput | None,
        *,
        negative_marking: Decimal,
    ) -> tuple[Decimal | None, dict]:
        """Return ``(score_awarded, stored_answer)``.

        `None` means "a human still has to mark this" -- distinct from
        `Decimal(0)`, which means "marked, and wrong". Conflating them would
        make an unmarked essay look like a zero.
        """
        if question.question_type not in AUTO_GRADABLE:
            return None, {"text": (given.text_answer if given else None)}

        points = Decimal(str(question.points))
        kind = question.question_type

        if kind is QuestionType.ORDERING:
            sequence = list(given.selected_option_ids or []) if given else []
            # Stored in the order given, never sorted: the sequence *is* the
            # answer, and `sorted()` would throw it away and mark everyone
            # who got it right as wrong.
            stored = {"ordered_option_ids": sequence}
            if not sequence:
                return Decimal("0"), stored
            correct_sequence = [o.id for o in _ordered_options(question)]
            return (
                (points, stored)
                if sequence == correct_sequence
                else (points * negative_marking * Decimal("-1"), stored)
            )

        if kind is QuestionType.MATCHING:
            pairs = dict(given.matches or {}) if given else {}
            stored = {"matches": pairs}
            if not pairs:
                return Decimal("0"), stored
            expected = {
                str(o.id): _normalise(o.match_text or "")
                for o in question.options
            }
            answered = {str(k): _normalise(str(v)) for k, v in pairs.items()}
            # All-or-nothing, like MCQ_MULTIPLE: partial credit needs a rule
            # nobody has specified, and inventing one would silently decide
            # how every matching question in the institution is marked.
            return (
                (points, stored)
                if answered == expected
                else (points * negative_marking * Decimal("-1"), stored)
            )

        if kind is QuestionType.FILL_BLANK:
            typed = (given.text_answer if given else None) or ""
            stored = {"text": typed or None}
            if not typed.strip():
                return Decimal("0"), stored
            raw = question.settings if isinstance(question.settings, dict) else {}
            cased = bool(raw.get("case_sensitive"))
            accepted = [str(a) for a in (raw.get("accepted") or [])]
            got = _normalise(typed, fold=not cased)
            is_right = any(got == _normalise(a, fold=not cased) for a in accepted)
            return (
                (points, stored)
                if is_right
                else (points * negative_marking * Decimal("-1"), stored)
            )

        if kind is QuestionType.NUMERIC:
            typed = (given.text_answer if given else None) or ""
            stored = {"text": typed or None}
            if not typed.strip():
                return Decimal("0"), stored
            raw = question.settings if isinstance(question.settings, dict) else {}
            try:
                target = Decimal(str(raw.get("answer")))
                tolerance = Decimal(str(raw.get("tolerance") or 0))
                got = Decimal(_numeric(typed))
            except (InvalidOperation, ValueError, TypeError):
                # An unparseable answer is **wrong, not unmarkable**: the
                # student typed something that is not a number into a numeric
                # question. A malformed *key* lands here too, which is why
                # `answer_key_problem` refuses one at authoring time.
                return Decimal("0"), stored
            is_right = abs(got - target) <= abs(tolerance)
            return (
                (points, stored)
                if is_right
                else (points * negative_marking * Decimal("-1"), stored)
            )

        selected = set(given.selected_option_ids or []) if given else set()
        stored = {"option_ids": sorted(selected)}

        if not selected:
            # Unanswered: zero, but never a negative-marking penalty --
            # deducting for leaving a question blank punishes not guessing.
            return Decimal("0"), stored

        correct = {o.id for o in question.options if o.is_correct}

        if kind in (QuestionType.MCQ_SINGLE, QuestionType.TRUE_FALSE):
            is_right = len(selected) == 1 and selected == correct
        else:
            # MCQ_MULTIPLE is all-or-nothing: partial credit needs a rule
            # nobody has specified, and inventing one would silently decide
            # how every multi-select question is marked.
            is_right = selected == correct

        if is_right:
            return points, stored
        return (points * negative_marking * Decimal("-1")), stored

    async def _recompute_score(self, attempt: QuizAttempt) -> None:
        """Recompute the attempt's percentage score and pass flag.

        Left as `None` while any answer is still unmarked: reporting a score
        that ignores an ungraded essay would understate the student, and
        marking them failed on it would be worse.

        **The denominator comes from the answer rows, not from the quiz.**
        There is one row per question this sitting was served, so a quiz that
        draws ten questions from a bank of fifty is marked out of those ten.
        The caller used to pass the question list, and both callers passed the
        whole bank -- which was right only while every attempt got every
        question.
        """
        rows = (
            (
                await self.session.execute(
                    select(QuizAnswer)
                    .options(selectinload(QuizAnswer.question))
                    .where(QuizAnswer.attempt_id == attempt.id)
                )
            )
            .scalars()
            .all()
        )

        if any(r.score_awarded is None for r in rows):
            attempt.score = None
            attempt.is_passed = None
            return

        total_points = sum(
            (Decimal(str(r.question.points)) for r in rows), Decimal("0")
        )
        earned = sum((Decimal(str(r.score_awarded)) for r in rows), Decimal("0"))
        # Negative marking can drive a total below zero; a negative percentage
        # is not a meaningful result, so the floor is zero.
        earned = max(earned, Decimal("0"))

        percentage = (
            (earned / total_points * Decimal("100")).quantize(Decimal("0.01"))
            if total_points > 0
            else Decimal("0")
        )
        attempt.score = percentage
        attempt.is_passed = percentage >= Decimal(str(attempt.quiz.passing_score))
        await self._record_in_gradebook(attempt)

    async def _record_in_gradebook(self, attempt: QuizAttempt) -> None:
        """Push a finished, fully-marked attempt into the grade book (§9, §47).

        Hooked here rather than at the two call sites because this is where a
        result *becomes* final -- on submission for an auto-graded quiz, and
        on the tutor's marking for one with essays in it. A third entry point
        added later gets this for free.

        **Reached only with a score set.** `_recompute_score` returns before
        this line whenever any answer is still unmarked, so there is no
        `score is None` guard here: one was written, and no test could tell it
        from its absence because nothing can reach it. A caller added later
        that does not hold that invariant must check before calling.

        **Fail-open, and loudly.** The marking has already happened and is
        already committed to as far as the student is concerned; refusing it
        because a derived row could not be written would discard real work to
        protect a cache. `sync_batch` exists precisely to repair what this
        loses, so the cost of a failure here is bounded and recoverable --
        which is why it is a warning rather than a raise.
        """
        try:
            await GradeBookService(self.session).record_component(
                student_id=attempt.student_id,
                course_id=attempt.quiz.course_id,
                batch_id=attempt.quiz.batch_id,
                component_type=GradeComponentType.QUIZ,
                reference_id=attempt.id,
                # `attempt.score` is already a percentage, so the denominator
                # is 100 rather than the quiz's raw points -- the same choice
                # `_sync_quizzes` makes, and they must agree or the sweep
                # would rewrite every row this one wrote.
                score=Decimal(str(attempt.score)),
                max_score=Decimal("100"),
            )
        except Exception:  # noqa: BLE001 - a derived row must not undo a mark
            logger.exception(
                "Failed to record quiz attempt in the grade book",
                extra={"attempt_id": attempt.id},
            )

    # -- guards --------------------------------------------------------------

    @staticmethod
    def _validate_options(
        question_type: QuestionType,
        options: list[dict],
        settings: dict | None = None,
    ) -> None:
        """The same rules the create schema applies, re-applied on an edit.

        One rule set in `schemas/quiz.py`, raised here as the API's own
        `ValidationError` -- the rules had been written out twice, and the
        copies had already drifted apart once the four new question types
        arrived with keys that are not options at all.
        """
        problem = answer_key_problem(question_type, options, settings)
        if problem:
            raise ValidationError(f"{problem}.")

    async def _assert_question_bank_editable(self, quiz: Quiz) -> None:
        if await self._has_attempts(quiz.id):
            # Editing the answer key after students have sat the quiz
            # retroactively changes whether their answers were right.
            raise ConflictError(
                "This quiz already has attempts; its questions can no longer be changed."
            )

    async def _has_attempts(self, quiz_id: int) -> bool:
        stmt = select(QuizAttempt.id).where(QuizAttempt.quiz_id == quiz_id).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def _can_author(self, actor: User) -> bool:
        from backend.api.deps import resolve_permissions
        from backend.core.permissions import Action, Module, perm

        return perm(Module.QUIZ, Action.UPDATE) in resolve_permissions(actor)

    async def _can_mark(self, actor: User) -> bool:
        """Holds the marking permission.

        The same split `ExamService` makes, and for the same reason: a
        Guardian holds `grade.read` and must not be handed a withheld mark,
        while a Tutor who marks the paper obviously sees it. Asked as a
        permission rather than a role so a custom role with the same job
        behaves the same way.
        """
        from backend.api.deps import resolve_permissions
        from backend.core.permissions import Action, Module, perm

        return perm(Module.QUIZ, Action.GRADE) in resolve_permissions(actor)

    async def _assert_enrolled_in_course(self, student: User, course_id: int) -> None:
        stmt = (
            select(Enrollments.enrollment_id)
            .join(Batch, Batch.id == Enrollments.batch_id)
            .where(
                Enrollments.student_id == student.id,
                Batch.course_id == course_id,
                Enrollments.status.in_(ACTIVE_STATUSES),
            )
            .limit(1)
        )
        if (await self.session.execute(stmt)).scalar_one_or_none() is None:
            raise ConflictError("You are not enrolled in this course.")

    async def _load_user(self, public_id: uuid.UUID) -> User:
        stmt = select(User).where(User.public_id == public_id)
        user = (await self.session.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise NotFoundError("User not found.")
        return user

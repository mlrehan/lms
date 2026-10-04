"""Quizzes, questions and attempts (spec §13).

**`QuizAttempt.score` is a percentage, not raw points.** It is stored that
way because the only thing it is ever compared against is
`Quiz.passing_score` (documented in the model as "e.g. 70.00"), and because a
percentage stays meaningful if the question set changes -- raw points would
silently mean something different after an edit. Raw points earned per
question remain on each `QuizAnswer.score_awarded`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
)
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.course_service import CourseService
from backend.services.assessment_scope import (
    AssessmentScopeResolver,
    AssessmentTarget,
    validate as validate_scope,
)
from backend.services.notification_service import NotificationService
from backend.core.notification_types import NotificationType
from backend.services.scope import ScopeResolver
from backend.utils.enums import QuestionType

# Wall-clock slack allowed past a quiz's `duration_minutes` before the
# submission is stamped late. Covers the round trip and a slow client; it is
# not a grace period on the exam itself.
_SUBMIT_GRACE = timedelta(seconds=30)


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
        quiz = await self.get(public_id, actor=actor)
        return await self.quizzes.questions_for(quiz.id)

    async def add_question(
        self, public_id: uuid.UUID, payload: QuestionCreateRequest, *, actor: User
    ) -> Question:
        quiz = await self.get(public_id, actor=actor)
        await self._assert_question_bank_editable(quiz)

        question = Question(
            quiz_id=quiz.id,
            question_text=payload.question_text,
            question_type=payload.question_type,
            points=payload.points,
            order=payload.order,
            settings=payload.settings,
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

        for field, value in changes.items():
            setattr(question, field, value)

        if options is not None:
            self._validate_options(question.question_type, options)
            await self.quizzes.delete_options_for(question.id)
            await self.session.flush()
            for option in options:
                self.session.add(
                    QuestionOption(
                        question_id=question.id,
                        option_text=option["option_text"],
                        is_correct=option["is_correct"],
                        order=option["order"],
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

        late = False
        if quiz.duration_minutes:
            deadline = attempt.started_at + timedelta(minutes=quiz.duration_minutes) + _SUBMIT_GRACE
            late = now > deadline

        questions = {q.public_id: q for q in await self.quizzes.questions_for(quiz.id)}
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
        await self._recompute_score(attempt, questions.values())

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
        await self._recompute_score(attempt, questions.values())

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

        selected = set(given.selected_option_ids or []) if given else set()
        stored = {"option_ids": sorted(selected)}

        if not selected:
            # Unanswered: zero, but never a negative-marking penalty --
            # deducting for leaving a question blank punishes not guessing.
            return Decimal("0"), stored

        correct = {o.id for o in question.options if o.is_correct}
        points = Decimal(str(question.points))

        if question.question_type in (QuestionType.MCQ_SINGLE, QuestionType.TRUE_FALSE):
            is_right = len(selected) == 1 and selected == correct
        else:
            # MCQ_MULTIPLE is all-or-nothing: partial credit needs a rule
            # nobody has specified, and inventing one would silently decide
            # how every multi-select question is marked.
            is_right = selected == correct

        if is_right:
            return points, stored
        return (points * negative_marking * Decimal("-1")), stored

    async def _recompute_score(
        self, attempt: QuizAttempt, questions: Sequence[Question]
    ) -> None:
        """Recompute the attempt's percentage score and pass flag.

        Left as `None` while any answer is still unmarked: reporting a score
        that ignores an ungraded essay would understate the student, and
        marking them failed on it would be worse.
        """
        rows = (
            (
                await self.session.execute(
                    select(QuizAnswer).where(QuizAnswer.attempt_id == attempt.id)
                )
            )
            .scalars()
            .all()
        )

        if any(r.score_awarded is None for r in rows):
            attempt.score = None
            attempt.is_passed = None
            return

        total_points = sum((Decimal(str(q.points)) for q in questions), Decimal("0"))
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

    # -- guards --------------------------------------------------------------

    @staticmethod
    def _validate_options(question_type: QuestionType, options: list[dict]) -> None:
        correct = [o for o in options if o.get("is_correct")]
        if question_type in AUTO_GRADABLE:
            if len(options) < 2:
                raise ValidationError(
                    f"{question_type.value} requires at least two options."
                )
            if not correct:
                raise ValidationError(
                    f"{question_type.value} requires at least one correct option."
                )
            if question_type in (QuestionType.MCQ_SINGLE, QuestionType.TRUE_FALSE) and len(correct) > 1:
                raise ValidationError(
                    f"{question_type.value} allows exactly one correct option."
                )
        elif options:
            raise ValidationError(
                f"{question_type.value} is graded manually and takes no options."
            )

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

"""Reuse one assessment for other batches, sessions, courses or named students.

A reuse is a **copy that points back** (`copied_from_id`), not a second
pointer to one shared row. Each copy has its own recipients, deadline, state,
submissions, attempts and marks; it also owns its content, on purpose --
editing one batch's paper after its students sat it must not change what
another batch is about to sit. What is shared is the authoring effort and the
lineage, which is what a template is for.

Every copy goes through the service's own ``create``. That is the whole
design: the course permission check, the scope resolution (a session names its
batch, a batch names its course), the named-student rule, the draft/publish
announcement and the audit entry are the ones a hand-made assessment gets,
because they are the same code. A quiz's questions are then added through
``add_question``, which applies the answer-key rules and the paper total.

The batch of copies is all or nothing: the caller's transaction rolls back on
the first refusal, so "copied to 3 of 5 batches" cannot happen.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ValidationError
from backend.models.identity.user import User
from backend.utils.enums import AssessmentScope, AssessmentState

#: One request may fan out to this many targets.
MAX_TARGETS = 20


@dataclass(frozen=True)
class CopyTarget:
    scope: AssessmentScope
    course_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    student_ids: Sequence[uuid.UUID] | None = None


class AssessmentReuseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _course_public_id(self, target: CopyTarget, source_course_id: int) -> uuid.UUID:
        """The course the copy is created under: named, derived, or the source's."""
        from sqlalchemy import select

        from backend.models.batch import Batch, BatchSession
        from backend.models.course import Course

        if target.course_id is not None:
            return target.course_id
        if target.session_id is not None:
            stmt = (
                select(Course.public_id)
                .join(Batch, Batch.course_id == Course.id)
                .join(BatchSession, BatchSession.batch_id == Batch.id)
                .where(BatchSession.public_id == target.session_id)
            )
        elif target.batch_id is not None:
            stmt = select(Course.public_id).join(Batch, Batch.course_id == Course.id).where(
                Batch.public_id == target.batch_id
            )
        else:
            stmt = select(Course.public_id).where(Course.id == source_course_id)
        found = (await self.session.execute(stmt)).scalar_one_or_none()
        if found is None:
            raise ValidationError("That batch or session does not exist.")
        return found

    @staticmethod
    def _check(targets: Sequence[CopyTarget]) -> None:
        if not targets:
            raise ValidationError("Choose at least one batch, session, course or group of students.")
        if len(targets) > MAX_TARGETS:
            raise ValidationError(f"At most {MAX_TARGETS} copies can be made at once.")

    @staticmethod
    def _mark_copy(row: Any, source: Any) -> None:
        row.copied_from_id = source.id

    async def copy_assignment(
        self,
        source_public_id: uuid.UUID,
        targets: Sequence[CopyTarget],
        *,
        actor: User,
        due_date: datetime | None,
        publish: bool,
    ) -> list[Any]:
        from backend.schemas.assignment import AssignmentCreateRequest
        from backend.services.assignment_service import AssignmentService

        self._check(targets)
        service = AssignmentService(self.session)
        source = await service.get(source_public_id, actor=actor)
        out = []
        for target in targets:
            payload = AssignmentCreateRequest(
                title=source.title,
                description=source.description,
                due_date=due_date or source.due_date,
                max_score=source.max_score,
                submission_type=source.submission_type,
                rubric=source.rubric,
                allow_late_submissions=source.allow_late_submissions,
                scope=target.scope,
                batch_id=target.batch_id,
                session_id=target.session_id,
                student_ids=list(target.student_ids) if target.student_ids else None,
                state=AssessmentState.PUBLISHED if publish else AssessmentState.DRAFT,
                available_from=source.available_from,
                passing_score=source.passing_score,
                weight=source.weight,
                allowed_file_types=source.allowed_file_types,
                max_upload_mb=source.max_upload_mb,
                allow_multiple_submissions=source.allow_multiple_submissions,
                allow_resubmission=source.allow_resubmission,
                late_penalty_percent_per_day=source.late_penalty_percent_per_day,
            )
            course = await self._course_public_id(target, source.course_id)
            row = await service.create(course, payload, actor=actor)
            self._mark_copy(row, source)
            out.append(row)
        await self.session.flush()
        return out

    async def copy_quiz(
        self,
        source_public_id: uuid.UUID,
        targets: Sequence[CopyTarget],
        *,
        actor: User,
        publish: bool,
    ) -> list[Any]:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from backend.models.quiz import Question
        from backend.schemas.quiz import OptionInput, QuestionCreateRequest, QuizCreateRequest
        from backend.services.quiz_service import QuizService

        self._check(targets)
        service = QuizService(self.session)
        source = await service.get(source_public_id, actor=actor)
        if not AssessmentAccessGate.may_copy_answer_key(source, actor):
            # Copying a quiz copies its answer key into a quiz the caller
            # owns. Only somebody who may already read that key may do it.
            raise ValidationError("Only the quiz's author can reuse its questions.")
        questions = (
            await self.session.execute(
                select(Question)
                .where(Question.quiz_id == source.id)
                .options(selectinload(Question.options))
                .order_by(Question.order, Question.id)
            )
        ).scalars().all()
        if publish and not questions:
            raise ValidationError("A quiz with no questions cannot be published.")

        out = []
        for target in targets:
            payload = QuizCreateRequest(
                title=source.title,
                instructions=source.instructions,
                duration_minutes=source.duration_minutes,
                attempts_allowed=source.attempts_allowed,
                passing_score=source.passing_score,
                total_marks=source.total_marks,
                shuffle_questions=source.shuffle_questions,
                is_auto_graded=source.is_auto_graded,
                grading_policy=source.grading_policy,
                scope=target.scope,
                batch_id=target.batch_id,
                session_id=target.session_id,
                student_ids=list(target.student_ids) if target.student_ids else None,
                available_from=source.available_from,
                available_until=source.available_until,
                shuffle_answers=source.shuffle_answers,
                questions_per_attempt=source.questions_per_attempt,
                show_result_immediately=source.show_result_immediately,
                show_correct_answers=source.show_correct_answers,
                show_explanations=source.show_explanations,
                auto_submit_on_expiry=source.auto_submit_on_expiry,
                weight=source.weight,
            )
            course = await self._course_public_id(target, source.course_id)
            row = await service.create(course, payload, actor=actor)
            self._mark_copy(row, source)
            for q in questions:
                await service.add_question(
                    row.public_id,
                    QuestionCreateRequest(
                        question_text=q.question_text,
                        question_type=q.question_type,
                        points=q.points,
                        order=q.order or 0,
                        settings=q.settings,
                        explanation=q.explanation,
                        options=[
                            OptionInput(
                                option_text=o.option_text,
                                is_correct=bool(o.is_correct),
                                order=o.order or 0,
                                match_text=o.match_text,
                            )
                            for o in sorted(q.options, key=lambda o: (o.order or 0, o.id))
                        ],
                    ),
                    actor=actor,
                )
            if publish:
                await service.set_published(row.public_id, True, actor=actor)
            out.append(row)
        await self.session.flush()
        return out

    async def copy_exam(
        self,
        source_public_id: uuid.UUID,
        targets: Sequence[CopyTarget],
        *,
        actor: User,
        scheduled_at: datetime | None,
        publish: bool,
    ) -> list[Any]:
        from backend.schemas.exam import ExamCreateRequest
        from backend.services.exam_service import ExamService

        self._check(targets)
        service = ExamService(self.session)
        source = await service.get(source_public_id, actor=actor)
        out = []
        for target in targets:
            course = await self._course_public_id(target, source.course_id)
            payload = ExamCreateRequest(
                title=source.title,
                exam_type=source.exam_type,
                scheduled_at=scheduled_at or source.scheduled_at,
                total_marks=source.total_marks,
                passing_marks=source.passing_marks,
                duration_minutes=source.duration_minutes,
                venue_or_link=source.venue_or_link,
                instructions=source.instructions,
                course_id=course,
                batch_id=target.batch_id,
                session_id=target.session_id,
                scope=target.scope,
                student_ids=list(target.student_ids) if target.student_ids else None,
                is_online=source.is_online,
                weight=source.weight,
            )
            row = await service.create(payload, actor=actor)
            self._mark_copy(row, source)
            if publish:
                await service.set_published(row.public_id, True, actor=actor)
            out.append(row)
        await self.session.flush()
        return out


class AssessmentAccessGate:
    @staticmethod
    def may_copy_answer_key(quiz: Any, actor: User) -> bool:
        from backend.services.assessment_access import AssessmentAccess

        return AssessmentAccess.may_manage(quiz, actor)

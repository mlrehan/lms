"""Quiz, question and attempt queries."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.orm import selectinload

from backend.models.quiz import Question, QuestionOption, Quiz, QuizAnswer, QuizAttempt
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams

if TYPE_CHECKING:
    from backend.services.scope import Scope, WorkVisibility


class QuizRepository(BaseRepository[Quiz]):
    model = Quiz

    def _base(self) -> Select[tuple[Quiz]]:
        return select(Quiz).options(selectinload(Quiz.course))

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> Quiz | None:
        stmt = self._base().where(Quiz.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def search(
        self,
        params: PageParams,
        *,
        scope: "Scope",
        course_id: int | None = None,
        published_only: bool = False,
    ) -> tuple[Sequence[Quiz], int]:
        stmt = scope.apply(self._base(), Quiz.course_id)
        if course_id is not None:
            stmt = stmt.where(Quiz.course_id == course_id)
        if published_only:
            stmt = stmt.where(Quiz.is_published.is_(True))
        stmt = stmt.order_by(Quiz.id.desc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def questions_for(self, quiz_id: int) -> list[Question]:
        """Questions with their options, in author-defined order."""
        stmt = (
            select(Question)
            .options(selectinload(Question.options))
            .where(Question.quiz_id == quiz_id)
            .order_by(Question.order, Question.id)
        )
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def get_question(self, public_id: uuid.UUID) -> Question | None:
        stmt = (
            select(Question)
            .options(selectinload(Question.options), selectinload(Question.quiz))
            .where(Question.public_id == public_id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def question_stats(self, quiz_id: int) -> tuple[int, float]:
        """``(question_count, total_points)`` without loading the questions."""
        stmt = select(func.count(), func.coalesce(func.sum(Question.points), 0)).where(
            Question.quiz_id == quiz_id
        )
        count, total = (await self.session.execute(stmt)).one()
        return int(count), total

    async def delete_options_for(self, question_id: int) -> None:
        for option in (
            (
                await self.session.execute(
                    select(QuestionOption).where(QuestionOption.question_id == question_id)
                )
            )
            .scalars()
            .all()
        ):
            await self.session.delete(option)


class AttemptRepository(BaseRepository[QuizAttempt]):
    model = QuizAttempt

    def _base(self) -> Select[tuple[QuizAttempt]]:
        return select(QuizAttempt).options(
            selectinload(QuizAttempt.quiz),
            selectinload(QuizAttempt.student),
            # The question's options come too: the attempt mapper renders
            # each answer as the option *text* a marker can read, and reaching
            # them lazily is a `MissingGreenlet` on an async session rather
            # than a slow query -- it fails the whole request.
            selectinload(QuizAttempt.answers)
            .selectinload(QuizAnswer.question)
            .selectinload(Question.options),
        )

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> QuizAttempt | None:
        stmt = self._base().where(QuizAttempt.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def count_for_student(self, *, quiz_id: int, student_id: int) -> int:
        stmt = select(func.count()).select_from(QuizAttempt).where(
            QuizAttempt.quiz_id == quiz_id,
            QuizAttempt.student_id == student_id,
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def get_in_progress(self, *, quiz_id: int, student_id: int) -> QuizAttempt | None:
        """An attempt that was started and never submitted.

        Used to stop a student opening a second attempt while one is still
        running -- otherwise the attempt limit is trivially bypassed by
        starting several and submitting the best.
        """
        stmt = self._base().where(
            QuizAttempt.quiz_id == quiz_id,
            QuizAttempt.student_id == student_id,
            QuizAttempt.finished_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_in_progress(self, quiz_id: int) -> list[QuizAttempt]:
        """Every unsubmitted attempt on one quiz, loaded ready to close.

        The full eager load, not a bare id list: closing an expired attempt
        grades the questions it never answered, which needs the quiz, its
        answers and their options -- and reaching any of those lazily on an
        async session raises `MissingGreenlet` rather than running a slow
        query.
        """
        stmt = self._base().where(
            QuizAttempt.quiz_id == quiz_id,
            QuizAttempt.finished_at.is_(None),
        )
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def marked_student_ids(self, quiz_id: int) -> set[int]:
        """Students with a submitted, fully-marked attempt on this quiz.

        Who "your result is available" is true for. A student still awaiting
        a tutor's mark on an essay is excluded: their score is `None`, and
        telling them it is ready would send them to an empty page.
        """
        stmt = select(QuizAttempt.student_id).where(
            QuizAttempt.quiz_id == quiz_id,
            QuizAttempt.finished_at.is_not(None),
            QuizAttempt.score.is_not(None),
        )
        return set((await self.session.execute(stmt)).scalars().all())

    async def search(
        self,
        params: PageParams,
        *,
        visibility: "WorkVisibility",
        quiz_id: int | None = None,
        student_id: int | None = None,
    ) -> tuple[Sequence[QuizAttempt], int]:
        stmt = self._base().join(Quiz, Quiz.id == QuizAttempt.quiz_id)
        stmt = visibility.apply(
            stmt,
            course_column=Quiz.course_id,
            student_column=QuizAttempt.student_id,
        )

        if quiz_id is not None:
            stmt = stmt.where(QuizAttempt.quiz_id == quiz_id)
        if student_id is not None:
            stmt = stmt.where(QuizAttempt.student_id == student_id)

        stmt = stmt.order_by(QuizAttempt.id.desc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]

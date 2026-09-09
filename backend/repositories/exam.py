"""Exam, invigilator and result queries."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import Select, false, func, or_, select
from sqlalchemy.orm import selectinload

from backend.models.exam import Exam, ExamInvigilator, ExamResult
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams

if TYPE_CHECKING:
    from backend.services.scope import Scope, WorkVisibility


class ExamRepository(BaseRepository[Exam]):
    model = Exam

    def _base(self) -> Select[tuple[Exam]]:
        return select(Exam).options(
            selectinload(Exam.course),
            selectinload(Exam.batch),
            selectinload(Exam.invigilators).selectinload(ExamInvigilator.tutor),
        )

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> Exam | None:
        stmt = self._base().where(Exam.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def search(
        self,
        params: PageParams,
        *,
        course_scope: "Scope",
        batch_scope: "Scope",
        invigilating_exam_ids: set[int] | None = None,
        published_only: bool = False,
    ) -> tuple[Sequence[Exam], int]:
        """An exam is reachable through *either* anchor, plus a third route:
        being assigned to invigilate it.

        A tutor invigilating an exam for a course they do not otherwise teach
        still needs to see it -- that is the entire point of an invigilator
        assignment, and scoping on course/batch alone would hide the exam
        from the person supervising it.
        """
        stmt = self._base()

        if not (course_scope.unrestricted or batch_scope.unrestricted):
            conditions = []
            if course_scope.ids:
                conditions.append(Exam.course_id.in_(course_scope.ids))
            if batch_scope.ids:
                conditions.append(Exam.batch_id.in_(batch_scope.ids))
            if invigilating_exam_ids:
                conditions.append(Exam.id.in_(invigilating_exam_ids))
            stmt = stmt.where(or_(*conditions)) if conditions else stmt.where(false())

        if published_only:
            stmt = stmt.where(Exam.is_published.is_(True))

        stmt = stmt.order_by(Exam.scheduled_at.desc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def invigilating_exam_ids(self, tutor_id: int) -> set[int]:
        stmt = select(ExamInvigilator.exam_id).where(ExamInvigilator.tutor_id == tutor_id)
        return set((await self.session.execute(stmt)).scalars().all())

    async def result_counts(self, exam_id: int) -> tuple[int, int]:
        """``(total_results, published_results)``."""
        stmt = select(
            func.count(),
            func.count().filter(ExamResult.is_published.is_(True)),
        ).where(ExamResult.exam_id == exam_id)
        total, published = (await self.session.execute(stmt)).one()
        return int(total), int(published)


class ExamResultRepository(BaseRepository[ExamResult]):
    model = ExamResult

    def _base(self) -> Select[tuple[ExamResult]]:
        return select(ExamResult).options(
            selectinload(ExamResult.exam),
            selectinload(ExamResult.student),
        )

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> ExamResult | None:
        stmt = self._base().where(ExamResult.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def existing_by_student(self, exam_id: int) -> dict[int, ExamResult]:
        stmt = self._base().where(ExamResult.exam_id == exam_id)
        rows = (await self.session.execute(stmt)).scalars().unique().all()
        return {r.student_id: r for r in rows}

    async def search(
        self,
        params: PageParams,
        *,
        visibility: "WorkVisibility",
        exam_id: int | None = None,
        student_id: int | None = None,
        include_unpublished: bool,
    ) -> tuple[Sequence[ExamResult], int]:
        stmt = self._base().join(Exam, Exam.id == ExamResult.exam_id)
        stmt = visibility.apply(
            stmt,
            course_column=Exam.course_id,
            student_column=ExamResult.student_id,
        )

        if not include_unpublished:
            # A result that has been recorded but not released must not reach
            # the student it belongs to -- spec §14 makes publication an
            # explicit, separate act from recording the mark.
            stmt = stmt.where(ExamResult.is_published.is_(True))

        if exam_id is not None:
            stmt = stmt.where(ExamResult.exam_id == exam_id)
        if student_id is not None:
            stmt = stmt.where(ExamResult.student_id == student_id)

        stmt = stmt.order_by(ExamResult.id.desc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]

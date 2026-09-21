"""Batch queries."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from backend.models.batch import Batch
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams
from backend.utils.enums import EnrollmentStatus

if TYPE_CHECKING:
    from backend.services.scope import Scope

# An enrollment occupies a seat only while it is live. DROPPED and CANCELLED
# free the seat; COMPLETED does too, since the batch has finished with them.
SEAT_OCCUPYING_STATUSES = (EnrollmentStatus.PENDING, EnrollmentStatus.CONFIRMED)


# The columns a batch list may be sorted by (a whitelist: `sort` comes from the query string).
SORTABLE = {
    "batch_code": Batch.batch_code, "course": Course.title, "start_date": Batch.start_date, "end_date": Batch.end_date,
    "enrolled": Batch.total_enrollments, "capacity": Batch.capacity, "fee": Batch.batch_fee, "method": Batch.training_method,
    "state": Batch.is_active,
}


class BatchRepository(BaseRepository[Batch]):
    model = Batch

    def _base(self) -> Select[tuple[Batch]]:
        return select(Batch).options(selectinload(Batch.course))

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> Batch | None:
        stmt = self._base().where(Batch.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_code(self, batch_code: str) -> Batch | None:
        stmt = select(Batch).where(func.lower(Batch.batch_code) == batch_code.strip().lower())
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def search(
        self,
        params: PageParams,
        *,
        scope: "Scope",
        course_id: int | None = None,
        is_active: bool | None = None,
        query: str | None = None,
        sort: str | None = None,
        descending: bool = False,
    ) -> tuple[Sequence[Batch], int]:
        stmt = scope.apply(self._base(), Batch.id)
        # The course title is searchable and sortable, so the list joins it once (it is also loaded, for display).
        stmt = stmt.join(Course, Course.id == Batch.course_id)

        if query:
            needle = f"%{query.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Batch.batch_code).like(needle),
                    func.lower(Course.title).like(needle),
                    func.lower(func.coalesce(Batch.training_method, "")).like(needle),
                    func.lower(func.coalesce(Batch.training_days, "")).like(needle),
                    func.lower(func.coalesce(Batch.notes, "")).like(needle),
                )
            )
        if course_id is not None:
            stmt = stmt.where(Batch.course_id == course_id)
        if is_active is not None:
            stmt = stmt.where(Batch.is_active.is_(is_active))

        column = SORTABLE.get(sort or "", Batch.batch_code)
        ordering = column.desc().nulls_last() if descending else column.asc().nulls_last()
        stmt = stmt.order_by(ordering, Batch.id)  # `id` last, so equal values keep a stable page order
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def occupied_seats(self, batch_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(Enrollments)
            .where(
                Enrollments.batch_id == batch_id,
                Enrollments.status.in_(SEAT_OCCUPYING_STATUSES),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def lock_for_enrollment(self, batch_id: int) -> Batch | None:
        """Re-read the batch row under `SELECT ... FOR UPDATE`.

        Capacity is checked and then acted on, which is a read-modify-write:
        without this lock two simultaneous enrollments both see the last free
        seat and both take it, overfilling the batch. Locking the batch row
        serialises enrollments *into that batch* while leaving every other
        batch unaffected.
        """
        stmt = select(Batch).where(Batch.id == batch_id).with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

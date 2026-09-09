"""Class session queries."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.orm import selectinload

from backend.models.attendance import Attendance
from backend.models.batch import Batch, BatchSession
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams

if TYPE_CHECKING:
    from backend.services.scope import Scope


class SessionRepository(BaseRepository[BatchSession]):
    model = BatchSession

    def _base(self) -> Select[tuple[BatchSession]]:
        return select(BatchSession).options(
            selectinload(BatchSession.batch).selectinload(Batch.course),
            selectinload(BatchSession.tutor),
        )

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> BatchSession | None:
        stmt = self._base().where(BatchSession.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def search(
        self,
        params: PageParams,
        *,
        scope: "Scope",
        batch_id: int | None = None,
        tutor_id: int | None = None,
        starts_after: datetime | None = None,
        starts_before: datetime | None = None,
    ) -> tuple[Sequence[BatchSession], int]:
        stmt = scope.apply(self._base(), BatchSession.id)

        if batch_id is not None:
            stmt = stmt.where(BatchSession.batch_id == batch_id)
        if tutor_id is not None:
            stmt = stmt.where(BatchSession.tutor_id == tutor_id)
        if starts_after is not None:
            stmt = stmt.where(BatchSession.session_start_time >= starts_after)
        if starts_before is not None:
            stmt = stmt.where(BatchSession.session_start_time <= starts_before)

        stmt = stmt.order_by(BatchSession.session_start_time.desc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def overlapping_for_tutor(
        self,
        *,
        tutor_id: int,
        start: datetime,
        end: datetime | None,
        exclude_session_id: int | None = None,
    ) -> BatchSession | None:
        """Find a session that would double-book this tutor.

        Only checked when an end time is known: with an open-ended session
        there is no interval to overlap, and inventing one (assuming an hour,
        say) would refuse bookings on a guess.
        """
        if end is None:
            return None

        stmt = self._base().where(
            BatchSession.tutor_id == tutor_id,
            BatchSession.session_end_time.is_not(None),
            # Standard interval overlap: existing.start < new.end
            # AND existing.end > new.start. Touching endpoints do not
            # overlap, so a 10:00-11:00 and an 11:00-12:00 are both fine.
            BatchSession.session_start_time < end,
            BatchSession.session_end_time > start,
        )
        if exclude_session_id is not None:
            stmt = stmt.where(BatchSession.id != exclude_session_id)

        return (await self.session.execute(stmt)).scalars().first()

    async def count_attendance(self, session_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(Attendance)
            .where(Attendance.session_id == session_id)
        )
        return int((await self.session.execute(stmt)).scalar_one())

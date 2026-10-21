"""Class session queries."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from backend.models.attendance import Attendance
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
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
        student_id: int | None = None,
        include_cancelled: bool = False,
    ) -> tuple[Sequence[BatchSession], int]:
        stmt = scope.apply(self._base(), BatchSession.id)
        if not include_cancelled:
            stmt = stmt.where(BatchSession.cancelled_at.is_(None))

        if batch_id is not None:
            stmt = stmt.where(BatchSession.batch_id == batch_id)
        if tutor_id is not None:
            stmt = stmt.where(BatchSession.tutor_id == tutor_id)
        if starts_after is not None:
            stmt = stmt.where(BatchSession.session_start_time >= starts_after)
        if starts_before is not None:
            stmt = stmt.where(BatchSession.session_start_time <= starts_before)
        if student_id is not None:
            stmt = stmt.where(
                BatchSession.batch_id.in_(
                    select(Enrollments.batch_id).where(Enrollments.student_id == student_id)
                )
            )

        # Ascending: this is a timetable, and a timetable reads forwards. The
        # page defaults its window to today onward, so the first row is the
        # next class rather than the oldest one on record.
        stmt = stmt.order_by(BatchSession.session_start_time.asc(), BatchSession.id)
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def window(
        self,
        *,
        scope: "Scope",
        start: datetime,
        end: datetime,
        batch_id: int | None = None,
        is_active: bool | None = None,
        tutor_id: int | None = None,
        student_id: int | None = None,
        query: str | None = None,
        limit: int,
    ) -> Sequence[BatchSession]:
        """Sessions overlapping [start, end), scoped to what the caller may see. Cancelled ones are not drawn."""
        stmt = scope.apply(self._base(), BatchSession.id).where(
            BatchSession.cancelled_at.is_(None),
            BatchSession.session_start_time < end,
            BatchSession.session_start_time >= start - timedelta(days=1),  # a session may end inside the window
        )
        if batch_id is not None:
            stmt = stmt.where(BatchSession.batch_id == batch_id)
        if is_active is not None:
            stmt = stmt.where(
                BatchSession.batch_id.in_(
                    select(Batch.id).where(Batch.is_active.is_(is_active))
                )
            )
        if tutor_id is not None:
            stmt = stmt.where(BatchSession.tutor_id == tutor_id)
        if student_id is not None:
            stmt = stmt.where(
                BatchSession.batch_id.in_(
                    select(Enrollments.batch_id).where(Enrollments.student_id == student_id)
                )
            )
        if query:
            needle = f"%{query.strip().lower()}%"
            batch_subq = (
                select(Batch.id)
                .join(Course, Course.id == Batch.course_id)
                .where(
                    or_(
                        func.lower(Batch.batch_code).like(needle),
                        func.lower(Course.title).like(needle),
                        func.lower(func.coalesce(Batch.training_method, "")).like(needle),
                        func.lower(func.coalesce(Batch.training_days, "")).like(needle),
                        func.lower(func.coalesce(Batch.notes, "")).like(needle),
                    )
                )
            )
            stmt = stmt.where(
                or_(
                    BatchSession.batch_id.in_(batch_subq),
                    func.lower(func.coalesce(BatchSession.classroom, "")).like(needle),
                )
            )
        stmt = stmt.order_by(BatchSession.session_start_time, BatchSession.id).limit(limit)
        return (await self.session.execute(stmt)).scalars().all()

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
            BatchSession.cancelled_at.is_(None),  # a cancelled class frees the tutor
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

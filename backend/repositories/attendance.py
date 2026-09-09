"""Attendance queries."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.orm import selectinload

from backend.models.attendance import Attendance
from backend.models.batch import BatchSession
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams
from backend.utils.enums import AttendanceStatus

if TYPE_CHECKING:
    from backend.services.scope import AttendanceVisibility


class AttendanceRepository(BaseRepository[Attendance]):
    model = Attendance

    def _base(self) -> Select[tuple[Attendance]]:
        return select(Attendance).options(
            selectinload(Attendance.student),
            selectinload(Attendance.tutor),
            selectinload(Attendance.session).selectinload(BatchSession.batch),
        )

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> Attendance | None:
        stmt = self._base().where(Attendance.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_session(self, session_id: int) -> list[Attendance]:
        stmt = self._base().where(Attendance.session_id == session_id)
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def existing_by_student(self, session_id: int) -> dict[int, Attendance]:
        """Existing register entries for a session, keyed by student id.

        Used by the bulk marker so re-marking corrects the existing row
        rather than inserting a second one -- which the
        `uq_attendances_session_student` constraint would refuse anyway.
        """
        rows = await self.list_for_session(session_id)
        return {row.student_id: row for row in rows}

    async def search(
        self,
        params: PageParams,
        *,
        visibility: "AttendanceVisibility",
        session_id: int | None = None,
        student_id: int | None = None,
        batch_id: int | None = None,
        status: AttendanceStatus | None = None,
    ) -> tuple[Sequence[Attendance], int]:
        stmt = visibility.apply(
            self._base(),
            session_column=Attendance.session_id,
            student_column=Attendance.student_id,
        )

        if session_id is not None:
            stmt = stmt.where(Attendance.session_id == session_id)
        if student_id is not None:
            stmt = stmt.where(Attendance.student_id == student_id)
        if status is not None:
            stmt = stmt.where(Attendance.status == status)
        if batch_id is not None:
            stmt = stmt.where(
                Attendance.session_id.in_(
                    select(BatchSession.id).where(BatchSession.batch_id == batch_id)
                )
            )

        stmt = stmt.order_by(Attendance.id.desc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def summarise(
        self,
        *,
        visibility: "AttendanceVisibility",
        student_id: int | None = None,
        batch_id: int | None = None,
    ) -> dict[AttendanceStatus, int]:
        """Counts by status, honouring the caller's visibility.

        The scope filter is applied to the *aggregate* as well as to listings:
        a summary computed over rows the caller cannot see would leak the
        same information one number at a time.
        """
        stmt = visibility.apply(
            select(Attendance.status, func.count()).select_from(Attendance),
            session_column=Attendance.session_id,
            student_column=Attendance.student_id,
        )

        if student_id is not None:
            stmt = stmt.where(Attendance.student_id == student_id)
        if batch_id is not None:
            stmt = stmt.where(
                Attendance.session_id.in_(
                    select(BatchSession.id).where(BatchSession.batch_id == batch_id)
                )
            )

        stmt = stmt.group_by(Attendance.status)
        rows = (await self.session.execute(stmt)).all()
        return {status: count for status, count in rows}

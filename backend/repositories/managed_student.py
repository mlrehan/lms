"""Corporate manager ↔ student link queries.

The same shape as `GuardianRepository`, deliberately: the two tables answer
the same question for the two kinds of person who have standing to read
somebody else's record, and a reader who knows one should not have to learn
the other.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import Select, false, func, or_, select
from sqlalchemy.orm import selectinload

from backend.models.organization import ManagedStudent
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams


class ManagedStudentRepository(BaseRepository[ManagedStudent]):
    model = ManagedStudent

    def _base(self) -> Select[tuple[ManagedStudent]]:
        return select(ManagedStudent).options(
            selectinload(ManagedStudent.manager),
            selectinload(ManagedStudent.student),
        )

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> ManagedStudent | None:
        stmt = self._base().where(ManagedStudent.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_link(self, *, manager_id: int, student_id: int) -> ManagedStudent | None:
        stmt = self._base().where(
            ManagedStudent.manager_id == manager_id,
            ManagedStudent.student_id == student_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def search(
        self,
        params: PageParams,
        *,
        unrestricted: bool,
        own_user_id: int | None,
        manager_id: int | None = None,
        student_id: int | None = None,
    ) -> tuple[Sequence[ManagedStudent], int]:
        stmt = self._base()

        if not unrestricted:
            # A caller without `institution.view_all` sees only links they are
            # part of -- as the manager, or as the student. `own_user_id` of
            # None would mean "nobody", so it denies rather than falling
            # through to an unfiltered query.
            if own_user_id is None:
                stmt = stmt.where(false())
            else:
                stmt = stmt.where(
                    or_(
                        ManagedStudent.manager_id == own_user_id,
                        ManagedStudent.student_id == own_user_id,
                    )
                )

        if manager_id is not None:
            stmt = stmt.where(ManagedStudent.manager_id == manager_id)
        if student_id is not None:
            stmt = stmt.where(ManagedStudent.student_id == student_id)

        stmt = stmt.order_by(ManagedStudent.id.desc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def count_for_student(self, student_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(ManagedStudent)
            .where(ManagedStudent.student_id == student_id)
        )
        return int((await self.session.execute(stmt)).scalar_one())

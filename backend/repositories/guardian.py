"""Guardian ↔ student link queries."""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import selectinload

from backend.models.guardian import StudentGuardian
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams


class GuardianRepository(BaseRepository[StudentGuardian]):
    model = StudentGuardian

    def _base(self) -> Select[tuple[StudentGuardian]]:
        return select(StudentGuardian).options(
            selectinload(StudentGuardian.guardian),
            selectinload(StudentGuardian.student),
        )

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> StudentGuardian | None:
        stmt = self._base().where(StudentGuardian.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_link(self, *, guardian_id: int, student_id: int) -> StudentGuardian | None:
        stmt = self._base().where(
            StudentGuardian.guardian_id == guardian_id,
            StudentGuardian.student_id == student_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def search(
        self,
        params: PageParams,
        *,
        unrestricted: bool,
        own_user_id: int | None,
        guardian_id: int | None = None,
        student_id: int | None = None,
    ) -> tuple[Sequence[StudentGuardian], int]:
        stmt = self._base()

        if not unrestricted:
            # A non-privileged caller sees only links they are part of --
            # either as the guardian or as the student. `own_user_id` of None
            # would mean "nobody", so it denies rather than falling through
            # to an unfiltered query.
            if own_user_id is None:
                from sqlalchemy import false

                stmt = stmt.where(false())
            else:
                stmt = stmt.where(
                    or_(
                        StudentGuardian.guardian_id == own_user_id,
                        StudentGuardian.student_id == own_user_id,
                    )
                )

        if guardian_id is not None:
            stmt = stmt.where(StudentGuardian.guardian_id == guardian_id)
        if student_id is not None:
            stmt = stmt.where(StudentGuardian.student_id == student_id)

        stmt = stmt.order_by(StudentGuardian.id.desc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def count_for_student(self, student_id: int) -> int:
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(StudentGuardian)
            .where(StudentGuardian.student_id == student_id)
        )
        return int((await self.session.execute(stmt)).scalar_one())

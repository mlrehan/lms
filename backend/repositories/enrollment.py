"""Enrollment queries."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import Select, select
from sqlalchemy.orm import selectinload

from backend.models.batch import Batch
from backend.models.enrollment import Enrollments
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams
from backend.utils.enums import EnrollmentStatus

if TYPE_CHECKING:
    from backend.services.scope import EnrollmentVisibility

# The statuses that mean "this enrollment is still live". The partial unique
# index `uq_enrollments_active_batch_student` uses exactly this set, so a
# second live enrollment for the same (batch, student) is refused by the
# database as well as by the service -- re-enrolling after DROPPED is fine.
ACTIVE_STATUSES = (EnrollmentStatus.PENDING, EnrollmentStatus.CONFIRMED)


class EnrollmentRepository(BaseRepository[Enrollments]):
    model = Enrollments

    def _base(self) -> Select[tuple[Enrollments]]:
        return select(Enrollments).options(
            selectinload(Enrollments.student),
            selectinload(Enrollments.batch).selectinload(Batch.course),
            selectinload(Enrollments.organization),
        )

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> Enrollments | None:
        stmt = self._base().where(Enrollments.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_active(self, *, student_id: int, batch_id: int) -> Enrollments | None:
        stmt = select(Enrollments).where(
            Enrollments.student_id == student_id,
            Enrollments.batch_id == batch_id,
            Enrollments.status.in_(ACTIVE_STATUSES),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def search(
        self,
        params: PageParams,
        *,
        visibility: "EnrollmentVisibility",
        batch_id: int | None = None,
        student_id: int | None = None,
        status: EnrollmentStatus | None = None,
        organization_id: int | None = None,
    ) -> tuple[Sequence[Enrollments], int]:
        stmt = visibility.apply(
            self._base(),
            batch_column=Enrollments.batch_id,
            student_column=Enrollments.student_id,
        )

        if batch_id is not None:
            stmt = stmt.where(Enrollments.batch_id == batch_id)
        if student_id is not None:
            stmt = stmt.where(Enrollments.student_id == student_id)
        if status is not None:
            stmt = stmt.where(Enrollments.status == status)
        if organization_id is not None:
            stmt = stmt.where(Enrollments.organization_id == organization_id)

        stmt = stmt.order_by(Enrollments.enrollment_id.desc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]

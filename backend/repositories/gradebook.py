"""Grade book, grade band and transcript queries."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import Select, select
from sqlalchemy.orm import selectinload

from backend.models.batch import Batch
from backend.models.gradebook import GradeBand, GradeBookEntry, Transcript
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams
from backend.utils.enums import GradeComponentType

if TYPE_CHECKING:
    from backend.services.scope import EnrollmentVisibility


class GradeBandRepository(BaseRepository[GradeBand]):
    model = GradeBand

    async def list_all(self) -> list[GradeBand]:
        stmt = select(GradeBand).order_by(GradeBand.min_score.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, band_id: int) -> GradeBand | None:
        return await self.session.get(GradeBand, band_id)

    async def get_by_letter(self, letter: str) -> GradeBand | None:
        stmt = select(GradeBand).where(GradeBand.letter_grade == letter)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def overlapping(
        self, *, min_score: Decimal, max_score: Decimal, exclude_id: int | None = None
    ) -> GradeBand | None:
        """Any band whose range intersects the given one.

        Overlapping bands make the letter for a given percentage ambiguous --
        which of two matching rows wins would come down to row order.
        """
        stmt = select(GradeBand).where(
            GradeBand.min_score <= max_score,
            GradeBand.max_score >= min_score,
        )
        if exclude_id is not None:
            stmt = stmt.where(GradeBand.id != exclude_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def for_percentage(self, percentage: Decimal) -> GradeBand | None:
        stmt = (
            select(GradeBand)
            .where(GradeBand.min_score <= percentage, GradeBand.max_score >= percentage)
            .order_by(GradeBand.min_score.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


class GradeBookRepository(BaseRepository[GradeBookEntry]):
    model = GradeBookEntry

    def _base(self) -> Select[tuple[GradeBookEntry]]:
        return select(GradeBookEntry).options(
            selectinload(GradeBookEntry.student),
            selectinload(GradeBookEntry.batch),
        )

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> GradeBookEntry | None:
        stmt = self._base().where(GradeBookEntry.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def for_batch(self, batch_id: int) -> list[GradeBookEntry]:
        stmt = self._base().where(GradeBookEntry.batch_id == batch_id)
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def for_student_in_batch(
        self, *, student_id: int, batch_id: int
    ) -> list[GradeBookEntry]:
        stmt = self._base().where(
            GradeBookEntry.student_id == student_id,
            GradeBookEntry.batch_id == batch_id,
        )
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def find_one(
        self,
        *,
        student_id: int,
        batch_id: int,
        component_type: GradeComponentType,
        reference_id: int | None,
    ) -> GradeBookEntry | None:
        """Locate the single entry the two partial unique indexes allow for
        this source row (or, for a reference-less component, for this
        student/batch/component)."""
        stmt = select(GradeBookEntry).where(
            GradeBookEntry.student_id == student_id,
            GradeBookEntry.batch_id == batch_id,
            GradeBookEntry.component_type == component_type,
        )
        stmt = (
            stmt.where(GradeBookEntry.reference_id == reference_id)
            if reference_id is not None
            else stmt.where(GradeBookEntry.reference_id.is_(None))
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def search(
        self,
        params: PageParams,
        *,
        visibility: "EnrollmentVisibility",
        batch_id: int | None = None,
        student_id: int | None = None,
        component_type: GradeComponentType | None = None,
    ) -> tuple[Sequence[GradeBookEntry], int]:
        stmt = visibility.apply(
            self._base(),
            batch_column=GradeBookEntry.batch_id,
            student_column=GradeBookEntry.student_id,
        )

        if batch_id is not None:
            stmt = stmt.where(GradeBookEntry.batch_id == batch_id)
        if student_id is not None:
            stmt = stmt.where(GradeBookEntry.student_id == student_id)
        if component_type is not None:
            stmt = stmt.where(GradeBookEntry.component_type == component_type)

        stmt = stmt.order_by(GradeBookEntry.id.desc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]


class TranscriptRepository(BaseRepository[Transcript]):
    model = Transcript

    def _base(self) -> Select[tuple[Transcript]]:
        return select(Transcript).options(
            selectinload(Transcript.student),
            selectinload(Transcript.batch).selectinload(Batch.course),
            selectinload(Transcript.course),
        )

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> Transcript | None:
        stmt = self._base().where(Transcript.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def existing_by_student(self, batch_id: int) -> dict[int, Transcript]:
        stmt = self._base().where(Transcript.batch_id == batch_id)
        rows = (await self.session.execute(stmt)).scalars().unique().all()
        return {r.student_id: r for r in rows}

    async def search(
        self,
        params: PageParams,
        *,
        visibility: "EnrollmentVisibility",
        batch_id: int | None = None,
        student_id: int | None = None,
        include_provisional: bool,
    ) -> tuple[Sequence[Transcript], int]:
        stmt = visibility.apply(
            self._base(),
            batch_column=Transcript.batch_id,
            student_column=Transcript.student_id,
        )

        if not include_provisional:
            # A transcript that has not been finalised is a working draft;
            # showing it to the student invites them to act on a figure that
            # is still being recomputed on every sync.
            stmt = stmt.where(Transcript.is_final.is_(True))

        if batch_id is not None:
            stmt = stmt.where(Transcript.batch_id == batch_id)
        if student_id is not None:
            stmt = stmt.where(Transcript.student_id == student_id)

        stmt = stmt.order_by(Transcript.id.desc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]

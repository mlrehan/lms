"""Academic reference-data queries (spec §23).

The recurring shape here is a **usage count**: how many rows still point at a
department, a category, a tag, an academic year. Each one is computed for a
whole page in a single GROUP BY rather than by walking a back-reference
collection per row -- those relationships are `lazy="raise"` precisely so
that mistake cannot be made quietly.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import Select, func, or_, select, union
from sqlalchemy.orm import selectinload

from backend.models.administration import (
    AcademicYear,
    Category,
    CourseTag,
    Department,
    Semester,
    SystemSetting,
    Tag,
)
from backend.models.batch import Batch
from backend.models.course import Course
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams


def _counts(rows: Sequence[tuple[int, int]]) -> dict[int, int]:
    return {int(a): int(b) for a, b in rows}


class AcademicYearRepository(BaseRepository[AcademicYear]):
    model = AcademicYear

    def _base(self) -> Select[tuple[AcademicYear]]:
        return select(AcademicYear).options(selectinload(AcademicYear.semesters))

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> AcademicYear | None:
        stmt = self._base().where(AcademicYear.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def by_label(self, label: str, *, exclude_id: int | None = None) -> AcademicYear | None:
        stmt = select(AcademicYear).where(func.lower(AcademicYear.label) == label.strip().lower())
        if exclude_id is not None:
            stmt = stmt.where(AcademicYear.id != exclude_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def search(
        self, params: PageParams, *, current_only: bool = False
    ) -> tuple[Sequence[AcademicYear], int]:
        stmt = self._base()
        if current_only:
            stmt = stmt.where(AcademicYear.is_current.is_(True))
        # Most recent first: an administrator opens this screen to work on the
        # year in progress, not on 2009.
        stmt = stmt.order_by(AcademicYear.start_date.desc(), AcademicYear.id.desc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def clear_current(self, *, except_id: int | None = None) -> None:
        from sqlalchemy import update

        stmt = (
            update(AcademicYear)
            .where(AcademicYear.is_current.is_(True))
            .values(is_current=False)
        )
        if except_id is not None:
            stmt = stmt.where(AcademicYear.id != except_id)
        await self.session.execute(stmt)

    async def batch_counts(self, year_ids: Sequence[int]) -> dict[int, int]:
        """Batches scheduled into each year, counted through **both** routes.

        A batch can name the year directly (`academic_year_id`) or reach it
        through a semester. Counting only the direct column would report a
        year as unused while batches are sitting in its autumn term, and the
        delete guard built on this count would then be wrong in the direction
        that loses data.
        """
        if not year_ids:
            return {}

        direct = select(
            Batch.academic_year_id.label("year_id"), Batch.id.label("batch_id")
        ).where(Batch.academic_year_id.in_(year_ids))

        via_semester = (
            select(Semester.academic_year_id.label("year_id"), Batch.id.label("batch_id"))
            .select_from(Batch)
            .join(Semester, Batch.semester_id == Semester.id)
            .where(Semester.academic_year_id.in_(year_ids))
        )

        # UNION over (year, batch) pairs, then COUNT DISTINCT: a batch that
        # names both the year and one of its semesters is one batch, not two.
        both = union(direct, via_semester).subquery()
        stmt = select(both.c.year_id, func.count(func.distinct(both.c.batch_id))).group_by(
            both.c.year_id
        )
        return _counts((await self.session.execute(stmt)).all())  # type: ignore[arg-type]


class SemesterRepository(BaseRepository[Semester]):
    model = Semester

    def _base(self) -> Select[tuple[Semester]]:
        return select(Semester).options(selectinload(Semester.academic_year))

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> Semester | None:
        stmt = self._base().where(Semester.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def named(
        self, *, academic_year_id: int, name: str, exclude_id: int | None = None
    ) -> Semester | None:
        stmt = select(Semester).where(
            Semester.academic_year_id == academic_year_id,
            func.lower(Semester.name) == name.strip().lower(),
        )
        if exclude_id is not None:
            stmt = stmt.where(Semester.id != exclude_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def search(
        self, params: PageParams, *, academic_year_id: int | None = None
    ) -> tuple[Sequence[Semester], int]:
        stmt = self._base()
        if academic_year_id is not None:
            stmt = stmt.where(Semester.academic_year_id == academic_year_id)
        stmt = stmt.order_by(Semester.start_date.asc(), Semester.id.asc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def batch_counts(self, semester_ids: Sequence[int]) -> dict[int, int]:
        if not semester_ids:
            return {}
        stmt = (
            select(Batch.semester_id, func.count())
            .where(Batch.semester_id.in_(semester_ids))
            .group_by(Batch.semester_id)
        )
        return _counts((await self.session.execute(stmt)).all())  # type: ignore[arg-type]


class DepartmentRepository(BaseRepository[Department]):
    model = Department

    def _base(self) -> Select[tuple[Department]]:
        return select(Department).options(selectinload(Department.head_tutor))

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> Department | None:
        stmt = self._base().where(Department.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def by_name_or_code(
        self, *, name: str | None = None, code: str | None = None, exclude_id: int | None = None
    ) -> Department | None:
        clauses = []
        if name:
            clauses.append(func.lower(Department.name) == name.strip().lower())
        if code:
            clauses.append(func.lower(Department.code) == code.strip().lower())
        if not clauses:
            return None
        stmt = select(Department).where(or_(*clauses))
        if exclude_id is not None:
            stmt = stmt.where(Department.id != exclude_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def search(
        self, params: PageParams, *, query: str | None = None
    ) -> tuple[Sequence[Department], int]:
        stmt = self._base()
        if query:
            needle = f"%{query.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Department.name).like(needle),
                    func.lower(func.coalesce(Department.code, "")).like(needle),
                )
            )
        stmt = stmt.order_by(Department.name.asc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def course_counts(self, department_ids: Sequence[int]) -> dict[int, int]:
        if not department_ids:
            return {}
        stmt = (
            select(Course.department_id, func.count())
            .where(Course.department_id.in_(department_ids))
            .group_by(Course.department_id)
        )
        return _counts((await self.session.execute(stmt)).all())  # type: ignore[arg-type]


class CategoryRepository(BaseRepository[Category]):
    model = Category

    def _base(self) -> Select[tuple[Category]]:
        return select(Category).options(selectinload(Category.parent))

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> Category | None:
        stmt = self._base().where(Category.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def sibling_named(
        self, *, name: str, parent_id: int | None, exclude_id: int | None = None
    ) -> Category | None:
        stmt = select(Category).where(func.lower(Category.name) == name.strip().lower())
        stmt = (
            stmt.where(Category.parent_id == parent_id)
            if parent_id is not None
            else stmt.where(Category.parent_id.is_(None))
        )
        if exclude_id is not None:
            stmt = stmt.where(Category.id != exclude_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def search(
        self, params: PageParams, *, parent_id: int | None = None, top_level: bool = False,
        query: str | None = None,
    ) -> tuple[Sequence[Category], int]:
        stmt = self._base()
        if top_level:
            stmt = stmt.where(Category.parent_id.is_(None))
        elif parent_id is not None:
            stmt = stmt.where(Category.parent_id == parent_id)
        if query:
            stmt = stmt.where(func.lower(Category.name).like(f"%{query.strip().lower()}%"))
        stmt = stmt.order_by(Category.name.asc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def child_counts(self, category_ids: Sequence[int]) -> dict[int, int]:
        if not category_ids:
            return {}
        stmt = (
            select(Category.parent_id, func.count())
            .where(Category.parent_id.in_(category_ids))
            .group_by(Category.parent_id)
        )
        return _counts((await self.session.execute(stmt)).all())  # type: ignore[arg-type]

    async def course_counts(self, category_ids: Sequence[int]) -> dict[int, int]:
        if not category_ids:
            return {}
        stmt = (
            select(Course.category_id, func.count())
            .where(Course.category_id.in_(category_ids))
            .group_by(Course.category_id)
        )
        return _counts((await self.session.execute(stmt)).all())  # type: ignore[arg-type]

    async def descendant_ids(self, category_id: int) -> set[int]:
        """Every category beneath this one.

        Used to refuse re-parenting a category into its own subtree, which
        would detach that subtree from the tree entirely. Bounded, like the
        equivalent walk in `repositories/resource.py`: a cycle already in the
        data must not make this loop forever.
        """
        found: set[int] = set()
        frontier = [category_id]
        while frontier and len(found) < 10_000:
            stmt = select(Category.id).where(Category.parent_id.in_(frontier))
            next_ids = [i for i in (await self.session.execute(stmt)).scalars().all() if i not in found]
            found.update(next_ids)
            frontier = next_ids
        return found


class TagRepository(BaseRepository[Tag]):
    model = Tag

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> Tag | None:
        stmt = select(Tag).where(Tag.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def by_name(self, name: str, *, exclude_id: int | None = None) -> Tag | None:
        stmt = select(Tag).where(func.lower(Tag.name) == name.strip().lower())
        if exclude_id is not None:
            stmt = stmt.where(Tag.id != exclude_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def by_public_ids(self, public_ids: Sequence[uuid.UUID]) -> list[Tag]:
        if not public_ids:
            return []
        stmt = select(Tag).where(Tag.public_id.in_(public_ids))
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def search(
        self, params: PageParams, *, query: str | None = None
    ) -> tuple[Sequence[Tag], int]:
        stmt = select(Tag)
        if query:
            stmt = stmt.where(func.lower(Tag.name).like(f"%{query.strip().lower()}%"))
        stmt = stmt.order_by(Tag.name.asc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def course_counts(self, tag_ids: Sequence[int]) -> dict[int, int]:
        if not tag_ids:
            return {}
        stmt = (
            select(CourseTag.tag_id, func.count())
            .where(CourseTag.tag_id.in_(tag_ids))
            .group_by(CourseTag.tag_id)
        )
        return _counts((await self.session.execute(stmt)).all())  # type: ignore[arg-type]

    async def tag_ids_for_course(self, course_id: int) -> set[int]:
        stmt = select(CourseTag.tag_id).where(CourseTag.course_id == course_id)
        return set((await self.session.execute(stmt)).scalars().all())


class SystemSettingRepository(BaseRepository[SystemSetting]):
    model = SystemSetting

    async def get_key(self, key: str) -> SystemSetting | None:
        return await self.session.get(SystemSetting, key)

    async def search(
        self, params: PageParams, *, prefix: str | None = None
    ) -> tuple[Sequence[SystemSetting], int]:
        stmt = select(SystemSetting)
        if prefix:
            # Grouped by dotted namespace: settings are read a section at a
            # time ("grading.*"), never as one flat list of everything.
            stmt = stmt.where(SystemSetting.key.startswith(prefix.strip().lower()))
        stmt = stmt.order_by(SystemSetting.key.asc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]

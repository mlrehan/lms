"""Academic reference data: years, semesters, departments, categories, tags
(spec §23).

**Reference data is deleted differently from records.** Everywhere else in
this codebase a delete is either a soft delete (courses, resources) or a
clean unlink (guardianships). Here the row is small and the danger is not
losing it -- it is what happens to everything pointing at it. Every foreign
key into these tables is `ON DELETE SET NULL` or CASCADE, so Postgres will
happily accept the delete and silently blank a hundred courses' department,
or detach a subtree of categories. That is data loss with no error and no
audit signature.

So the rule throughout: **a delete is refused with 409 while anything still
references the row, and the message names the count.** An administrator gets
"12 courses still use this department" instead of a success followed by a
support ticket. The one exception is a tag, which is only ever a label --
untagging is the whole point of deleting one.

The second recurring rule: **dates are validated against the parent, not just
against each other.** A "Fall" semester running from 2025 into 2027 passes any
start-before-end check and is still wrong; it has to sit inside its academic
year, and only the service can see both.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.models.administration import (
    AcademicYear,
    Category,
    Department,
    Semester,
    Tag,
)
from backend.models.identity.user import User
from backend.repositories.administration import (
    AcademicYearRepository,
    CategoryRepository,
    DepartmentRepository,
    SemesterRepository,
    TagRepository,
)
from backend.schemas.administration import (
    AcademicYearCreateRequest,
    AcademicYearUpdateRequest,
    CategoryCreateRequest,
    CategoryUpdateRequest,
    DepartmentCreateRequest,
    DepartmentUpdateRequest,
    SemesterCreateRequest,
    SemesterUpdateRequest,
    TagWriteRequest,
)
from backend.schemas.base import PageParams
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.utils.enums import Roles


def _audit(session, *, action: str, actor: User, entity: str, entity_id: int, details: dict) -> None:
    audit_service.record(
        session,
        action=action,
        actor_user_id=actor.id,
        actor_email=actor.email,
        entity_type=entity,
        entity_id=entity_id,
        details=details,
    )


class AcademicYearService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.years = AcademicYearRepository(session)

    async def list(
        self, params: PageParams, *, current_only: bool = False
    ) -> tuple[Sequence[AcademicYear], int, dict[int, int]]:
        rows, total = await self.years.search(params, current_only=current_only)
        counts = await self.years.batch_counts([r.id for r in rows])
        return rows, total, counts

    async def get(self, public_id: uuid.UUID) -> tuple[AcademicYear, int]:
        year = await self._load(public_id)
        counts = await self.years.batch_counts([year.id])
        return year, counts.get(year.id, 0)

    async def create(self, payload: AcademicYearCreateRequest, *, actor: User) -> AcademicYear:
        if await self.years.by_label(payload.label):
            raise ConflictError("An academic year with that label already exists.")

        if payload.is_current:
            await self.years.clear_current()

        year = AcademicYear(
            label=payload.label,
            start_date=payload.start_date,
            end_date=payload.end_date,
            is_current=payload.is_current,
            # Initialised before the object becomes persistent: a new
            # instance's collections are unloaded, and the flush cascade
            # touching one raises `MissingGreenlet` under asyncio.
            semesters=[],
        )
        await self.years.add_and_flush(year)
        _audit(self.session, action=AuditAction.CREATE, actor=actor,
               entity="academic_year", entity_id=year.id, details={"label": year.label})
        return year

    async def update(
        self, public_id: uuid.UUID, payload: AcademicYearUpdateRequest, *, actor: User
    ) -> AcademicYear:
        year = await self._load(public_id)
        changes = payload.model_dump(exclude_unset=True)

        if "label" in changes and await self.years.by_label(changes["label"], exclude_id=year.id):
            raise ConflictError("An academic year with that label already exists.")

        start = changes.get("start_date", year.start_date)
        end = changes.get("end_date", year.end_date)
        if start and end and end <= start:
            # Re-checked against the stored row: moving only `start_date` past
            # an untouched `end_date` inverts the window, and the schema
            # validator cannot see the half it was not sent.
            raise ValidationError("end_date must be after start_date.")

        # Checked before anything is assigned: narrowing a year so that its
        # own semesters fall outside it has to be refused, not applied and
        # then unwound by the request's rollback.
        self._assert_semesters_still_inside(year, start=start, end=end)

        if changes.get("is_current"):
            await self.years.clear_current(except_id=year.id)

        for field, value in changes.items():
            setattr(year, field, value)

        _audit(self.session, action=AuditAction.UPDATE, actor=actor,
               entity="academic_year", entity_id=year.id, details={"fields": sorted(changes)})
        return year

    async def delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        year = await self._load(public_id)
        counts = await self.years.batch_counts([year.id])
        in_use = counts.get(year.id, 0)
        if in_use:
            raise ConflictError(
                f"{in_use} batch(es) are still scheduled in this academic year.",
                details={"batch_count": in_use},
            )

        entity_id, label = year.id, year.label
        semester_count = len(year.semesters)
        # Its semesters cascade away with it. That is safe only because the
        # check above proved no batch is scheduled in any of them -- the
        # count deliberately spans both routes into the year.
        await self.session.delete(year)
        _audit(self.session, action=AuditAction.DELETE, actor=actor,
               entity="academic_year", entity_id=entity_id,
               details={"label": label, "semesters_removed": semester_count})

    @staticmethod
    def _assert_semesters_still_inside(year: AcademicYear, *, start, end) -> None:
        for semester in year.semesters:
            if semester.start_date < start or semester.end_date > end:
                raise ValidationError(
                    f"Semester '{semester.name}' would fall outside the new dates.",
                    details={"semester": semester.name},
                )

    async def _load(self, public_id: uuid.UUID) -> AcademicYear:
        year = await self.years.get_by_public_id_full(public_id)
        if year is None:
            raise NotFoundError("Academic year not found.")
        return year


class SemesterService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.semesters = SemesterRepository(session)
        self.years = AcademicYearRepository(session)

    async def list(
        self, params: PageParams, *, academic_year_id: uuid.UUID | None = None
    ) -> tuple[Sequence[Semester], int, dict[int, int]]:
        year_pk = None
        if academic_year_id is not None:
            year_pk = (await self._load_year(academic_year_id)).id
        rows, total = await self.semesters.search(params, academic_year_id=year_pk)
        counts = await self.semesters.batch_counts([r.id for r in rows])
        return rows, total, counts

    async def get(self, public_id: uuid.UUID) -> tuple[Semester, int]:
        semester = await self._load(public_id)
        counts = await self.semesters.batch_counts([semester.id])
        return semester, counts.get(semester.id, 0)

    async def create(self, payload: SemesterCreateRequest, *, actor: User) -> Semester:
        year = await self._load_year(payload.academic_year_id)

        if await self.semesters.named(academic_year_id=year.id, name=payload.name):
            raise ConflictError("That academic year already has a semester with this name.")

        self._assert_inside_year(year, payload.start_date, payload.end_date)

        semester = Semester(
            academic_year_id=year.id,
            name=payload.name,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )
        await self.semesters.add_and_flush(semester)
        _audit(self.session, action=AuditAction.CREATE, actor=actor,
               entity="semester", entity_id=semester.id,
               details={"name": semester.name, "academic_year": year.label})
        return await self.semesters.get_by_public_id_full(semester.public_id)  # type: ignore[return-value]

    async def update(
        self, public_id: uuid.UUID, payload: SemesterUpdateRequest, *, actor: User
    ) -> Semester:
        semester = await self._load(public_id)
        changes = payload.model_dump(exclude_unset=True)

        if "name" in changes and await self.semesters.named(
            academic_year_id=semester.academic_year_id, name=changes["name"], exclude_id=semester.id
        ):
            raise ConflictError("That academic year already has a semester with this name.")

        start = changes.get("start_date", semester.start_date)
        end = changes.get("end_date", semester.end_date)
        if start and end and end <= start:
            raise ValidationError("end_date must be after start_date.")
        self._assert_inside_year(semester.academic_year, start, end)

        for field, value in changes.items():
            setattr(semester, field, value)

        _audit(self.session, action=AuditAction.UPDATE, actor=actor,
               entity="semester", entity_id=semester.id, details={"fields": sorted(changes)})
        return semester

    async def delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        semester = await self._load(public_id)
        counts = await self.semesters.batch_counts([semester.id])
        in_use = counts.get(semester.id, 0)
        if in_use:
            raise ConflictError(
                f"{in_use} batch(es) are still scheduled in this semester.",
                details={"batch_count": in_use},
            )

        entity_id, name = semester.id, semester.name
        await self.session.delete(semester)
        _audit(self.session, action=AuditAction.DELETE, actor=actor,
               entity="semester", entity_id=entity_id, details={"name": name})

    @staticmethod
    def _assert_inside_year(year: AcademicYear, start, end) -> None:
        """A semester belongs to its year, and the dates have to agree.

        Only the service can see both sides of this: the request knows the
        semester's dates, the row knows the year's, and neither alone can tell
        that "Fall 2025" has been entered as running into 2027.
        """
        if start < year.start_date or end > year.end_date:
            raise ValidationError(
                f"Semester dates must fall within {year.label} "
                f"({year.start_date} to {year.end_date}).",
            )

    async def _load(self, public_id: uuid.UUID) -> Semester:
        semester = await self.semesters.get_by_public_id_full(public_id)
        if semester is None:
            raise NotFoundError("Semester not found.")
        return semester

    async def _load_year(self, public_id: uuid.UUID) -> AcademicYear:
        year = await self.years.get_by_public_id_full(public_id)
        if year is None:
            raise NotFoundError("Academic year not found.")
        return year


class DepartmentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.departments = DepartmentRepository(session)

    async def list(
        self, params: PageParams, *, query: str | None = None
    ) -> tuple[Sequence[Department], int, dict[int, int]]:
        rows, total = await self.departments.search(params, query=query)
        counts = await self.departments.course_counts([r.id for r in rows])
        return rows, total, counts

    async def get(self, public_id: uuid.UUID) -> tuple[Department, int]:
        department = await self._load(public_id)
        counts = await self.departments.course_counts([department.id])
        return department, counts.get(department.id, 0)

    async def create(self, payload: DepartmentCreateRequest, *, actor: User) -> Department:
        if await self.departments.by_name_or_code(name=payload.name, code=payload.code):
            raise ConflictError("A department with that name or code already exists.")

        head_id = None
        if payload.head_tutor_id is not None:
            head_id = (await self._load_tutor(payload.head_tutor_id)).id

        department = Department(name=payload.name, code=payload.code, head_tutor_id=head_id)
        await self.departments.add_and_flush(department)
        _audit(self.session, action=AuditAction.CREATE, actor=actor,
               entity="department", entity_id=department.id, details={"name": department.name})
        return await self.departments.get_by_public_id_full(department.public_id)  # type: ignore[return-value]

    async def update(
        self, public_id: uuid.UUID, payload: DepartmentUpdateRequest, *, actor: User
    ) -> Department:
        department = await self._load(public_id)
        changes = payload.model_dump(exclude_unset=True)
        clear_head = changes.pop("clear_head_tutor", False)

        if ("name" in changes or "code" in changes) and await self.departments.by_name_or_code(
            name=changes.get("name"), code=changes.get("code"), exclude_id=department.id
        ):
            raise ConflictError("A department with that name or code already exists.")

        head_public_id = changes.pop("head_tutor_id", None)
        if clear_head:
            department.head_tutor_id = None
        elif head_public_id is not None:
            department.head_tutor_id = (await self._load_tutor(head_public_id)).id

        for field, value in changes.items():
            setattr(department, field, value)

        # Assigning the FK does not invalidate the already-loaded `head_tutor`
        # object, so the response would echo the previous holder of the post.
        # Same stale-relationship trap as `_apply_location` in user_service.
        self.session.expire(department, ["head_tutor"])
        refreshed = await self.departments.get_by_public_id_full(department.public_id)

        _audit(self.session, action=AuditAction.UPDATE, actor=actor,
               entity="department", entity_id=department.id,
               details={"fields": sorted(set(changes) | ({"head_tutor_id"} if clear_head or head_public_id else set()))})
        return refreshed  # type: ignore[return-value]

    async def delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        department = await self._load(public_id)
        counts = await self.departments.course_counts([department.id])
        in_use = counts.get(department.id, 0)
        if in_use:
            # `courses.department_id` is ON DELETE SET NULL, so Postgres would
            # accept this and quietly blank the department on every one of
            # them -- data loss with no error to notice.
            raise ConflictError(
                f"{in_use} course(s) still belong to this department.",
                details={"course_count": in_use},
            )

        entity_id, name = department.id, department.name
        await self.session.delete(department)
        _audit(self.session, action=AuditAction.DELETE, actor=actor,
               entity="department", entity_id=entity_id, details={"name": name})

    async def _load(self, public_id: uuid.UUID) -> Department:
        department = await self.departments.get_by_public_id_full(public_id)
        if department is None:
            raise NotFoundError("Department not found.")
        return department

    async def _load_tutor(self, public_id: uuid.UUID) -> User:
        stmt = select(User).where(User.public_id == public_id)
        user = (await self.session.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise NotFoundError("User not found.")
        if not any((r.name or "").upper() == Roles.TUTOR.value for r in (user.roles or [])):
            raise ValidationError(
                "The head of a department must hold the TUTOR role.",
                details={"username": user.username},
            )
        return user


class CategoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.categories = CategoryRepository(session)

    async def list(
        self,
        params: PageParams,
        *,
        parent_id: uuid.UUID | None = None,
        top_level: bool = False,
        query: str | None = None,
    ) -> tuple[Sequence[Category], int, dict[int, int], dict[int, int]]:
        parent_pk = None
        if parent_id is not None:
            parent_pk = (await self._load(parent_id)).id
        rows, total = await self.categories.search(
            params, parent_id=parent_pk, top_level=top_level, query=query
        )
        ids = [r.id for r in rows]
        return rows, total, await self.categories.child_counts(ids), await self.categories.course_counts(ids)

    async def get(self, public_id: uuid.UUID) -> tuple[Category, int, int]:
        category = await self._load(public_id)
        children = await self.categories.child_counts([category.id])
        courses = await self.categories.course_counts([category.id])
        return category, children.get(category.id, 0), courses.get(category.id, 0)

    async def create(self, payload: CategoryCreateRequest, *, actor: User) -> Category:
        parent_pk = None
        if payload.parent_id is not None:
            parent_pk = (await self._load(payload.parent_id)).id

        if await self.categories.sibling_named(name=payload.name, parent_id=parent_pk):
            raise ConflictError("A category with that name already exists at this level.")

        category = Category(name=payload.name, parent_id=parent_pk, children=[])
        await self.categories.add_and_flush(category)
        _audit(self.session, action=AuditAction.CREATE, actor=actor,
               entity="category", entity_id=category.id, details={"name": category.name})
        return await self.categories.get_by_public_id_full(category.public_id)  # type: ignore[return-value]

    async def update(
        self, public_id: uuid.UUID, payload: CategoryUpdateRequest, *, actor: User
    ) -> Category:
        category = await self._load(public_id)
        changes = payload.model_dump(exclude_unset=True)
        make_top = changes.pop("make_top_level", False)
        new_parent_public = changes.pop("parent_id", None)

        target_parent = category.parent_id
        if make_top:
            target_parent = None
        elif new_parent_public is not None:
            parent = await self._load(new_parent_public)
            if parent.id == category.id:
                raise ValidationError("A category cannot be its own parent.")
            descendants = await self.categories.descendant_ids(category.id)
            if parent.id in descendants:
                # Re-parenting into your own subtree detaches that subtree
                # from the tree entirely -- it becomes a ring reachable from
                # nowhere. Same guard as moving a resource folder.
                raise ValidationError("A category cannot be moved inside its own subtree.")
            target_parent = parent.id

        name = changes.get("name", category.name)
        if (name != category.name or target_parent != category.parent_id) and await self.categories.sibling_named(
            name=name, parent_id=target_parent, exclude_id=category.id
        ):
            raise ConflictError("A category with that name already exists at this level.")

        category.parent_id = target_parent
        for field, value in changes.items():
            setattr(category, field, value)

        self.session.expire(category, ["parent"])
        refreshed = await self.categories.get_by_public_id_full(category.public_id)

        _audit(self.session, action=AuditAction.UPDATE, actor=actor,
               entity="category", entity_id=category.id, details={"fields": sorted(changes)})
        return refreshed  # type: ignore[return-value]

    async def delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        category = await self._load(public_id)
        children = (await self.categories.child_counts([category.id])).get(category.id, 0)
        courses = (await self.categories.course_counts([category.id])).get(category.id, 0)

        if children:
            # `categories.parent_id` is SET NULL, so deleting a parent would
            # silently promote its children to top level rather than fail.
            raise ConflictError(
                f"This category has {children} sub-categor(ies). Move or remove them first.",
                details={"child_count": children},
            )
        if courses:
            raise ConflictError(
                f"{courses} course(s) are still in this category.",
                details={"course_count": courses},
            )

        entity_id, name = category.id, category.name
        await self.session.delete(category)
        _audit(self.session, action=AuditAction.DELETE, actor=actor,
               entity="category", entity_id=entity_id, details={"name": name})

    async def _load(self, public_id: uuid.UUID) -> Category:
        category = await self.categories.get_by_public_id_full(public_id)
        if category is None:
            raise NotFoundError("Category not found.")
        return category


class TagService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tags = TagRepository(session)

    async def list(
        self, params: PageParams, *, query: str | None = None
    ) -> tuple[Sequence[Tag], int, dict[int, int]]:
        rows, total = await self.tags.search(params, query=query)
        return rows, total, await self.tags.course_counts([r.id for r in rows])

    async def get(self, public_id: uuid.UUID) -> tuple[Tag, int]:
        tag = await self._load(public_id)
        counts = await self.tags.course_counts([tag.id])
        return tag, counts.get(tag.id, 0)

    async def create(self, payload: TagWriteRequest, *, actor: User) -> Tag:
        if await self.tags.by_name(payload.name):
            raise ConflictError("That tag already exists.")
        tag = Tag(name=payload.name, courses=[])
        await self.tags.add_and_flush(tag)
        _audit(self.session, action=AuditAction.CREATE, actor=actor,
               entity="tag", entity_id=tag.id, details={"name": tag.name})
        return tag

    async def update(self, public_id: uuid.UUID, payload: TagWriteRequest, *, actor: User) -> Tag:
        tag = await self._load(public_id)
        if await self.tags.by_name(payload.name, exclude_id=tag.id):
            raise ConflictError("That tag already exists.")
        tag.name = payload.name
        _audit(self.session, action=AuditAction.UPDATE, actor=actor,
               entity="tag", entity_id=tag.id, details={"name": tag.name})
        return tag

    async def delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        """Deleting a tag untags every course carrying it, and that is the
        intended effect.

        The 409-while-referenced rule the rest of this module follows does
        not apply: a department or a category is something a course *belongs
        to*, and blanking it loses a fact. A tag is a label, `course_tags`
        cascades cleanly, and re-tagging is a re-tag -- so the count goes in
        the audit record rather than in the way.
        """
        tag = await self._load(public_id)
        tagged = (await self.tags.course_counts([tag.id])).get(tag.id, 0)
        entity_id, name = tag.id, tag.name
        await self.session.delete(tag)
        _audit(self.session, action=AuditAction.DELETE, actor=actor,
               entity="tag", entity_id=entity_id, details={"name": name, "courses_untagged": tagged})

    async def _load(self, public_id: uuid.UUID) -> Tag:
        tag = await self.tags.get_by_public_id_full(public_id)
        if tag is None:
            raise NotFoundError("Tag not found.")
        return tag

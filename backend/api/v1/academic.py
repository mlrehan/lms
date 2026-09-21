"""Academic administration endpoints (spec §23).

Five routers over one permission pair: `academic.read` to look, and
`academic.create`/`update`/`delete` to change. Reading is granted to every
role — this is the vocabulary the course catalogue is described in, and a
student who cannot list departments cannot filter by one. Writing is the
administration's.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.core.privacy import visible_username
from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.administration import (
    AcademicYear,
    Category,
    Department,
    Semester,
    Tag,
)
from backend.schemas.administration import (
    AcademicYearCreateRequest,
    AcademicYearResponse,
    AcademicYearUpdateRequest,
    CategoryCreateRequest,
    CategoryResponse,
    CategoryUpdateRequest,
    DepartmentCreateRequest,
    DepartmentResponse,
    DepartmentUpdateRequest,
    SemesterCreateRequest,
    SemesterResponse,
    SemesterUpdateRequest,
    TagResponse,
    TagWriteRequest,
)
from backend.schemas.base import Page, PageParams
from backend.services.academic_service import (
    AcademicYearService,
    CategoryService,
    DepartmentService,
    SemesterService,
    TagService,
)

_READ = require_permissions(perm(Module.ACADEMIC, Action.READ))
_CREATE = require_permissions(perm(Module.ACADEMIC, Action.CREATE))
_UPDATE = require_permissions(perm(Module.ACADEMIC, Action.UPDATE))
_DELETE = require_permissions(perm(Module.ACADEMIC, Action.DELETE))

years_router = APIRouter(prefix="/academic-years", tags=["Academic administration"])
semesters_router = APIRouter(prefix="/semesters", tags=["Academic administration"])
departments_router = APIRouter(prefix="/departments", tags=["Academic administration"])
categories_router = APIRouter(prefix="/categories", tags=["Academic administration"])
tags_router = APIRouter(prefix="/tags", tags=["Academic administration"])


# =============================================================================
# ACADEMIC YEARS
# =============================================================================


def _year(year: AcademicYear, *, batch_count: int = 0) -> AcademicYearResponse:
    return AcademicYearResponse(
        public_id=year.public_id,
        label=year.label,
        start_date=year.start_date,
        end_date=year.end_date,
        is_current=year.is_current,
        semester_count=len(year.semesters),
        batch_count=batch_count,
    )


@years_router.get("", response_model=Page[AcademicYearResponse], summary="List academic years")
async def list_years(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(_READ)],
    current_only: Annotated[bool, Query()] = False,
) -> Page[AcademicYearResponse]:
    rows, total, counts = await AcademicYearService(session).list(params, current_only=current_only)
    return Page.build(
        [_year(r, batch_count=counts.get(r.id, 0)) for r in rows], total=total, params=params
    )


@years_router.post(
    "",
    response_model=AcademicYearResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an academic year",
)
async def create_year(
    payload: AcademicYearCreateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_CREATE)],
) -> AcademicYearResponse:
    """`is_current` is exclusive — promoting a year demotes whichever held it,
    so "the current year" is one row and not a count everyone has to trust."""
    return _year(await AcademicYearService(session).create(payload, actor=actor))


@years_router.get(
    "/{year_id}", response_model=AcademicYearResponse, summary="Get one academic year"
)
async def get_year(
    year_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> AcademicYearResponse:
    year, count = await AcademicYearService(session).get(year_id)
    return _year(year, batch_count=count)


@years_router.patch(
    "/{year_id}", response_model=AcademicYearResponse, summary="Update an academic year"
)
async def update_year(
    year_id: uuid.UUID,
    payload: AcademicYearUpdateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_UPDATE)],
) -> AcademicYearResponse:
    """Narrowing the dates so an existing semester would fall outside them is
    refused — the year is the container, and it cannot be shrunk out from
    under its own contents."""
    return _year(await AcademicYearService(session).update(year_id, payload, actor=actor))


@years_router.delete(
    "/{year_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an academic year"
)
async def delete_year(
    year_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_DELETE)],
) -> Response:
    """409 while any batch is scheduled in the year **or in one of its
    semesters** — the semesters cascade away with it, so counting only the
    direct reference would silently unschedule those batches."""
    await AcademicYearService(session).delete(year_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# SEMESTERS
# =============================================================================


def _semester(semester: Semester, *, batch_count: int = 0) -> SemesterResponse:
    return SemesterResponse(
        public_id=semester.public_id,
        academic_year_id=semester.academic_year.public_id,
        academic_year_label=semester.academic_year.label,
        name=semester.name,
        start_date=semester.start_date,
        end_date=semester.end_date,
        batch_count=batch_count,
    )


@semesters_router.get("", response_model=Page[SemesterResponse], summary="List semesters")
async def list_semesters(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(_READ)],
    academic_year_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[SemesterResponse]:
    rows, total, counts = await SemesterService(session).list(
        params, academic_year_id=academic_year_id
    )
    return Page.build(
        [_semester(r, batch_count=counts.get(r.id, 0)) for r in rows], total=total, params=params
    )


@semesters_router.post(
    "",
    response_model=SemesterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a semester",
)
async def create_semester(
    payload: SemesterCreateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_CREATE)],
) -> SemesterResponse:
    """Dates must fall inside the parent academic year. A term that starts
    before its year or runs past the end of it passes every start-before-end
    check and is still a data-entry error."""
    return _semester(await SemesterService(session).create(payload, actor=actor))


@semesters_router.get("/{semester_id}", response_model=SemesterResponse, summary="Get one semester")
async def get_semester(
    semester_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> SemesterResponse:
    semester, count = await SemesterService(session).get(semester_id)
    return _semester(semester, batch_count=count)


@semesters_router.patch(
    "/{semester_id}", response_model=SemesterResponse, summary="Update a semester"
)
async def update_semester(
    semester_id: uuid.UUID,
    payload: SemesterUpdateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_UPDATE)],
) -> SemesterResponse:
    """A semester cannot be moved to a different academic year — that is not
    an edit, it is a different term, and batches already scheduled into it
    would silently change year."""
    return _semester(await SemesterService(session).update(semester_id, payload, actor=actor))


@semesters_router.delete(
    "/{semester_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a semester"
)
async def delete_semester(
    semester_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_DELETE)],
) -> Response:
    await SemesterService(session).delete(semester_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# DEPARTMENTS
# =============================================================================


def _department(department: Department, *, course_count: int = 0) -> DepartmentResponse:
    head = department.head_tutor
    return DepartmentResponse(
        public_id=department.public_id,
        name=department.name,
        code=department.code,
        head_tutor_id=head.public_id if head else None,
        head_tutor_username=visible_username(head) if head else None,
        course_count=course_count,
    )


@departments_router.get("", response_model=Page[DepartmentResponse], summary="List departments")
async def list_departments(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(_READ)],
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[DepartmentResponse]:
    rows, total, counts = await DepartmentService(session).list(params, query=q)
    return Page.build(
        [_department(r, course_count=counts.get(r.id, 0)) for r in rows], total=total, params=params
    )


@departments_router.post(
    "",
    response_model=DepartmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a department",
)
async def create_department(
    payload: DepartmentCreateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_CREATE)],
) -> DepartmentResponse:
    """The head of a department must hold the TUTOR role — 422 otherwise."""
    return _department(await DepartmentService(session).create(payload, actor=actor))


@departments_router.get(
    "/{department_id}", response_model=DepartmentResponse, summary="Get one department"
)
async def get_department(
    department_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> DepartmentResponse:
    department, count = await DepartmentService(session).get(department_id)
    return _department(department, course_count=count)


@departments_router.patch(
    "/{department_id}", response_model=DepartmentResponse, summary="Update a department"
)
async def update_department(
    department_id: uuid.UUID,
    payload: DepartmentUpdateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_UPDATE)],
) -> DepartmentResponse:
    """Vacating the head-of-department post uses `clear_head_tutor: true`,
    not `head_tutor_id: null` — with optional fields omitted from the body,
    "set to nothing" and "not sent" are the same JSON."""
    return _department(await DepartmentService(session).update(department_id, payload, actor=actor))


@departments_router.delete(
    "/{department_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a department"
)
async def delete_department(
    department_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_DELETE)],
) -> Response:
    """409 while courses still belong to it. The foreign key is SET NULL, so
    without this guard the delete would succeed and quietly blank the
    department on every one of them."""
    await DepartmentService(session).delete(department_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# CATEGORIES
# =============================================================================


def _category(
    category: Category, *, child_count: int = 0, course_count: int = 0
) -> CategoryResponse:
    parent = category.parent
    return CategoryResponse(
        public_id=category.public_id,
        name=category.name,
        parent_id=parent.public_id if parent else None,
        parent_name=parent.name if parent else None,
        child_count=child_count,
        course_count=course_count,
    )


@categories_router.get("", response_model=Page[CategoryResponse], summary="List categories")
async def list_categories(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(_READ)],
    parent_id: Annotated[uuid.UUID | None, Query(description="Children of this category.")] = None,
    top_level: Annotated[bool, Query(description="Only categories with no parent.")] = False,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[CategoryResponse]:
    """The tree is walked a level at a time (`top_level=true`, then
    `parent_id=`), not returned nested — a nested response has no useful
    paging and grows without bound as the catalogue does."""
    rows, total, children, courses = await CategoryService(session).list(
        params, parent_id=parent_id, top_level=top_level, query=q
    )
    items = [
        _category(r, child_count=children.get(r.id, 0), course_count=courses.get(r.id, 0))
        for r in rows
    ]
    return Page.build(items, total=total, params=params)


@categories_router.post(
    "",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a category",
)
async def create_category(
    payload: CategoryCreateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_CREATE)],
) -> CategoryResponse:
    return _category(await CategoryService(session).create(payload, actor=actor))


@categories_router.get(
    "/{category_id}", response_model=CategoryResponse, summary="Get one category"
)
async def get_category(
    category_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> CategoryResponse:
    category, children, courses = await CategoryService(session).get(category_id)
    return _category(category, child_count=children, course_count=courses)


@categories_router.patch(
    "/{category_id}", response_model=CategoryResponse, summary="Update or move a category"
)
async def update_category(
    category_id: uuid.UUID,
    payload: CategoryUpdateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_UPDATE)],
) -> CategoryResponse:
    """Moving a category inside its own subtree is refused: the subtree would
    be detached from the tree entirely and reachable from nowhere."""
    return _category(await CategoryService(session).update(category_id, payload, actor=actor))


@categories_router.delete(
    "/{category_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a category"
)
async def delete_category(
    category_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_DELETE)],
) -> Response:
    """409 while it has sub-categories or courses. Both foreign keys are SET
    NULL, so the delete would otherwise promote the children to top level and
    uncategorise the courses, with nothing reported."""
    await CategoryService(session).delete(category_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# TAGS
# =============================================================================


def _tag(tag: Tag, *, course_count: int = 0) -> TagResponse:
    return TagResponse(public_id=tag.public_id, name=tag.name, course_count=course_count)


@tags_router.get("", response_model=Page[TagResponse], summary="List tags")
async def list_tags(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(_READ)],
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[TagResponse]:
    rows, total, counts = await TagService(session).list(params, query=q)
    return Page.build(
        [_tag(r, course_count=counts.get(r.id, 0)) for r in rows], total=total, params=params
    )


@tags_router.post(
    "", response_model=TagResponse, status_code=status.HTTP_201_CREATED, summary="Create a tag"
)
async def create_tag(
    payload: TagWriteRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_CREATE)],
) -> TagResponse:
    return _tag(await TagService(session).create(payload, actor=actor))


@tags_router.get("/{tag_id}", response_model=TagResponse, summary="Get one tag")
async def get_tag(
    tag_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> TagResponse:
    tag, count = await TagService(session).get(tag_id)
    return _tag(tag, course_count=count)


@tags_router.patch("/{tag_id}", response_model=TagResponse, summary="Rename a tag")
async def update_tag(
    tag_id: uuid.UUID,
    payload: TagWriteRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_UPDATE)],
) -> TagResponse:
    return _tag(await TagService(session).update(tag_id, payload, actor=actor))


@tags_router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a tag")
async def delete_tag(
    tag_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_DELETE)],
) -> Response:
    """Unlike a department or a category, this is **not** refused when in use.
    A tag is a label and untagging is exactly what deleting one means; the
    number of courses affected goes into the audit record."""
    await TagService(session).delete(tag_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

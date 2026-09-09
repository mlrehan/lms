"""Course and batch endpoints (spec §5, §6)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.api.deps import CurrentUser, require_permissions
# One definition of the batch response, imported rather than copied. This
# file used to carry its own duplicate, and the two drifted the moment a
# field was added: the batch *create* route lives here while every other
# batch route lives in `batches.py`, so a change made in one place was
# invisible in the other and the new calendar fields came back empty from
# create alone.
from backend.api.v1.batches import batch_response
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.schemas.base import Page, PageParams
from backend.schemas.batch import (
    BatchCreateRequest,
    BatchResponse,
    BatchSummary,
    BatchUpdateRequest,
)
from backend.schemas.administration import SetCourseTagsRequest
from backend.schemas.course import (
    CourseCreateRequest,
    CourseResponse,
    CourseStatusRequest,
    CourseSummary,
    CourseTutorsRequest,
    CourseUpdateRequest,
)
from backend.services.batch_service import BatchService
from backend.services.course_service import CourseService
from backend.utils.enums import CourseStatus, Levels

router = APIRouter(prefix="/courses", tags=["Courses"])


def _course_response(course, batch_count: int = 0) -> CourseResponse:  # type: ignore[no-untyped-def]
    """Built field by field rather than by `model_validate(course)`.

    `Course.category_id` is the internal integer foreign key while
    `CourseResponse.category_id` is the category's public UUID -- same name,
    different value, and attribute-based validation would happily try to
    coerce one into the other. Naming them apart in the response would only
    move the confusion to the client.
    """
    category, department = course.category, course.department
    return CourseResponse(
        public_id=course.public_id,
        title=course.title,
        code=course.code,
        status=course.status,
        level=course.level,
        duration_hours=course.duration_hours,
        price=course.price,
        course_picture=course.course_picture,
        description=course.description,
        prerequisites=course.prerequisites,
        course_link=course.course_link,
        category_id=category.public_id if category else None,
        category_name=category.name if category else None,
        department_id=department.public_id if department else None,
        department_name=department.name if department else None,
        tags=sorted(t.name for t in (course.tags or [])),
        created_at=course.created_at,
        updated_at=course.updated_at,
        tutors=[t.username for t in (course.tutors or [])],
        batch_count=batch_count,
    )


@router.get("", response_model=Page[CourseSummary], summary="Browse the course catalogue")
async def list_courses(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.COURSE, Action.READ)))],
    query: Annotated[str | None, Query(max_length=100)] = None,
    course_status: Annotated[CourseStatus | None, Query(alias="status")] = None,
    level: Annotated[Levels | None, Query()] = None,
    category_id: Annotated[uuid.UUID | None, Query()] = None,
    department_id: Annotated[uuid.UUID | None, Query()] = None,
    tag_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[CourseSummary]:
    """The catalogue is deliberately not row-scoped -- a Corporate Manager
    must be able to find a course to enrol employees into. What *is* hidden
    from ordinary callers is DRAFT and ARCHIVED courses, which the
    institution is not currently offering. An assigned tutor still sees their
    own course while it is a draft."""
    courses, total = await CourseService(session).list_courses(
        params,
        actor=actor,
        query=query,
        status=course_status,
        level=level,
        category_id=category_id,
        department_id=department_id,
        tag_id=tag_id,
    )
    return Page.build(
        [CourseSummary.model_validate(c) for c in courses], total=total, params=params
    )


@router.post(
    "", response_model=CourseResponse, status_code=status.HTTP_201_CREATED, summary="Create a course"
)
async def create_course(
    payload: CourseCreateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.COURSE, Action.CREATE)))],
) -> CourseResponse:
    """Always created as DRAFT -- publishing is a separate, deliberate act."""
    return _course_response(await CourseService(session).create(payload, actor=actor))


@router.get("/{course_id}", response_model=CourseResponse, summary="Get one course")
async def get_course(
    course_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.COURSE, Action.READ)))],
) -> CourseResponse:
    service = CourseService(session)
    course = await service.get(course_id, actor=actor)
    return _course_response(course, await service.courses.count_batches(course.id))


@router.patch("/{course_id}", response_model=CourseResponse, summary="Update a course")
async def update_course(
    course_id: uuid.UUID,
    payload: CourseUpdateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.COURSE, Action.UPDATE)))],
) -> CourseResponse:
    return _course_response(await CourseService(session).update(course_id, payload, actor=actor))


@router.put(
    "/{course_id}/status",
    response_model=CourseResponse,
    summary="Move a course through its lifecycle",
)
async def set_course_status(
    course_id: uuid.UUID,
    payload: CourseStatusRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.COURSE, Action.PUBLISH)))
    ],
) -> CourseResponse:
    """Draft → Published → Running → Completed → Archived. Illegal jumps are
    refused with 409 and the list of transitions that *are* available."""
    return _course_response(
        await CourseService(session).set_status(course_id, payload.status, actor=actor)
    )


@router.put(
    "/{course_id}/tutors",
    response_model=CourseResponse,
    summary="Assign tutors to a course",
)
async def set_course_tutors(
    course_id: uuid.UUID,
    payload: CourseTutorsRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.COURSE, Action.UPDATE)))],
) -> CourseResponse:
    """This is an authorization write, not metadata: `tutor_courses` is what
    grants a tutor sight of the course's batches and the students enrolled in
    them."""
    return _course_response(
        await CourseService(session).set_tutors(course_id, payload.tutors, actor=actor)
    )


@router.delete(
    "/{course_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an empty course"
)
async def delete_course(
    course_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.COURSE, Action.DELETE)))],
) -> Response:
    """Refused once the course has batches -- archive it instead, so the
    enrollments and grades hanging off those batches keep their context."""
    await CourseService(session).soft_delete(course_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# BATCHES (nested under a course)
# =============================================================================


@router.get(
    "/{course_id}/batches",
    response_model=Page[BatchSummary],
    summary="List a course's batches",
)
async def list_course_batches(
    course_id: uuid.UUID,
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.BATCH, Action.READ)))],
    is_active: Annotated[bool | None, Query()] = None,
) -> Page[BatchSummary]:
    batches, total = await BatchService(session).list_batches(
        params, actor=actor, course_public_id=course_id, is_active=is_active
    )
    return Page.build(
        [BatchSummary.model_validate(b) for b in batches], total=total, params=params
    )


@router.post(
    "/{course_id}/batches",
    response_model=BatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a batch",
)
async def create_batch(
    course_id: uuid.UUID,
    payload: BatchCreateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(perm(Module.BATCH, Action.CREATE)))],
) -> BatchResponse:
    service = BatchService(session)
    batch = await service.create(course_id, payload, actor=actor)
    return await batch_response(service, batch)


@router.put(
    "/{course_id}/tags",
    response_model=CourseResponse,
    summary="Replace a course's tags",
)
async def set_course_tags(
    course_id: uuid.UUID,
    payload: SetCourseTagsRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.COURSE, Action.UPDATE)))
    ],
) -> CourseResponse:
    """The complete set, not a delta — tags omitted from the list are removed.
    An unknown tag id is a 404 for the whole request rather than a silent
    partial apply, so the caller never has to diff what they sent against what
    came back to find out which one was wrong."""
    service = CourseService(session)
    course = await service.set_tags(course_id, payload.tag_ids, actor=actor)
    return _course_response(course, await service.courses.count_batches(course.id))

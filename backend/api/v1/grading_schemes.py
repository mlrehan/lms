"""Configuring how marks become grades (spec §6, §13, §20).

The most consequential configuration in the academic system: saving a weighting
re-grades every student in every course that uses the scheme, at once. So
reading is `grading_scheme.read` (tutors and administrators, who need to explain
a mark) and every write is `grading_scheme.manage` -- held by the Super Admin
alone, matching §20's "configure grading" sitting with them and not with the
administrator who runs daily operations.

Activation is a separate endpoint from editing, deliberately. Weights are
entered a row at a time, so a scheme in progress legitimately does not total
100; the check belongs at the moment it starts affecting people, not on every
keystroke.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select

from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.course import Course
from backend.models.grading import GradingScheme
from backend.schemas.grading_scheme import (
    AssignSchemeRequest,
    SchemeAssignment,
    SchemeUsage,
    BandResponse,
    ComponentWeightResponse,
    GradingSchemeCreateRequest,
    GradingSchemeResponse,
    GradingSchemeSummary,
    GradingSchemeUpdateRequest,
    SetBandsRequest,
    SetComponentsRequest,
)
from backend.services.batch_service import BatchService
from backend.services.course_service import CourseService
from backend.services.grading_scheme_service import GradingSchemeService

router = APIRouter(prefix="/grading-schemes", tags=["Grading schemes"])

_READ = require_permissions(perm(Module.GRADING_SCHEME, Action.READ))
_MANAGE = require_permissions(perm(Module.GRADING_SCHEME, Action.MANAGE))


def _summary(row: GradingScheme) -> GradingSchemeSummary:
    return GradingSchemeSummary(
        public_id=row.public_id,
        name=row.name,
        description=row.description,
        is_default=row.is_default,
        is_active=row.is_active,
        scale_type=row.scale_type,
        missing_mark_policy=row.missing_mark_policy,
        passing_percentage=row.passing_percentage,
        total_weight=GradingSchemeService.total_weight(row),
        component_count=len(row.components or []),
    )


def _detail(
    row: GradingScheme,
    *,
    courses: list | None = None,
    batches: list | None = None,
) -> GradingSchemeResponse:
    courses, batches = courses or [], batches or []
    return GradingSchemeResponse(
        **_summary(row).model_dump(),
        components=[
            ComponentWeightResponse(
                public_id=c.public_id,
                component_type=c.component_type,
                label=c.label,
                weight_percentage=c.weight_percentage,
                is_mandatory=c.is_mandatory,
                passing_percentage=c.passing_percentage,
            )
            for c in (row.components or [])
        ],
        bands=[
            BandResponse(
                min_score=b.min_score,
                max_score=b.max_score,
                letter_grade=b.letter_grade,
                gpa_points=b.gpa_points,
                is_pass=b.is_pass,
            )
            for b in sorted(row.bands or [], key=lambda b: Decimal(b.min_score), reverse=True)
        ],
        courses_using=len(courses),
        batches_using=len(batches),
        applied_to_courses=[SchemeUsage(public_id=pid, label=title) for pid, title in courses],
        applied_to_batches=[
            SchemeUsage(public_id=pid, label=code, course_title=title) for pid, code, title in batches
        ],
    )


async def _with_usage(session, row: GradingScheme) -> GradingSchemeResponse:  # noqa: ANN001
    courses, batches = await GradingSchemeService(session).usage(row.id)
    return _detail(row, courses=courses, batches=batches)


@router.get("", response_model=list[GradingSchemeSummary], summary="List grading schemes")
async def list_schemes(
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> list[GradingSchemeSummary]:
    return [_summary(r) for r in await GradingSchemeService(session).list_schemes()]


@router.get(
    "/{scheme_id}",
    response_model=GradingSchemeResponse,
    summary="One scheme, with its weightings and grade bands",
)
async def get_scheme(
    scheme_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> GradingSchemeResponse:
    row = await GradingSchemeService(session).get(scheme_id)
    return await _with_usage(session, row)


@router.post(
    "",
    response_model=GradingSchemeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a grading scheme",
)
async def create_scheme(
    payload: GradingSchemeCreateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_MANAGE)],
) -> GradingSchemeResponse:
    """Created inactive and never as the default.

    Becoming the institution's default is a separate, deliberate act: a new
    scheme silently taking over every course would re-grade the institution by
    accident.
    """
    row = await GradingSchemeService(session).create(
        actor=actor,
        name=payload.name,
        description=payload.description,
        scale_type=payload.scale_type,
        missing_mark_policy=payload.missing_mark_policy,
        passing_percentage=payload.passing_percentage,
    )
    return _detail(row)


@router.patch(
    "/{scheme_id}", response_model=GradingSchemeResponse, summary="Rename or re-configure a scheme"
)
async def update_scheme(
    scheme_id: uuid.UUID,
    payload: GradingSchemeUpdateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_MANAGE)],
) -> GradingSchemeResponse:
    service = GradingSchemeService(session)
    row = await service.get(scheme_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(row, field, value)
    await session.flush()
    return await _with_usage(session, row)


@router.put(
    "/{scheme_id}/components",
    response_model=GradingSchemeResponse,
    summary="Set the weightings",
)
async def set_components(
    scheme_id: uuid.UUID,
    payload: SetComponentsRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_MANAGE)],
) -> GradingSchemeResponse:
    """Replaces the whole set. Not validated against 100 here -- a scheme is
    edited a row at a time, and refusing every intermediate state would make
    the editor unusable. `POST /activate` is where the total is checked."""
    service = GradingSchemeService(session)
    row = await service.set_components(
        scheme_id, [c.model_dump() for c in payload.components], actor=actor
    )
    return await _with_usage(session, row)


@router.put(
    "/{scheme_id}/bands", response_model=GradingSchemeResponse, summary="Set the grade ladder"
)
async def set_bands(
    scheme_id: uuid.UUID,
    payload: SetBandsRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_MANAGE)],
) -> GradingSchemeResponse:
    """Overlapping bands are refused: a mark of 80 falling into both "A" and
    "B" would make the grade depend on row order."""
    service = GradingSchemeService(session)
    row = await service.set_bands(scheme_id, [b.model_dump() for b in payload.bands], actor=actor)
    return await _with_usage(session, row)


@router.post(
    "/{scheme_id}/activate",
    response_model=GradingSchemeResponse,
    summary="Make a scheme usable",
)
async def activate_scheme(
    scheme_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_MANAGE)],
) -> GradingSchemeResponse:
    """Refused unless the weights total 100%.

    This is the moment the scheme starts deciding people's results, so it is
    the moment the total has to be right. The refusal names how far off it is,
    because "invalid" without a number sends somebody hunting.
    """
    service = GradingSchemeService(session)
    row = await service.activate(scheme_id, actor=actor)
    return await _with_usage(session, row)


@router.post(
    "/{scheme_id}/make-default",
    response_model=GradingSchemeResponse,
    summary="Make this the institution's default scheme",
)
async def make_default(
    scheme_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_MANAGE)],
) -> GradingSchemeResponse:
    """Every course without an override is graded under the default, so this
    changes results across the institution. It is refused for an inactive
    scheme, and the previous default is cleared in the same transaction --
    the database permits exactly one."""
    service = GradingSchemeService(session)
    row = await service.make_default(scheme_id, actor=actor)
    return await _with_usage(session, row)


# -- which scheme a course or batch is graded under --------------------------
#
# Their own routes rather than fields on the course and batch forms: those are
# gated on `course.update` / `batch.update`, which an Administrator holds, and
# pointing a course at another scheme re-grades every student in it at once --
# the same decision as editing a weight, so it needs `grading_scheme.manage`.

assignment_router = APIRouter(tags=["Grading schemes"])


async def _assignment(
    service: GradingSchemeService, *, course, batch=None  # noqa: ANN001
) -> SchemeAssignment:
    own_id = (batch.grading_scheme_id if batch is not None else course.grading_scheme_id)
    own = None
    if own_id is not None:
        own = (
            await service.session.execute(select(GradingScheme).where(GradingScheme.id == own_id))
        ).scalar_one_or_none()
    effective, source = await service.resolve(
        course_id=course.id, batch_id=batch.id if batch is not None else None
    )
    return SchemeAssignment(
        own_scheme_id=own.public_id if own else None,
        own_scheme_name=own.name if own else None,
        effective_scheme_id=effective.public_id if effective else None,
        effective_scheme_name=effective.name if effective else None,
        source=source.value,
    )


@assignment_router.get(
    "/courses/{course_id}/grading-scheme",
    response_model=SchemeAssignment,
    summary="Which scheme a course is graded under",
)
async def get_course_scheme(
    course_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> SchemeAssignment:
    course = await CourseService(session).get(course_id, actor=actor)
    return await _assignment(GradingSchemeService(session), course=course)


@assignment_router.put(
    "/courses/{course_id}/grading-scheme",
    response_model=SchemeAssignment,
    summary="Grade a course under a scheme, or under the institution default",
)
async def set_course_scheme(
    course_id: uuid.UUID,
    payload: AssignSchemeRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_MANAGE)],
) -> SchemeAssignment:
    """Re-grades every student in the course whose batch has no scheme of its
    own. Finalised transcripts are frozen and keep the scheme they were issued
    under."""
    service = GradingSchemeService(session)
    course = await service.assign_to_course(course_id, payload.scheme_id, actor=actor)
    return await _assignment(service, course=course)


@assignment_router.get(
    "/batches/{batch_id}/grading-scheme",
    response_model=SchemeAssignment,
    summary="Which scheme a batch is graded under",
)
async def get_batch_scheme(
    batch_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_READ)],
) -> SchemeAssignment:
    batch = await BatchService(session).get(batch_id, actor=actor)
    return await _assignment(GradingSchemeService(session), course=batch.course, batch=batch)


@assignment_router.put(
    "/batches/{batch_id}/grading-scheme",
    response_model=SchemeAssignment,
    summary="Grade a batch under its own scheme, or its course's",
)
async def set_batch_scheme(
    batch_id: uuid.UUID,
    payload: AssignSchemeRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_MANAGE)],
) -> SchemeAssignment:
    service = GradingSchemeService(session)
    batch = await service.assign_to_batch(batch_id, payload.scheme_id, actor=actor)
    course = (
        await session.execute(select(Course).where(Course.id == batch.course_id))
    ).scalar_one()
    return await _assignment(service, course=course, batch=batch)

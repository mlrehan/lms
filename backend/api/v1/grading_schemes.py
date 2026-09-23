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
    BandResponse,
    ComponentWeightResponse,
    GradingSchemeCreateRequest,
    GradingSchemeResponse,
    GradingSchemeSummary,
    GradingSchemeUpdateRequest,
    SetBandsRequest,
    SetComponentsRequest,
)
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


def _detail(row: GradingScheme, *, courses_using: int = 0) -> GradingSchemeResponse:
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
        courses_using=courses_using,
    )


async def _courses_using(session, scheme_id: int) -> int:  # noqa: ANN001
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Course)
                .where(Course.grading_scheme_id == scheme_id)
            )
        ).scalar_one()
    )


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
    return _detail(row, courses_using=await _courses_using(session, row.id))


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
    return _detail(row, courses_using=await _courses_using(session, row.id))


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
    return _detail(row, courses_using=await _courses_using(session, row.id))


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
    return _detail(row, courses_using=await _courses_using(session, row.id))


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
    return _detail(row, courses_using=await _courses_using(session, row.id))


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
    return _detail(row, courses_using=await _courses_using(session, row.id))

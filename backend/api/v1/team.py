"""The people in the caller's care: a corporate manager's employees, or a guardian's wards (`team.read`).

Who appears is decided by the same enrolment-visibility scope the rest of the system uses, not by anything
in the request: there is no parameter that names a person's organisation or a manager, so there is nothing to
tamper with. An id outside the caller's people is a 404.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.schemas.team import TeamMemberDetail, TeamOverview
from backend.services.team_service import TeamService

router = APIRouter(prefix="/team", tags=["Team"])

_READ = require_permissions(perm(Module.TEAM, Action.READ))


@router.get("", response_model=TeamOverview, summary="The people in my care, with their progress")
async def team(session: DBSession, actor: Annotated[CurrentUser, Depends(_READ)]) -> TeamOverview:
    return await TeamService(session).overview(actor=actor)


@router.get("/{user_id}", response_model=TeamMemberDetail, summary="One person in my care, in detail")
async def team_member(
    user_id: uuid.UUID, session: DBSession, actor: Annotated[CurrentUser, Depends(_READ)]
) -> TeamMemberDetail:
    return await TeamService(session).member(user_id, actor=actor)

"""Dashboard endpoint (spec §17)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.deps import CurrentUser
from backend.db.dependencies import DBSession
from backend.schemas.reporting import DashboardResponse
from backend.schemas.today import TodayClasses
from backend.services.today_service import TodayService
from backend.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("", response_model=DashboardResponse, summary="Your dashboard")
async def dashboard(
    session: DBSession,
    actor: CurrentUser,
) -> DashboardResponse:
    """One endpoint, shaped by who is asking.

    Deliberately gated on **authentication only** — no `require_permissions`.
    A dashboard assembles things the caller can already reach, so each panel
    is gated on the permission for its own data and a missing permission drops
    the tile rather than failing the request. Gating the whole endpoint on
    `report.read` is the obvious move and is backwards: neither Student nor
    Guardian holds it, so the two roles whose dashboard matters most would be
    locked out of their own.

    `panels` names what came back — `personal` always, then `student`,
    `teaching`, `care` and `institution` for callers they apply to. Somebody
    who both teaches and has a child enrolled gets both; roles are additive
    here as everywhere else.

    Every figure is scoped exactly as the corresponding listing is: a count
    computed over rows the caller cannot see would leak the same information
    one number at a time.
    """
    return await DashboardService(session).build(actor=actor)


@router.get(
    "/today",
    response_model=TodayClasses,
    summary="Today's classes",
)
async def today(
    session: DBSession,
    actor: CurrentUser,
) -> TodayClasses:
    """The classes scheduled for the caller's own today.

    Authentication only, like the dashboard itself: the rows are scoped to what
    this caller can already see, so a tutor gets their classes and an
    administrator gets the institution's.

    "Today" is computed in the caller's timezone and the zone is named in the
    response -- the rows are stored in UTC, and a day boundary taken there puts
    an evening class on the wrong day for the person teaching it.
    """
    return await TodayService(session).today(actor=actor)

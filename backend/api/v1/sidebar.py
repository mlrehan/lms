"""The numbers beside the menu.

Open to any authenticated caller, like the dashboard and for the same reason:
it is an assembly of things they can already reach, and each number is gated on
the permission for its own data. Gating the endpoint itself would lock out the
roles whose badges matter most.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.deps import CurrentUser, DBSession
from backend.schemas.sidebar import SidebarCountsResponse
from backend.services.sidebar_counts_service import SidebarCountsService

router = APIRouter(tags=["Sidebar"])


@router.get(
    "/sidebar/counts",
    response_model=SidebarCountsResponse,
    summary="Badge counts for the menu",
)
async def sidebar_counts(
    session: DBSession,
    actor: CurrentUser,
) -> SidebarCountsResponse:
    """Every badge the caller is entitled to, in one request.

    A key the caller may not see is **absent**, not zero: a client cannot
    distinguish "you have none" from "you may not know" if both are `0`, and
    the console renders no badge for a missing key.

    Each number comes from the same scope objects the matching listing uses, so
    a badge and the screen behind it cannot disagree unless the listing is
    wrong.
    """
    counts = await SidebarCountsService(session).counts(actor=actor)
    return SidebarCountsResponse(counts=counts)

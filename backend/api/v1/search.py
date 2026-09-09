"""Global search (spec §22)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.api.deps import CurrentUser
from backend.db.dependencies import DBSession
from backend.schemas.search import SearchResponse, SearchType
from backend.services.search_service import (
    DEFAULT_PER_TYPE,
    MAX_PER_TYPE,
    MIN_QUERY,
    SearchService,
)

router = APIRouter(prefix="/search", tags=["Search"])


@router.get("", response_model=SearchResponse, summary="Search across the institution")
async def search(
    session: DBSession,
    actor: CurrentUser,
    q: Annotated[str, Query(min_length=MIN_QUERY, max_length=100)],
    types: Annotated[
        list[SearchType] | None, Query(description="Repeatable; omit to search everything.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PER_TYPE)] = DEFAULT_PER_TYPE,
) -> SearchResponse:
    """Gated on **authentication only**, like `/dashboard`, and for the same
    reason: search returns nothing the caller could not already list, so a
    permission of its own would gate an aggregation rather than any data.
    Each *group* is gated on that domain's own read permission, and each
    result set is produced by the domain's own scoped query — search calls
    `CourseRepository.search`, not a query of its own, so it cannot show a
    row the courses endpoint would hide.

    A type the caller cannot read at all is reported in `skipped` rather than
    returned as an empty group: an empty `user` group implies nobody matched,
    which is a different and misleading claim.

    Groups are capped independently so one crowded type cannot squeeze out
    the rest; each reports the `total` **this caller may see**, never a global
    count.
    """
    return await SearchService(session).search(
        actor=actor, query=q, types=types, per_type=limit
    )

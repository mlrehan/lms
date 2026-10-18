"""Who is actually using the system right now.

Gated on seeing the whole institution, because this is a list of *other people*
and when they were last at their desk. `user.read` alone is not enough: every
role holds it, since it is how a tutor resolves the name beside a mark.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.core.privacy import visible_username
from backend.db.dependencies import DBSession
from backend.models.identity.user import User
from backend.realtime.presence import DEFAULT_WINDOW_SECONDS
from backend.schemas.base import Page, PageParams
from backend.schemas.presence import ActiveUserRow, PresenceSummary
from backend.services.scope import ScopeResolver
from backend.utils.enums import UserStatus

from fastapi import Depends

router = APIRouter(tags=["Presence"])

_USER_READ = perm(Module.USER, Action.READ)


@router.get(
    "/presence/active",
    response_model=PresenceSummary,
    summary="Who is online now",
)
async def active_users(
    request: Request,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(_USER_READ))],
    params: Annotated[PageParams, Depends()],
    state: Annotated[Literal["online", "offline", "all"], Query()] = "online",
) -> PresenceSummary:
    """Genuinely active people, not merely unexpired sessions.

    "Online" means a browser is holding its realtime connection open now. A
    token that has not expired proves only that somebody signed in at some
    point, which is why this is not built from sessions.

    Offline is a timeout and never an event: an entry stops being refreshed and
    falls out of the window. So a crashed browser, a closed laptop and a lost
    network all behave like a clean sign-out, just later.
    """
    if not ScopeResolver.is_unrestricted(actor):
        # A list of who else is at their desk is an institution-wide view.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seeing who is online needs institution-wide access.",
        )

    store = getattr(request.app.state, "presence", None)
    seen: dict[int, float] = {} if store is None else await store.online()

    stmt = (
        select(User)
        .options(selectinload(User.roles))
        .where(User.deleted_at.is_(None), User.status != UserStatus.DELETED)
    )
    if state == "online":
        if not seen:
            return PresenceSummary(
                online=0,
                total=0,
                window_seconds=DEFAULT_WINDOW_SECONDS,
                realtime_enabled=store is not None,
                users=Page.build([], total=0, params=params),
            )
        stmt = stmt.where(User.id.in_(list(seen)))

    rows = list((await session.execute(stmt)).scalars().unique())
    if state == "offline":
        rows = [u for u in rows if u.id not in seen]

    rows.sort(key=lambda u: seen.get(u.id, 0.0), reverse=True)
    total = len(rows)
    window = rows[params.offset : params.offset + params.limit]

    return PresenceSummary(
        online=len(seen),
        total=total,
        window_seconds=DEFAULT_WINDOW_SECONDS,
        realtime_enabled=store is not None,
        users=Page.build(
            [_row(user, seen.get(user.id)) for user in window],
            total=total,
            params=params,
        ),
    )


def _row(user: User, last_seen: float | None) -> ActiveUserRow:
    return ActiveUserRow(
        public_id=user.public_id,
        name=visible_username(user),
        roles=sorted(r.name for r in (user.roles or [])),
        online=last_seen is not None,
        # Where they *say* they are, from their own profile -- not an IP
        # lookup. Deriving a location from an address would be telling an
        # administrator where a colleague is sitting, which nobody consented to
        # and which this product has never collected for that purpose.
        location=_location(user),
        last_seen_at=(
            datetime.fromtimestamp(last_seen, tz=timezone.utc) if last_seen else None
        ),
        last_login_at=user.last_login,
    )


def _location(user: User) -> str | None:
    # Both relationships are `lazy="selectin"`, so they arrive with the user
    # and reading them here cannot become a lazy load inside the response
    # mapper -- the failure mode that made saving class performance a 500.
    parts = [
        getattr(getattr(user, "current_city", None), "name", None),
        getattr(getattr(user, "country", None), "name", None),
    ]
    named = [p for p in parts if p]
    return ", ".join(named) if named else None

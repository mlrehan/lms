"""Announcement endpoints (spec §16)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.core.privacy import visible_username
from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.notification import Announcement
from backend.schemas.announcement import (
    AnnouncementResponse,
    CreateAnnouncementRequest,
    UpdateAnnouncementRequest,
)
from backend.schemas.base import Page, PageParams
from backend.schemas.messaging import PartyRef
from backend.services.announcement_service import AnnouncementService

router = APIRouter(prefix="/announcements", tags=["Announcements"])


def _response(announcement: Announcement) -> AnnouncementResponse:
    now = datetime.now(timezone.utc)
    live = (announcement.start_at is None or announcement.start_at <= now) and (
        announcement.end_at is None or announcement.end_at > now
    )
    author = announcement.author
    return AnnouncementResponse(
        public_id=announcement.public_id,
        title=announcement.title,
        content=announcement.content,
        author=(
            PartyRef(
                public_id=author.public_id,
                username=visible_username(author),
                full_name=author.full_name,
            )
            if author
            else None
        ),
        course_id=announcement.course.public_id if announcement.course else None,
        course_title=announcement.course.title if announcement.course else None,
        batch_id=announcement.batch.public_id if announcement.batch else None,
        batch_code=announcement.batch.batch_code if announcement.batch else None,
        role_scope=announcement.role_scope,
        start_at=announcement.start_at,
        end_at=announcement.end_at,
        pinned=announcement.pinned,
        is_live=live,
    )


@router.get("", response_model=Page[AnnouncementResponse], summary="Your announcement feed")
async def list_announcements(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ANNOUNCEMENT, Action.READ)))
    ],
    mine: Annotated[bool, Query(description="Only announcements you posted.")] = False,
    course_id: Annotated[uuid.UUID | None, Query()] = None,
    batch_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[AnnouncementResponse]:
    """Filtered to the audience you belong to: an announcement narrowed to a
    course, batch or role you are not part of is not in your feed, and one
    narrowed to none of them reaches everybody. Only currently-live notices
    are returned unless you hold `institution.view_all`, or asked for
    `mine=true` — an author needs to see what they scheduled before it
    publishes and what has since lapsed."""
    rows, total = await AnnouncementService(session).list_feed(
        params, actor=actor, mine=mine, course_id=course_id, batch_id=batch_id
    )
    return Page.build([_response(r) for r in rows], total=total, params=params)


@router.post(
    "",
    response_model=AnnouncementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Post an announcement",
)
async def create_announcement(
    payload: CreateAnnouncementRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ANNOUNCEMENT, Action.CREATE)))
    ],
) -> AnnouncementResponse:
    """A tutor must target a course or batch they teach. Leaving all three
    targeting fields empty is an institution-wide notice and is refused with
    403 for anyone without `institution.view_all` — otherwise the grant that
    lets a tutor address their class also lets them address the school."""
    return _response(await AnnouncementService(session).create(payload, actor=actor))


@router.get(
    "/{announcement_id}", response_model=AnnouncementResponse, summary="Get one announcement"
)
async def get_announcement(
    announcement_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ANNOUNCEMENT, Action.READ)))
    ],
) -> AnnouncementResponse:
    return _response(await AnnouncementService(session).get(announcement_id, actor=actor))


@router.patch(
    "/{announcement_id}", response_model=AnnouncementResponse, summary="Edit an announcement"
)
async def update_announcement(
    announcement_id: uuid.UUID,
    payload: UpdateAnnouncementRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ANNOUNCEMENT, Action.UPDATE)))
    ],
) -> AnnouncementResponse:
    """Authors can edit their own; `institution.view_all` can edit any. The
    targeting columns are not editable — re-aiming a notice that people have
    already read at a different audience is a new announcement, not an edit."""
    return _response(
        await AnnouncementService(session).update(announcement_id, payload, actor=actor)
    )


@router.delete(
    "/{announcement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Withdraw an announcement",
)
async def delete_announcement(
    announcement_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ANNOUNCEMENT, Action.DELETE)))
    ],
) -> Response:
    await AnnouncementService(session).delete(announcement_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""Course discussion endpoints (spec §16)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.identity.user import User
from backend.models.messaging import CourseDiscussion, DiscussionReply
from backend.schemas.base import Page, PageParams
from backend.schemas.discussion import (
    CreateDiscussionRequest,
    DiscussionReplyResponse,
    DiscussionResponse,
    ReplyRequest,
    UpdateDiscussionRequest,
)
from backend.schemas.messaging import PartyRef
from backend.services.discussion_service import DiscussionService

router = APIRouter(prefix="/discussions", tags=["Discussions"])

# Replies are addressed directly for edit/delete, so they get their own
# top-level prefix rather than a nested path: a reply's id is unique on its
# own, and `/discussions/{a}/replies/{b}` would invite callers to pass a
# mismatched pair and expect one of them to win.
replies_router = APIRouter(prefix="/discussion-replies", tags=["Discussions"])


def _party(user: User | None) -> PartyRef | None:
    if user is None:
        return None
    return PartyRef(
        public_id=user.public_id, username=user.username, full_name=user.full_name
    )


def _response(discussion: CourseDiscussion, *, reply_count: int = 0) -> DiscussionResponse:
    return DiscussionResponse(
        public_id=discussion.public_id,
        course_id=discussion.course.public_id,
        course_title=discussion.course.title if discussion.course else None,
        author=_party(discussion.author),
        title=discussion.title,
        body=discussion.body,
        is_pinned=discussion.is_pinned,
        is_locked=discussion.is_locked,
        reply_count=reply_count,
        created_at=discussion.created_at,
    )


def _reply_response(
    reply: DiscussionReply, *, discussion_id: uuid.UUID
) -> DiscussionReplyResponse:
    return DiscussionReplyResponse(
        public_id=reply.public_id,
        discussion_id=discussion_id,
        author=_party(reply.author),
        body=reply.body,
        created_at=reply.created_at,
    )


@router.get("", response_model=Page[DiscussionResponse], summary="List discussions")
async def list_discussions(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.DISCUSSION, Action.READ)))
    ],
    course_id: Annotated[uuid.UUID | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[DiscussionResponse]:
    """Scoped to courses you can reach — the same scope that decides whether
    you can open the course at all. Pinned threads sort first."""
    rows, total, counts = await DiscussionService(session).list_threads(
        params, actor=actor, course_id=course_id, query=q
    )
    items = [_response(r, reply_count=counts.get(r.id, 0)) for r in rows]
    return Page.build(items, total=total, params=params)


@router.post(
    "",
    response_model=DiscussionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a discussion",
)
async def create_discussion(
    payload: CreateDiscussionRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.DISCUSSION, Action.CREATE)))
    ],
) -> DiscussionResponse:
    return _response(await DiscussionService(session).create(payload, actor=actor))


@router.get(
    "/{discussion_id}", response_model=DiscussionResponse, summary="Get one discussion"
)
async def get_discussion(
    discussion_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.DISCUSSION, Action.READ)))
    ],
) -> DiscussionResponse:
    discussion, reply_count = await DiscussionService(session).get(discussion_id, actor=actor)
    return _response(discussion, reply_count=reply_count)


@router.patch(
    "/{discussion_id}", response_model=DiscussionResponse, summary="Edit or moderate a thread"
)
async def update_discussion(
    discussion_id: uuid.UUID,
    payload: UpdateDiscussionRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.DISCUSSION, Action.UPDATE)))
    ],
) -> DiscussionResponse:
    """Two different authorities behind one route: `title`/`body` need
    authorship, `is_pinned`/`is_locked` need to be a tutor of that course.
    Sending a moderation field without that standing is a 403 even for the
    thread's own author."""
    service = DiscussionService(session)
    discussion = await service.update(discussion_id, payload, actor=actor)
    counts = await service.discussions.reply_counts([discussion.id])
    return _response(discussion, reply_count=counts.get(discussion.id, 0))


@router.delete(
    "/{discussion_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a discussion",
)
async def delete_discussion(
    discussion_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.DISCUSSION, Action.DELETE)))
    ],
) -> Response:
    """An author can withdraw their own thread only while nobody else has
    replied — after that, removing it would delete other people's words to
    retract yours, and it takes a tutor of the course."""
    await DiscussionService(session).delete(discussion_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{discussion_id}/replies",
    response_model=Page[DiscussionReplyResponse],
    summary="List replies",
)
async def list_replies(
    discussion_id: uuid.UUID,
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.DISCUSSION, Action.READ)))
    ],
) -> Page[DiscussionReplyResponse]:
    """Paged and oldest-first. Replies are deliberately not embedded in the
    thread response: a 300-reply thread would otherwise be loaded in full on
    every row of a list that only renders a count."""
    rows, total = await DiscussionService(session).list_replies(
        discussion_id, params, actor=actor
    )
    items = [_reply_response(r, discussion_id=discussion_id) for r in rows]
    return Page.build(items, total=total, params=params)


@router.post(
    "/{discussion_id}/replies",
    response_model=DiscussionReplyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Reply to a discussion",
)
async def create_reply(
    discussion_id: uuid.UUID,
    payload: ReplyRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.DISCUSSION, Action.CREATE)))
    ],
) -> DiscussionReplyResponse:
    reply, parent_id = await DiscussionService(session).reply(
        discussion_id, payload, actor=actor
    )
    return _reply_response(reply, discussion_id=parent_id)


@replies_router.patch(
    "/{reply_id}", response_model=DiscussionReplyResponse, summary="Edit your reply"
)
async def update_reply(
    reply_id: uuid.UUID,
    payload: ReplyRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.DISCUSSION, Action.UPDATE)))
    ],
) -> DiscussionReplyResponse:
    """Authors only — not moderators. Rewriting somebody else's words in
    place, still under their name, is not moderation; a moderator removes."""
    reply, parent_id = await DiscussionService(session).update_reply(
        reply_id, payload, actor=actor
    )
    return _reply_response(reply, discussion_id=parent_id)


@replies_router.delete(
    "/{reply_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a reply"
)
async def delete_reply(
    reply_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.DISCUSSION, Action.DELETE)))
    ],
) -> Response:
    await DiscussionService(session).delete_reply(reply_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

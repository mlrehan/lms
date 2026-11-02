"""The video library (`/videos`).

Every route that leads to the video itself -- `/player`, `/open`,
`/thumbnail` -- is a redirect issued only after `VideoService` has re-checked
that this caller may see the video, and each answer is `no-store`. The
provider's address therefore appears in no listing or detail payload for a
viewer, and a link copied out of the page leads back through the check.

What this cannot do, and the response says so per provider: the player on
the other side of the redirect is the provider's own. Whether it offers a
download, and whether it plays on other sites, is set by the owner in that
provider -- see `core.video_links.provider_profile`.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Sequence

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select

from backend.api.deps import CurrentUser, require_permissions
from backend.core.errors import ValidationError
from backend.core.permissions import Action, Module, perm
from backend.core.video_links import VideoLinkError, parse_video_url, provider_label, provider_profile
from backend.db.dependencies import DBSession
from backend.models.administration import Category
from backend.models.batch import Batch
from backend.models.course import Course
from backend.models.identity.user import User
from backend.models.video import Video
from backend.schemas.base import Page, PageParams
from backend.schemas.video import (
    VideoCreateRequest,
    VideoDetail,
    VideoInspectRequest,
    VideoInspectResponse,
    VideoProviderNotes,
    VideoShareLine,
    VideoShareRequest,
    VideoShareResult,
    VideoSummary,
    VideoUpdateRequest,
)
from backend.services.resource_audience import display_name
from backend.services.video_service import VideoService

router = APIRouter(tags=["Video library"])

_READ = require_permissions(perm(Module.VIDEO, Action.READ))
_CREATE = require_permissions(perm(Module.VIDEO, Action.CREATE))
_UPDATE = require_permissions(perm(Module.VIDEO, Action.UPDATE))
_DELETE = require_permissions(perm(Module.VIDEO, Action.DELETE))
_SHARE = require_permissions(perm(Module.VIDEO, Action.PUBLISH))

#: Players that will not start unless they can see which site embeds them
#: (measured for YouTube: `no-referrer` gives "Error 153"). Everyone else gets
#: no referrer at all.
_NEEDS_ORIGIN = ("youtube",)


def _notes(provider: str) -> VideoProviderNotes:
    p = provider_profile(provider)
    return VideoProviderNotes(
        plays_in_lms=p.plays_in_lms,
        download=p.download,
        domain_restriction=p.domain_restriction,
        needs_provider_sign_in=p.needs_provider_sign_in,
    )


def _plays_in_lms(row: Video) -> bool:
    try:
        link = parse_video_url(row.source_url)
    except VideoLinkError:
        return False
    return link.is_embeddable or link.is_direct_file


def _has_thumbnail(row: Video) -> bool:
    try:
        return parse_video_url(row.source_url).thumbnail_url is not None
    except VideoLinkError:
        return False


async def _summaries(
    session, service: VideoService, rows: Sequence[Video], actor: User  # noqa: ANN001
) -> list[VideoSummary]:
    """Rows to responses, with their labels fetched in one query per kind."""
    course_ids = {r.course_id for r in rows if r.course_id}
    batch_ids = {r.batch_id for r in rows if r.batch_id}
    category_ids = {r.category_id for r in rows if r.category_id}
    owner_ids = {r.owner_id for r in rows if r.owner_id}
    courses = {
        c.id: c for c in (await session.execute(
            select(Course.id, Course.public_id, Course.title).where(Course.id.in_(course_ids))
        )).all()
    } if course_ids else {}
    batches = {
        b.id: b for b in (await session.execute(
            select(Batch.id, Batch.public_id, Batch.batch_code).where(Batch.id.in_(batch_ids))
        )).all()
    } if batch_ids else {}
    categories = {
        c.id: c for c in (await session.execute(
            select(Category.id, Category.public_id, Category.name).where(Category.id.in_(category_ids))
        )).all()
    } if category_ids else {}
    owners = {
        u.id: u for u in (await session.execute(select(User).where(User.id.in_(owner_ids)))).scalars().unique()
    } if owner_ids else {}
    manageable = [r.id for r in rows if service.may_manage(r, actor)]
    counts = await service.share_counts(manageable)

    out = []
    for r in rows:
        course, batch, category = courses.get(r.course_id), batches.get(r.batch_id), categories.get(r.category_id)
        owner = owners.get(r.owner_id)
        can_manage = service.may_manage(r, actor)
        out.append(VideoSummary(
            public_id=r.public_id,
            title=r.title,
            description=r.description,
            provider=r.provider,
            provider_label=provider_label(r.provider),
            plays_in_lms=_plays_in_lms(r),
            thumbnail_url=f"/videos/{r.public_id}/thumbnail" if _has_thumbnail(r) else None,
            course_id=course.public_id if course else None,
            course_title=course.title if course else None,
            batch_id=batch.public_id if batch else None,
            batch_code=batch.batch_code if batch else None,
            category_id=category.public_id if category else None,
            category_name=category.name if category else None,
            # A name, never a login name: the library is read by students.
            owner_name=display_name(owner) if owner else None,
            is_mine=r.owner_id == actor.id,
            can_manage=can_manage,
            share_count=counts.get(r.id, 0) if can_manage else None,
            created_at=r.created_at,
        ))
    return out


async def _detail(session, service: VideoService, row: Video, actor: User) -> VideoDetail:  # noqa: ANN001
    summary = (await _summaries(session, service, [row], actor))[0]
    shares = None
    if summary.can_manage:
        shares = [
            VideoShareLine(
                id=share.id,
                kind="PERSON" if share.user_id else "BATCH",
                label=display_name(user) if user else (batch.batch_code if batch else "Removed"),
                created_at=share.created_at,
            )
            for share, user, batch in await service.shares(row)
        ]
    return VideoDetail(
        **summary.model_dump(),
        player_url=f"/videos/{row.public_id}/player" if summary.plays_in_lms else None,
        open_url=f"/videos/{row.public_id}/open",
        source_url=row.source_url if summary.can_manage else None,
        notes=_notes(row.provider),
        shares=shares,
    )


def _redirect(target: str, *, provider: str) -> Response:
    return Response(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={
            "Location": target,
            # One admission, for this caller, now; no cache may repeat it.
            "Cache-Control": "private, no-store",
            "Referrer-Policy": "strict-origin-when-cross-origin" if provider in _NEEDS_ORIGIN else "no-referrer",
        },
    )


# -- routes ---------------------------------------------------------------------


@router.get("/videos", response_model=Page[VideoSummary], summary="Videos you may watch")
async def list_videos(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[CurrentUser, Depends(_READ)],
    q: Annotated[str | None, Query(max_length=100)] = None,
    provider: Annotated[str | None, Query(max_length=40)] = None,
    course_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    sharing: Annotated[str, Query(description="all, mine or shared_with_me")] = "all",
    sort: Annotated[str, Query(description="newest, oldest or title")] = "newest",
) -> Page[VideoSummary]:
    service = VideoService(session)
    rows, total = await service.list(
        params, actor=actor, query=q, provider=provider, course_id=course_id,
        batch_id=batch_id, category_id=category_id, sharing=sharing, sort=sort,
    )
    return Page.build(await _summaries(session, service, rows, actor), total=total, params=params)


@router.post("/videos/inspect", response_model=VideoInspectResponse, summary="Recognise a pasted link")
async def inspect_video_link(
    payload: VideoInspectRequest,
    actor: Annotated[CurrentUser, Depends(_CREATE)],
) -> VideoInspectResponse:
    """Parses only -- no request is made to the address (it would be an SSRF)."""
    try:
        link = parse_video_url(payload.url)
    except VideoLinkError as exc:
        raise ValidationError(str(exc)) from exc
    return VideoInspectResponse(
        provider=link.provider, provider_label=link.provider_label, notes=_notes(link.provider)
    )


@router.post("/videos", response_model=VideoDetail, status_code=status.HTTP_201_CREATED, summary="Add a video")
async def create_video(
    payload: VideoCreateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_CREATE)],
) -> VideoDetail:
    service = VideoService(session)
    row = await service.create(actor=actor, **payload.model_dump())
    return await _detail(session, service, row, actor)


@router.get("/videos/{video_id}", response_model=VideoDetail, summary="One video")
async def get_video(
    video_id: uuid.UUID, session: DBSession, actor: Annotated[CurrentUser, Depends(_READ)]
) -> VideoDetail:
    service = VideoService(session)
    return await _detail(session, service, await service.get(video_id, actor=actor), actor)


@router.patch("/videos/{video_id}", response_model=VideoDetail, summary="Edit your video")
async def update_video(
    video_id: uuid.UUID,
    payload: VideoUpdateRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_UPDATE)],
) -> VideoDetail:
    service = VideoService(session)
    row = await service.update(video_id, actor=actor, **payload.model_dump(exclude_unset=True))
    return await _detail(session, service, row, actor)


@router.delete("/videos/{video_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete your video")
async def delete_video(
    video_id: uuid.UUID, session: DBSession, actor: Annotated[CurrentUser, Depends(_DELETE)]
) -> Response:
    await VideoService(session).delete(video_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/videos/{video_id}/shares", response_model=VideoShareResult, summary="Share with people or batches")
async def share_video(
    video_id: uuid.UUID,
    payload: VideoShareRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_SHARE)],
) -> VideoShareResult:
    """A Super Admin may share with anybody; a tutor with colleagues, the students
    of batches they teach and those students' guardians, and with those batches.
    One recipient outside that refuses the whole request."""
    people, batches = await VideoService(session).share(
        video_id, actor=actor, user_ids=payload.user_ids, batch_ids=payload.batch_ids
    )
    return VideoShareResult(people_added=people, batches_added=batches)


@router.delete(
    "/videos/{video_id}/shares/{share_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Stop sharing"
)
async def unshare_video(
    video_id: uuid.UUID,
    share_id: int,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(_SHARE)],
) -> Response:
    await VideoService(session).unshare(video_id, share_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/videos/{video_id}/player",
    response_class=Response,
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    summary="The in-LMS player (re-checks access, then hands over to the provider)",
)
async def play_video(
    video_id: uuid.UUID, session: DBSession, actor: Annotated[CurrentUser, Depends(_READ)]
) -> Response:
    row, target = await VideoService(session).player_target(video_id, actor=actor, embed=True)
    return _redirect(target, provider=row.provider)


@router.get(
    "/videos/{video_id}/open",
    response_class=Response,
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    summary="Open the video on the provider's site (re-checks access)",
)
async def open_video(
    video_id: uuid.UUID, session: DBSession, actor: Annotated[CurrentUser, Depends(_READ)]
) -> Response:
    row, target = await VideoService(session).player_target(video_id, actor=actor, embed=False)
    return _redirect(target, provider=row.provider)


@router.get(
    "/videos/{video_id}/thumbnail",
    response_class=Response,
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    summary="The video's still image, where the provider publishes one",
)
async def video_thumbnail(
    video_id: uuid.UUID, session: DBSession, actor: Annotated[CurrentUser, Depends(_READ)]
) -> Response:
    target = await VideoService(session).thumbnail_target(video_id, actor=actor)
    return Response(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Location": target, "Cache-Control": "private, max-age=300", "Referrer-Policy": "no-referrer"},
    )

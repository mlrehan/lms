"""The video library: who may see, share and watch a video.

Three rules, each enforced here rather than by what the console shows:

* **Seeing.** An unrestricted caller (Super Admin, Administrator) sees every
  video. Anybody else sees a video they own, one shared with them by name, or
  one shared with a batch they study in or teach. Nothing else -- in the
  listing, on a direct link, or on the player route.
* **Sharing.** A Super Admin may share with anybody. A tutor may share only
  with the audience `ResourceShareAudience` already defines for files --
  colleagues, the students of the batches they teach, and those students'
  guardians -- and only with batches they teach. One refusal refuses the
  whole request, so a share is never half-made.
* **Watching.** `player_target` re-runs the seeing rule on every open and
  records the view; the provider URL never appears in any response to a
  viewer who cannot edit the video.

Only the owner (or an unrestricted caller) edits, deletes or shares a video.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Sequence

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import AuthorizationError, NotFoundError, ValidationError
from backend.core.video_links import VideoLinkError, parse_video_url
from backend.models.administration import Category
from backend.models.batch import Batch
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.user import User
from backend.models.video import Video, VideoShare
from backend.repositories.enrollment import ACTIVE_STATUSES
from backend.schemas.base import PageParams
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.resource_audience import ResourceShareAudience
from backend.services.scope import ScopeResolver

SORTS = {"newest", "oldest", "title"}
SHARING = {"all", "mine", "shared_with_me"}


@dataclass(frozen=True)
class VideoReach:
    """What a caller can reach, resolved once per request."""

    unrestricted: bool
    user_id: int
    #: Batches whose shared videos this caller receives: studied in or taught.
    batch_ids: frozenset[int]
    #: Batches this caller may share *to*: taught (everything, if unrestricted).
    teach_batch_ids: frozenset[int]


class VideoService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.scopes = ScopeResolver(session)
        self.audience = ResourceShareAudience(session)

    # -- reach ---------------------------------------------------------------

    async def reach(self, actor: User) -> VideoReach:
        if ScopeResolver.is_unrestricted(actor):
            return VideoReach(True, actor.id, frozenset(), frozenset())
        taught = set((await self.scopes.enrollment_visibility(actor)).taught_batch_ids)
        studied = set(
            (
                await self.session.execute(
                    select(Enrollments.batch_id).where(
                        Enrollments.student_id == actor.id,
                        Enrollments.status.in_(ACTIVE_STATUSES),
                    )
                )
            )
            .scalars()
            .all()
        )
        return VideoReach(False, actor.id, frozenset(taught | studied), frozenset(taught))

    @staticmethod
    def _visible(reach: VideoReach) -> Any:
        """SQL: the videos `reach` admits (live ones only)."""
        live = Video.deleted_at.is_(None)
        if reach.unrestricted:
            return live
        shared_to_me = exists().where(
            VideoShare.video_id == Video.id,
            or_(
                VideoShare.user_id == reach.user_id,
                VideoShare.batch_id.in_(reach.batch_ids) if reach.batch_ids else False,
            ),
        )
        return and_(live, or_(Video.owner_id == reach.user_id, shared_to_me))

    async def get(self, public_id: uuid.UUID, *, actor: User) -> Video:
        """One video the caller may see. Out of reach and nonexistent are the same 404."""
        reach = await self.reach(actor)
        row = (
            await self.session.execute(
                select(Video).where(Video.public_id == public_id, self._visible(reach))
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Video not found.")
        return row

    @staticmethod
    def may_manage(row: Video, actor: User) -> bool:
        return ScopeResolver.is_unrestricted(actor) or (
            row.owner_id is not None and row.owner_id == actor.id
        )

    def _assert_manages(self, row: Video, actor: User) -> None:
        if not self.may_manage(row, actor):
            raise AuthorizationError("Only the person who added this video can change it.")

    # -- listing -------------------------------------------------------------

    async def list(
        self,
        params: PageParams,
        *,
        actor: User,
        query: str | None = None,
        provider: str | None = None,
        course_id: uuid.UUID | None = None,
        batch_id: uuid.UUID | None = None,
        category_id: uuid.UUID | None = None,
        sharing: str = "all",
        sort: str = "newest",
    ) -> tuple[Sequence[Video], int]:
        if sort not in SORTS:
            raise ValidationError(f"sort must be one of {sorted(SORTS)}.")
        if sharing not in SHARING:
            raise ValidationError(f"sharing must be one of {sorted(SHARING)}.")
        reach = await self.reach(actor)
        stmt = select(Video).where(self._visible(reach))

        if query and query.strip():
            needle = f"%{query.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Video.title).like(needle),
                    func.lower(func.coalesce(Video.description, "")).like(needle),
                )
            )
        if provider:
            stmt = stmt.where(Video.provider == provider)
        if course_id:
            stmt = stmt.where(Video.course_id == select(Course.id).where(Course.public_id == course_id).scalar_subquery())
        if batch_id:
            stmt = stmt.where(Video.batch_id == select(Batch.id).where(Batch.public_id == batch_id).scalar_subquery())
        if category_id:
            stmt = stmt.where(
                Video.category_id == select(Category.id).where(Category.public_id == category_id).scalar_subquery()
            )
        if sharing == "mine":
            stmt = stmt.where(Video.owner_id == actor.id)
        elif sharing == "shared_with_me":
            stmt = stmt.where(or_(Video.owner_id.is_(None), Video.owner_id != actor.id))

        order = {
            "newest": (Video.created_at.desc(), Video.id.desc()),
            "oldest": (Video.created_at.asc(), Video.id.asc()),
            "title": (func.lower(Video.title).asc(), Video.id.asc()),
        }[sort]
        stmt = stmt.order_by(*order)

        total = (
            await self.session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
        ).scalar_one()
        rows = (
            await self.session.execute(stmt.limit(params.limit).offset(params.offset))
        ).scalars().all()
        return rows, int(total)

    # -- writing -------------------------------------------------------------

    async def _context(
        self,
        reach: VideoReach,
        actor: User,
        *,
        course_id: uuid.UUID | None,
        batch_id: uuid.UUID | None,
        category_id: uuid.UUID | None,
    ) -> tuple[int | None, int | None, int | None]:
        """Resolve the optional course/batch/category, within the caller's teaching."""
        course_pk = batch_pk = category_pk = None
        if batch_id is not None:
            batch = (
                await self.session.execute(select(Batch).where(Batch.public_id == batch_id))
            ).scalar_one_or_none()
            if batch is None or (not reach.unrestricted and batch.id not in reach.teach_batch_ids):
                raise NotFoundError("Batch not found.")
            batch_pk, course_pk = batch.id, batch.course_id
        if course_id is not None:
            course = (
                await self.session.execute(select(Course).where(Course.public_id == course_id))
            ).scalar_one_or_none()
            if course is None:
                raise NotFoundError("Course not found.")
            if not reach.unrestricted and course.id not in await self.scopes.teaching_course_ids(actor):
                raise AuthorizationError("You can only file a video under a course you teach.")
            if course_pk is not None and course_pk != course.id:
                raise ValidationError("That batch belongs to a different course.")
            course_pk = course.id
        if category_id is not None:
            category = (
                await self.session.execute(select(Category).where(Category.public_id == category_id))
            ).scalar_one_or_none()
            if category is None:
                raise NotFoundError("Category not found.")
            category_pk = category.id
        return course_pk, batch_pk, category_pk

    async def create(
        self,
        *,
        actor: User,
        title: str,
        url: str,
        description: str | None = None,
        course_id: uuid.UUID | None = None,
        batch_id: uuid.UUID | None = None,
        category_id: uuid.UUID | None = None,
    ) -> Video:
        try:
            link = parse_video_url(url)
        except VideoLinkError as exc:
            raise ValidationError(str(exc)) from exc
        reach = await self.reach(actor)
        course_pk, batch_pk, category_pk = await self._context(
            reach, actor, course_id=course_id, batch_id=batch_id, category_id=category_id
        )
        row = Video(
            title=title.strip(),
            description=(description or "").strip() or None,
            provider=link.provider,
            source_url=link.url,
            course_id=course_pk,
            batch_id=batch_pk,
            category_id=category_pk,
            owner_id=actor.id,
            created_at=datetime.now(UTC),
        )
        self.session.add(row)
        await self.session.flush()
        audit_service.record(
            self.session, action=AuditAction.CREATE, actor_user_id=actor.id,
            actor_email=actor.email, entity_type="video", entity_id=row.id,
            details={"title": row.title, "provider": row.provider},
        )
        return row

    async def update(self, public_id: uuid.UUID, *, actor: User, **changes: Any) -> Video:
        row = await self.get(public_id, actor=actor)
        self._assert_manages(row, actor)
        if "url" in changes and changes["url"] is not None:
            try:
                link = parse_video_url(changes.pop("url"))
            except VideoLinkError as exc:
                raise ValidationError(str(exc)) from exc
            row.provider, row.source_url = link.provider, link.url
        changes.pop("url", None)
        if any(k in changes for k in ("course_id", "batch_id", "category_id")):
            reach = await self.reach(actor)
            course_pk, batch_pk, category_pk = await self._context(
                reach, actor,
                course_id=changes.pop("course_id", None),
                batch_id=changes.pop("batch_id", None),
                category_id=changes.pop("category_id", None),
            )
            row.course_id, row.batch_id, row.category_id = course_pk, batch_pk, category_pk
        if changes.get("title") is not None:
            row.title = changes["title"].strip()
        if "description" in changes:
            row.description = (changes["description"] or "").strip() or None
        row.updated_at = datetime.now(UTC)
        audit_service.record(
            self.session, action=AuditAction.UPDATE, actor_user_id=actor.id,
            actor_email=actor.email, entity_type="video", entity_id=row.id,
            details={"title": row.title},
        )
        return row

    async def delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        """Withdraw: the video leaves every list and its player stops at once."""
        row = await self.get(public_id, actor=actor)
        self._assert_manages(row, actor)
        row.deleted_at = datetime.now(UTC)
        audit_service.record(
            self.session, action=AuditAction.DELETE, actor_user_id=actor.id,
            actor_email=actor.email, entity_type="video", entity_id=row.id,
            details={"title": row.title, "withdrawn": True},
        )

    # -- sharing -------------------------------------------------------------

    async def share(
        self,
        public_id: uuid.UUID,
        *,
        actor: User,
        user_ids: Sequence[uuid.UUID] = (),
        batch_ids: Sequence[uuid.UUID] = (),
    ) -> tuple[int, int]:
        """Add recipients; returns (people added, batches added). All or nothing."""
        row = await self.get(public_id, actor=actor)
        self._assert_manages(row, actor)
        if not user_ids and not batch_ids:
            raise ValidationError("Choose at least one person or batch to share with.")

        # People: the same audience rule as sharing a file, and the same single
        # refusal whatever the reason, so the endpoint is not a directory probe.
        people = await self.audience.resolve(actor, list(user_ids))

        reach = await self.reach(actor)
        batches: list[Batch] = []
        if batch_ids:
            batches = list(
                (await self.session.execute(select(Batch).where(Batch.public_id.in_(list(batch_ids)))))
                .scalars()
                .all()
            )
            if len(batches) != len(set(batch_ids)) or (
                not reach.unrestricted and any(b.id not in reach.teach_batch_ids for b in batches)
            ):
                raise AuthorizationError("You can share only with batches you teach.")

        existing_users = set(
            (await self.session.execute(
                select(VideoShare.user_id).where(VideoShare.video_id == row.id, VideoShare.user_id.is_not(None))
            )).scalars().all()
        )
        existing_batches = set(
            (await self.session.execute(
                select(VideoShare.batch_id).where(VideoShare.video_id == row.id, VideoShare.batch_id.is_not(None))
            )).scalars().all()
        )
        now = datetime.now(UTC)
        added_people = [p for p in people if p.id not in existing_users]
        added_batches = [b for b in batches if b.id not in existing_batches]
        for person in added_people:
            self.session.add(VideoShare(video_id=row.id, user_id=person.id, shared_by=actor.id, created_at=now))
        for batch in added_batches:
            self.session.add(VideoShare(video_id=row.id, batch_id=batch.id, shared_by=actor.id, created_at=now))
        await self.session.flush()
        audit_service.record(
            self.session, action=AuditAction.PERMISSION_CHANGE, actor_user_id=actor.id,
            actor_email=actor.email, entity_type="video", entity_id=row.id,
            # Recipients by public id: a share must not copy an address into the trail.
            details={"people": [str(p.public_id) for p in added_people],
                     "batches": [b.batch_code for b in added_batches]},
        )
        return len(added_people), len(added_batches)

    async def unshare(self, public_id: uuid.UUID, share_id: int, *, actor: User) -> None:
        row = await self.get(public_id, actor=actor)
        self._assert_manages(row, actor)
        share = (
            await self.session.execute(
                select(VideoShare).where(VideoShare.id == share_id, VideoShare.video_id == row.id)
            )
        ).scalar_one_or_none()
        if share is None:
            raise NotFoundError("That share does not exist.")
        await self.session.delete(share)
        audit_service.record(
            self.session, action=AuditAction.UPDATE, actor_user_id=actor.id,
            actor_email=actor.email, entity_type="video", entity_id=row.id,
            details={"unshared": share_id},
        )

    async def shares(self, row: Video) -> list[tuple[VideoShare, User | None, Batch | None]]:
        rows = (
            await self.session.execute(
                select(VideoShare, User, Batch)
                .outerjoin(User, User.id == VideoShare.user_id)
                .outerjoin(Batch, Batch.id == VideoShare.batch_id)
                .where(VideoShare.video_id == row.id)
                .order_by(VideoShare.created_at)
            )
        ).all()
        return [(s, u, b) for s, u, b in rows]

    async def share_counts(self, video_ids: Sequence[int]) -> dict[int, int]:
        if not video_ids:
            return {}
        rows = await self.session.execute(
            select(VideoShare.video_id, func.count())
            .where(VideoShare.video_id.in_(list(video_ids)))
            .group_by(VideoShare.video_id)
        )
        return {vid: int(n) for vid, n in rows.all()}

    # -- watching ------------------------------------------------------------

    async def player_target(self, public_id: uuid.UUID, *, actor: User, embed: bool) -> tuple[Video, str]:
        """Re-check access, record the view, and return where to send the browser.

        `embed=True` is the in-LMS player; it refuses a provider that cannot be
        framed rather than handing back a page that will not render.
        """
        row = await self.get(public_id, actor=actor)
        try:
            link = parse_video_url(row.source_url)
        except VideoLinkError as exc:  # stored before a rule tightened
            raise NotFoundError("This video's link can no longer be played.") from exc
        if embed:
            target = link.embed_url if link.is_embeddable else (link.url if link.is_direct_file else None)
            if not target:
                raise ValidationError(
                    "This provider cannot play inside the LMS. Use 'Open on provider' instead."
                )
        else:
            target = link.url
        audit_service.record(
            self.session, action=AuditAction.VIDEO_VIEW, actor_user_id=actor.id,
            actor_email=actor.email, entity_type="video", entity_id=row.id,
            details={"provider": row.provider, "in_lms": embed},
        )
        return row, target

    async def thumbnail_target(self, public_id: uuid.UUID, *, actor: User) -> str:
        row = await self.get(public_id, actor=actor)
        try:
            thumb = parse_video_url(row.source_url).thumbnail_url
        except VideoLinkError:
            thumb = None
        if not thumb:
            raise NotFoundError("No thumbnail for this video.")
        return thumb

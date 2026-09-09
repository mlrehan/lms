"""Announcements (spec §16).

Two rules carry this module.

**Nobody broadcasts wider than they teach.** `announcement.create` is held by
Administrators and Tutors alike, but the two mean very different things: an
Administrator addressing the institution is running the institution, whereas
a Tutor addressing the institution is a tutor who has found the platform's
public address system. So a caller without `institution.view_all` must target
a course or a batch, and it must be one they actually teach. An
institution-wide notice -- all three targeting columns NULL -- is available
only to unrestricted callers.

**The reader's feed is filtered, and filtered in the direction that fails
closed.** See `repositories/announcement.py` for the audience predicate; the
service's job is to decide *which* scopes to hand it and never to let
`audience_filter=False` reach a caller who has not earned it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import AuthorizationError, NotFoundError, ValidationError
from backend.models.batch import Batch
from backend.models.course import Course
from backend.models.identity.user import User
from backend.models.notification import Announcement
from backend.repositories.announcement import AnnouncementRepository
from backend.schemas.announcement import (
    CreateAnnouncementRequest,
    UpdateAnnouncementRequest,
)
from backend.schemas.base import PageParams
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.scope import ScopeResolver


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AnnouncementService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.announcements = AnnouncementRepository(session)
        self.scopes = ScopeResolver(session)

    # -- reads ---------------------------------------------------------------

    async def list_feed(
        self,
        params: PageParams,
        *,
        actor: User,
        mine: bool = False,
        course_id: uuid.UUID | None = None,
        batch_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[Announcement], int]:
        unrestricted = ScopeResolver.is_unrestricted(actor)

        course_pk = await self._resolve_course(course_id) if course_id else None
        batch_pk = await self._resolve_batch(batch_id) if batch_id else None

        if mine:
            # Your own drafts and expired notices, so an author can see what
            # they scheduled before it goes live and confirm what has lapsed.
            return await self.announcements.search(
                params,
                now=_now(),
                audience_filter=False,
                author_id=actor.id,
                course_id=course_pk,
                batch_id=batch_pk,
                include_expired=True,
                include_scheduled=True,
            )

        return await self.announcements.search(
            params,
            now=_now(),
            audience_filter=not unrestricted,
            course_scope=None if unrestricted else await self.scopes.visible_course_ids(actor),
            batch_scope=None if unrestricted else await self.scopes.visible_batch_ids(actor),
            role_names=self._role_names(actor),
            course_id=course_pk,
            batch_id=batch_pk,
            # An administrator listing announcements is administering them and
            # needs to see the whole set; a reader is being shown a feed.
            include_expired=unrestricted,
            include_scheduled=unrestricted,
        )

    async def get(self, public_id: uuid.UUID, *, actor: User) -> Announcement:
        announcement = await self.announcements.get_by_public_id_full(public_id)
        if announcement is None:
            raise NotFoundError("Announcement not found.")

        if not ScopeResolver.is_unrestricted(actor):
            if announcement.created_by != actor.id and not await self._reaches(actor, announcement):
                # 404, not 403: an announcement addressed to another course is
                # not something to confirm the existence of.
                raise NotFoundError("Announcement not found.")
        return announcement

    # -- writes --------------------------------------------------------------

    async def create(
        self, payload: CreateAnnouncementRequest, *, actor: User
    ) -> Announcement:
        unrestricted = ScopeResolver.is_unrestricted(actor)

        course_pk = await self._resolve_course(payload.course_id) if payload.course_id else None
        batch_pk = await self._resolve_batch(payload.batch_id) if payload.batch_id else None

        if course_pk is not None and batch_pk is not None:
            await self._assert_batch_in_course(batch_pk, course_pk)

        if not unrestricted:
            await self._assert_may_target(actor, course_pk=course_pk, batch_pk=batch_pk)

        announcement = Announcement(
            title=payload.title,
            content=payload.content,
            created_by=actor.id,
            course_id=course_pk,
            batch_id=batch_pk,
            role_scope=payload.role_scope,
            start_at=payload.start_at or _now(),
            end_at=payload.end_at,
            pinned=payload.pinned,
        )
        await self.announcements.add_and_flush(announcement)

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="announcement",
            entity_id=announcement.id,
            details={
                "title": payload.title,
                "course_id": str(payload.course_id) if payload.course_id else None,
                "batch_id": str(payload.batch_id) if payload.batch_id else None,
                "role_scope": payload.role_scope.value if payload.role_scope else None,
            },
        )
        return await self.announcements.get_by_public_id_full(announcement.public_id)  # type: ignore[return-value]

    async def update(
        self, public_id: uuid.UUID, payload: UpdateAnnouncementRequest, *, actor: User
    ) -> Announcement:
        announcement = await self._load_for_write(public_id, actor=actor)
        changes = payload.model_dump(exclude_unset=True)

        start_at = changes.get("start_at", announcement.start_at)
        end_at = changes.get("end_at", announcement.end_at)
        if start_at and end_at and end_at <= start_at:
            # Re-checked against the stored row, not just within the payload:
            # moving only `start_at` past an untouched `end_at` produces a
            # window that can never be live, and the schema validator cannot
            # see the half it was not sent.
            raise ValidationError("end_at must be after start_at.")

        for field, value in changes.items():
            setattr(announcement, field, value)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="announcement",
            entity_id=announcement.id,
            details={"fields": sorted(changes)},
        )
        return announcement

    async def delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        announcement = await self._load_for_write(public_id, actor=actor)
        entity_id = announcement.id
        title = announcement.title

        # A hard delete. An announcement is a notice, not a record: once
        # withdrawn there is nothing about it worth keeping queryable, and the
        # audit row below preserves that it existed and who removed it.
        await self.session.delete(announcement)

        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="announcement",
            entity_id=entity_id,
            details={"title": title},
        )

    # -- policy --------------------------------------------------------------

    async def _load_for_write(self, public_id: uuid.UUID, *, actor: User) -> Announcement:
        announcement = await self.announcements.get_by_public_id_full(public_id)
        if announcement is None:
            raise NotFoundError("Announcement not found.")

        if ScopeResolver.is_unrestricted(actor):
            return announcement

        if announcement.created_by != actor.id:
            # Already visible to them if it reaches them, so 403 rather than
            # 404 here: it exists, they simply do not own it.
            raise AuthorizationError("You can only edit announcements you posted.")
        return announcement

    async def _assert_may_target(
        self, actor: User, *, course_pk: int | None, batch_pk: int | None
    ) -> None:
        if course_pk is None and batch_pk is None:
            raise AuthorizationError(
                "Only an administrator can post an institution-wide announcement. "
                "Target a course or batch you teach.",
            )

        work = await self.scopes.work_visibility(actor)
        enrollment = await self.scopes.enrollment_visibility(actor)

        if batch_pk is not None and batch_pk not in enrollment.taught_batch_ids:
            raise AuthorizationError("You do not teach this batch.")
        if course_pk is not None and course_pk not in work.taught_course_ids:
            raise AuthorizationError("You do not teach this course.")

    async def _reaches(self, actor: User, announcement: Announcement) -> bool:
        """Whether the announcement's audience includes this reader.

        The same predicate the feed query applies, evaluated for one row --
        used by `get`, which fetches by id and therefore bypasses the feed's
        WHERE clause entirely.
        """
        if announcement.role_scope is not None:
            if announcement.role_scope.value not in self._role_names(actor):
                return False

        if announcement.course_id is not None:
            courses = await self.scopes.visible_course_ids(actor)
            if not courses.allows(announcement.course_id):
                return False

        if announcement.batch_id is not None:
            batches = await self.scopes.visible_batch_ids(actor)
            if not batches.allows(announcement.batch_id):
                return False

        now = _now()
        if announcement.start_at and announcement.start_at > now:
            return False
        if announcement.end_at and announcement.end_at <= now:
            return False
        return True

    @staticmethod
    def _role_names(actor: User) -> set[str]:
        return {(r.name or "").upper() for r in (actor.roles or [])}

    # -- helpers -------------------------------------------------------------

    async def _resolve_course(self, public_id: uuid.UUID) -> int:
        stmt = select(Course.id).where(Course.public_id == public_id)
        course_id = (await self.session.execute(stmt)).scalar_one_or_none()
        if course_id is None:
            raise NotFoundError("Course not found.")
        return int(course_id)

    async def _resolve_batch(self, public_id: uuid.UUID) -> int:
        stmt = select(Batch.id).where(Batch.public_id == public_id)
        batch_id = (await self.session.execute(stmt)).scalar_one_or_none()
        if batch_id is None:
            raise NotFoundError("Batch not found.")
        return int(batch_id)

    async def _assert_batch_in_course(self, batch_pk: int, course_pk: int) -> None:
        stmt = select(Batch.course_id).where(Batch.id == batch_pk)
        owner = (await self.session.execute(stmt)).scalar_one_or_none()
        if owner != course_pk:
            raise ValidationError("That batch does not belong to that course.")

"""Course discussions (spec §16).

A discussion is public *within its course* and invisible outside it, so every
read goes through `visible_course_ids` -- the same scope that decides whether
you can open the course at all. Nothing here is reachable by course id alone.

**Moderation is not a permission, it is a relationship.** `discussion.update`
says a caller may edit discussion content; it cannot say whose. Editing your
own words and locking a thread other people are using are different acts with
different owners, so the service splits them: authorship governs title/body,
and being a tutor *of that course* (or unrestricted) governs pinning,
locking, and removing somebody else's post. Encoding that as a second
permission name would have made "moderator" a global property, and a tutor of
Mathematics is not a moderator of the History forum.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from backend.models.course import Course
from backend.models.identity.user import User
from backend.models.messaging import CourseDiscussion, DiscussionReply
from backend.repositories.discussion import (
    DiscussionReplyRepository,
    DiscussionRepository,
)
from backend.schemas.base import PageParams
from backend.schemas.discussion import (
    CreateDiscussionRequest,
    ReplyRequest,
    UpdateDiscussionRequest,
)
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.scope import ScopeResolver

_MODERATION_FIELDS = {"is_pinned", "is_locked"}


class DiscussionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.discussions = DiscussionRepository(session)
        self.replies = DiscussionReplyRepository(session)
        self.scopes = ScopeResolver(session)

    # -- reads ---------------------------------------------------------------

    async def list_threads(
        self,
        params: PageParams,
        *,
        actor: User,
        course_id: uuid.UUID | None = None,
        query: str | None = None,
    ) -> tuple[Sequence[CourseDiscussion], int, dict[int, int]]:
        course_pk = await self._resolve_course(course_id) if course_id else None
        rows, total = await self.discussions.search(
            params,
            course_scope=await self.scopes.visible_course_ids(actor),
            course_id=course_pk,
            query=query,
        )
        counts = await self.discussions.reply_counts([r.id for r in rows])
        return rows, total, counts

    async def get(self, public_id: uuid.UUID, *, actor: User) -> tuple[CourseDiscussion, int]:
        discussion = await self.discussions.get_by_public_id_full(public_id)
        if discussion is None:
            raise NotFoundError("Discussion not found.")
        await self._assert_visible(actor, discussion.course_id)
        counts = await self.discussions.reply_counts([discussion.id])
        return discussion, counts.get(discussion.id, 0)

    async def list_replies(
        self, public_id: uuid.UUID, params: PageParams, *, actor: User
    ) -> tuple[Sequence[DiscussionReply], int]:
        discussion = await self.discussions.get_by_public_id_full(public_id)
        if discussion is None:
            raise NotFoundError("Discussion not found.")
        await self._assert_visible(actor, discussion.course_id)
        return await self.replies.for_discussion(params, discussion_id=discussion.id)

    # -- thread writes -------------------------------------------------------

    async def create(
        self, payload: CreateDiscussionRequest, *, actor: User
    ) -> CourseDiscussion:
        course_pk = await self._resolve_course(payload.course_id)
        await self._assert_visible(actor, course_pk)

        discussion = CourseDiscussion(
            course_id=course_pk,
            created_by=actor.id,
            title=payload.title,
            body=payload.body,
            is_pinned=False,
            is_locked=False,
            # Initialised before `add`. A newly-constructed instance has its
            # collections unloaded, and the flush cascade touches them --
            # which under asyncio surfaces as `MissingGreenlet`, not as
            # anything that names the real cause.
            replies=[],
        )
        await self.discussions.add_and_flush(discussion)

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="course_discussion",
            entity_id=discussion.id,
            details={"course_id": str(payload.course_id), "title": payload.title},
        )
        return await self.discussions.get_by_public_id_full(discussion.public_id)  # type: ignore[return-value]

    async def update(
        self, public_id: uuid.UUID, payload: UpdateDiscussionRequest, *, actor: User
    ) -> CourseDiscussion:
        discussion = await self.discussions.get_by_public_id_full(public_id)
        if discussion is None:
            raise NotFoundError("Discussion not found.")
        await self._assert_visible(actor, discussion.course_id)

        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            return discussion

        moderating = _MODERATION_FIELDS.intersection(changes)
        authoring = set(changes) - _MODERATION_FIELDS
        is_moderator = await self._is_moderator(actor, discussion.course_id)

        if moderating and not is_moderator:
            raise AuthorizationError(
                "Only a tutor of this course can pin or lock a discussion."
            )
        if authoring and discussion.created_by != actor.id and not is_moderator:
            raise AuthorizationError("You can only edit a discussion you started.")

        for field, value in changes.items():
            setattr(discussion, field, value)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="course_discussion",
            entity_id=discussion.id,
            details={"fields": sorted(changes)},
        )
        return discussion

    async def delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        discussion = await self.discussions.get_by_public_id_full(public_id)
        if discussion is None:
            raise NotFoundError("Discussion not found.")
        await self._assert_visible(actor, discussion.course_id)

        is_moderator = await self._is_moderator(actor, discussion.course_id)
        if not is_moderator:
            if discussion.created_by != actor.id:
                raise AuthorizationError("You can only delete a discussion you started.")
            if await self.discussions.has_replies_by_others(
                discussion.id, author_id=actor.id
            ):
                # Deleting the thread cascades its replies away. Once other
                # people have written in it, that is deleting their words to
                # withdraw yours -- a moderator's call, not the author's.
                raise ConflictError(
                    "Others have replied to this discussion; ask a tutor to remove it."
                )

        entity_id = discussion.id
        title = discussion.title
        await self.session.delete(discussion)

        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="course_discussion",
            entity_id=entity_id,
            details={"title": title},
        )

    # -- reply writes --------------------------------------------------------

    async def reply(
        self, public_id: uuid.UUID, payload: ReplyRequest, *, actor: User
    ) -> tuple[DiscussionReply, uuid.UUID]:
        discussion = await self.discussions.get_by_public_id_full(public_id)
        if discussion is None:
            raise NotFoundError("Discussion not found.")
        await self._assert_visible(actor, discussion.course_id)

        if discussion.is_locked and not await self._is_moderator(actor, discussion.course_id):
            raise ValidationError("This discussion is locked and accepts no new replies.")

        reply = DiscussionReply(
            discussion_id=discussion.id, author_id=actor.id, body=payload.body
        )
        await self.replies.add_and_flush(reply)
        stored = await self.replies.get_by_public_id_full(reply.public_id)
        # The parent's public id is returned alongside rather than read off
        # `reply.discussion`: that relationship is `lazy="raise"` on purpose,
        # and the caller already has the thread in hand.
        return stored, discussion.public_id  # type: ignore[return-value]

    async def update_reply(
        self, reply_id: uuid.UUID, payload: ReplyRequest, *, actor: User
    ) -> tuple[DiscussionReply, uuid.UUID]:
        reply, discussion = await self._load_reply(reply_id, actor=actor)

        if reply.author_id != actor.id:
            # Not even a moderator: editing somebody else's words in place,
            # under their name, is not moderation. A moderator removes.
            raise AuthorizationError("You can only edit your own reply.")

        if discussion.is_locked and not await self._is_moderator(actor, discussion.course_id):
            raise ValidationError("This discussion is locked.")

        reply.body = payload.body
        return reply, discussion.public_id

    async def delete_reply(self, reply_id: uuid.UUID, *, actor: User) -> None:
        reply, discussion = await self._load_reply(reply_id, actor=actor)

        if reply.author_id != actor.id and not await self._is_moderator(
            actor, discussion.course_id
        ):
            raise AuthorizationError("You can only delete your own reply.")

        entity_id = reply.id
        await self.session.delete(reply)

        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="discussion_reply",
            entity_id=entity_id,
            details={"discussion_id": str(discussion.public_id)},
        )

    # -- policy --------------------------------------------------------------

    async def _assert_visible(self, actor: User, course_id: int) -> None:
        courses = await self.scopes.visible_course_ids(actor)
        if not courses.allows(course_id):
            # 404 rather than 403 throughout: a thread in a course the caller
            # has nothing to do with must not be provable to exist.
            raise NotFoundError("Discussion not found.")

    async def _is_moderator(self, actor: User, course_id: int) -> bool:
        if ScopeResolver.is_unrestricted(actor):
            return True
        work = await self.scopes.work_visibility(actor)
        return course_id in work.taught_course_ids

    async def _load_reply(
        self, reply_id: uuid.UUID, *, actor: User
    ) -> tuple[DiscussionReply, CourseDiscussion]:
        reply = await self.replies.get_by_public_id_full(reply_id)
        if reply is None:
            raise NotFoundError("Reply not found.")
        discussion = await self.discussions.get_by_id(reply.discussion_id)
        if discussion is None:
            raise NotFoundError("Reply not found.")
        await self._assert_visible(actor, discussion.course_id)
        return reply, discussion

    async def _resolve_course(self, public_id: uuid.UUID) -> int:
        stmt = select(Course.id).where(Course.public_id == public_id)
        course_id = (await self.session.execute(stmt)).scalar_one_or_none()
        if course_id is None:
            raise NotFoundError("Course not found.")
        return int(course_id)

"""Global search (spec §22).

**Search is a fan-out over the existing scoped listings, not a new query
surface.** Every group below delegates to the domain's own repository
`search()` — the same method the domain's own endpoint calls, with the same
scope object. That is the whole design: search touches every table at once,
which makes it the single most likely place for a row-scoping rule to be
re-derived slightly differently and get it wrong. Here there is nothing to
re-derive. If `/courses` cannot show you a draft course, neither can search,
because it is the same query.

**A type the caller cannot read at all is skipped, not emptied.** Returning
an empty `user` group to a student implies there were no matching people;
`skipped` says the question was never asked. The distinction matters on a
screen whose job is to tell somebody what exists.

**Groups are capped independently.** One type with three thousand matches
must not crowd the other six out of the response, so each gets its own slice
and reports its own `total` — the count the caller *may see*, computed by the
same scoped query, never a global count.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ValidationError
from backend.core.permissions import Action, Module, perm
from backend.models.identity.user import User
from backend.repositories.announcement import AnnouncementRepository
from backend.repositories.assignment import AssignmentRepository
from backend.repositories.batch import BatchRepository
from backend.repositories.course import CourseRepository
from backend.repositories.discussion import DiscussionRepository
from backend.repositories.resource import (
    ResourcePermissionRepository,
    ResourceRepository,
    SharedResourceRepository,
)
from backend.repositories.user import UserRepository
from backend.schemas.base import PageParams
from backend.schemas.search import SearchGroup, SearchHit, SearchResponse, SearchType
from backend.services.scope import ScopeResolver

# Two characters is the shortest query with any selectivity. A single
# character matches most of every table, so the index cannot help and the
# answer is useless -- refused rather than served slowly.
MIN_QUERY = 2
MAX_QUERY = 100
DEFAULT_PER_TYPE = 5
MAX_PER_TYPE = 25


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class _Group:
    type: SearchType
    permission: str


# Which permission a caller must hold for the group to be searched at all.
# Row-level scoping is applied *on top* of this by each repository; this is
# only the "may you look at this kind of thing" half.
_GROUPS: tuple[_Group, ...] = (
    _Group(SearchType.COURSE, perm(Module.COURSE, Action.READ)),
    _Group(SearchType.USER, perm(Module.USER, Action.READ)),
    _Group(SearchType.BATCH, perm(Module.BATCH, Action.READ)),
    _Group(SearchType.RESOURCE, perm(Module.RESOURCE, Action.READ)),
    _Group(SearchType.ASSIGNMENT, perm(Module.ASSIGNMENT, Action.READ)),
    _Group(SearchType.ANNOUNCEMENT, perm(Module.ANNOUNCEMENT, Action.READ)),
    _Group(SearchType.DISCUSSION, perm(Module.DISCUSSION, Action.READ)),
)


class SearchService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.scopes = ScopeResolver(session)

    async def search(
        self,
        *,
        actor: User,
        query: str,
        types: Sequence[SearchType] | None = None,
        per_type: int = DEFAULT_PER_TYPE,
    ) -> SearchResponse:
        text = (query or "").strip()
        if len(text) < MIN_QUERY:
            raise ValidationError(
                f"Search needs at least {MIN_QUERY} characters.",
                details={"min_length": MIN_QUERY},
            )
        if len(text) > MAX_QUERY:
            raise ValidationError("Search query is too long.")
        per_type = max(1, min(per_type, MAX_PER_TYPE))

        held = ScopeResolver.held_permissions(actor)
        wanted = set(types) if types else {g.type for g in _GROUPS}

        searched: list[SearchType] = []
        skipped: list[SearchType] = []
        groups: list[SearchGroup] = []

        for group in _GROUPS:
            if group.type not in wanted:
                continue
            if group.permission not in held:
                skipped.append(group.type)
                continue

            searched.append(group.type)
            hits, total = await self._run(group.type, actor=actor, query=text, limit=per_type)
            groups.append(
                SearchGroup(
                    type=group.type,
                    total=total,
                    items=hits,
                    truncated=total > len(hits),
                )
            )

        return SearchResponse(
            query=text,
            generated_at=_now(),
            searched=searched,
            skipped=skipped,
            total=sum(g.total for g in groups),
            groups=[g for g in groups if g.total],
        )

    # -- per-type delegation -------------------------------------------------

    async def _run(
        self, kind: SearchType, *, actor: User, query: str, limit: int
    ) -> tuple[list[SearchHit], int]:
        params = PageParams(limit=limit, offset=0)
        handler = getattr(self, f"_search_{kind.value}")
        return await handler(actor=actor, query=query, params=params)

    async def _search_course(self, *, actor: User, query: str, params: PageParams):  # type: ignore[no-untyped-def]
        rows, total = await CourseRepository(self.session).search(
            params,
            unrestricted=ScopeResolver.is_unrestricted(actor),
            tutor_course_ids=await self.scopes.tutor_course_ids(actor),
            query=query,
        )
        return [
            SearchHit(
                type=SearchType.COURSE,
                public_id=r.public_id,
                label=r.title,
                subtitle=r.code or r.status.value,
                created_at=r.created_at,
            )
            for r in rows
        ], total

    async def _search_user(self, *, actor: User, query: str, params: PageParams):  # type: ignore[no-untyped-def]
        scope = await self.scopes.visible_student_ids(actor)
        rows, total = await UserRepository(self.session).search(
            params, query=query, scope=scope
        )
        return [
            SearchHit(
                type=SearchType.USER,
                public_id=r.public_id,
                label=r.full_name or r.username,
                subtitle=r.username,
                created_at=getattr(r, "created_at", None),
            )
            for r in rows
        ], total

    async def _search_batch(self, *, actor: User, query: str, params: PageParams):  # type: ignore[no-untyped-def]
        rows, total = await BatchRepository(self.session).search(
            params, scope=await self.scopes.visible_batch_ids(actor), query=query
        )
        return [
            SearchHit(
                type=SearchType.BATCH,
                public_id=r.public_id,
                label=r.batch_code,
                subtitle=r.course.title if r.course else None,
            )
            for r in rows
        ], total

    async def _search_resource(self, *, actor: User, query: str, params: PageParams):  # type: ignore[no-untyped-def]
        # Resources are reachable three ways -- course, batch, or an explicit
        # grant/share -- so the extra ids are gathered exactly as the
        # resource listing gathers them.
        permissions = ResourcePermissionRepository(self.session)
        shares = SharedResourceRepository(self.session)
        extra = await shares.resource_ids_shared_with(actor.id)
        extra |= await permissions.resource_ids_for_scopes([("USER", actor.id)])

        rows, total = await ResourceRepository(self.session).search(
            params,
            course_scope=await self.scopes.visible_course_ids(actor),
            batch_scope=await self.scopes.visible_batch_ids(actor),
            extra_resource_ids=extra,
            query=query,
        )
        return [
            SearchHit(
                type=SearchType.RESOURCE,
                public_id=r.public_id,
                label=r.name,
                subtitle=r.course.title if r.course else None,
                created_at=r.created_at,
            )
            for r in rows
        ], total

    async def _search_assignment(self, *, actor: User, query: str, params: PageParams):  # type: ignore[no-untyped-def]
        work = await self.scopes.work_visibility(actor)
        from backend.services.scope import Scope

        scope = (
            Scope.all()
            if work.unrestricted
            else Scope.of(set(work.taught_course_ids) | await self._enrolled_course_ids(actor))
        )
        rows, total = await AssignmentRepository(self.session).search(
            params, scope=scope, query=query
        )
        return [
            SearchHit(
                type=SearchType.ASSIGNMENT,
                public_id=r.public_id,
                label=r.title,
                subtitle=r.course.title if getattr(r, "course", None) else None,
            )
            for r in rows
        ], total

    async def _search_announcement(self, *, actor: User, query: str, params: PageParams):  # type: ignore[no-untyped-def]
        unrestricted = ScopeResolver.is_unrestricted(actor)
        rows, total = await AnnouncementRepository(self.session).search(
            params,
            now=_now(),
            audience_filter=not unrestricted,
            course_scope=None if unrestricted else await self.scopes.visible_course_ids(actor),
            batch_scope=None if unrestricted else await self.scopes.visible_batch_ids(actor),
            role_names={(r.name or "").upper() for r in (actor.roles or [])},
            query=query,
        )
        return [
            SearchHit(
                type=SearchType.ANNOUNCEMENT,
                public_id=r.public_id,
                label=r.title,
                subtitle=r.course.title if r.course else None,
                created_at=r.start_at,
            )
            for r in rows
        ], total

    async def _search_discussion(self, *, actor: User, query: str, params: PageParams):  # type: ignore[no-untyped-def]
        rows, total = await DiscussionRepository(self.session).search(
            params, course_scope=await self.scopes.visible_course_ids(actor), query=query
        )
        return [
            SearchHit(
                type=SearchType.DISCUSSION,
                public_id=r.public_id,
                label=r.title,
                subtitle=r.course.title if r.course else None,
                created_at=r.created_at,
            )
            for r in rows
        ], total

    # -- helpers -------------------------------------------------------------

    async def _enrolled_course_ids(self, actor: User) -> set[int]:
        """Courses this person is enrolled in, for assignment visibility.

        `work_visibility.taught_course_ids` covers a tutor; a student reaches
        an assignment through their own enrolment, which is the batch scope's
        courses.
        """
        from sqlalchemy import select

        from backend.models.batch import Batch

        batches = await self.scopes.visible_batch_ids(actor)
        if batches.unrestricted:
            return set()
        if not batches.ids:
            return set()
        stmt = select(Batch.course_id).where(Batch.id.in_(batches.ids))
        return set((await self.session.execute(stmt)).scalars().all())

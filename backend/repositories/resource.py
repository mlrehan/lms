"""Resource, folder, version, permission and sharing queries."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from backend.models.resource import (
    Resource,
    ResourceFolder,
    ResourcePermission,
    ResourceVersion,
    SharedResource,
)
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams
from backend.utils.enums import ResourcePermissionLevel, ResourceType

if TYPE_CHECKING:
    from backend.services.scope import Scope


class FolderRepository(BaseRepository[ResourceFolder]):
    model = ResourceFolder

    def _base(self) -> Select[tuple[ResourceFolder]]:
        return select(ResourceFolder).options(
            selectinload(ResourceFolder.parent),
            selectinload(ResourceFolder.course),
            selectinload(ResourceFolder.batch),
            selectinload(ResourceFolder.creator),
        )

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> ResourceFolder | None:
        stmt = self._base().where(ResourceFolder.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, folder_id: int) -> ResourceFolder | None:
        return await self.session.get(ResourceFolder, folder_id)

    async def children_of(self, parent_id: int | None, *, course_id: int | None,
                          batch_id: int | None) -> list[ResourceFolder]:
        stmt = self._base()
        if parent_id is None:
            stmt = stmt.where(ResourceFolder.parent_folder_id.is_(None))
            if course_id is not None:
                stmt = stmt.where(ResourceFolder.course_id == course_id)
            if batch_id is not None:
                stmt = stmt.where(ResourceFolder.batch_id == batch_id)
        else:
            stmt = stmt.where(ResourceFolder.parent_folder_id == parent_id)
        return list((await self.session.execute(stmt.order_by(ResourceFolder.name))).scalars().unique().all())

    async def sibling_named(
        self, *, name: str, parent_id: int | None, course_id: int | None,
        batch_id: int | None, exclude_id: int | None = None
    ) -> ResourceFolder | None:
        """A folder with the same name under the same parent.

        Two identically-named siblings make a path ambiguous the moment
        anyone refers to a folder by its path rather than its id.
        """
        stmt = select(ResourceFolder).where(func.lower(ResourceFolder.name) == name.strip().lower())
        if parent_id is None:
            stmt = stmt.where(ResourceFolder.parent_folder_id.is_(None))
            stmt = stmt.where(
                ResourceFolder.course_id == course_id
                if course_id is not None
                else ResourceFolder.course_id.is_(None)
            )
            stmt = stmt.where(
                ResourceFolder.batch_id == batch_id
                if batch_id is not None
                else ResourceFolder.batch_id.is_(None)
            )
        else:
            stmt = stmt.where(ResourceFolder.parent_folder_id == parent_id)
        if exclude_id is not None:
            stmt = stmt.where(ResourceFolder.id != exclude_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def counts(self, folder_id: int) -> tuple[int, int]:
        """``(child_folders, live_resources)``."""
        children = (
            await self.session.execute(
                select(func.count()).select_from(ResourceFolder).where(
                    ResourceFolder.parent_folder_id == folder_id
                )
            )
        ).scalar_one()
        resources = (
            await self.session.execute(
                select(func.count()).select_from(Resource).where(
                    Resource.folder_id == folder_id, Resource.is_deleted.is_(False)
                )
            )
        ).scalar_one()
        return int(children), int(resources)

    async def ancestors(self, folder: ResourceFolder) -> list[ResourceFolder]:
        """Root-first chain up to and including ``folder``.

        Walks with a visited set and a hard depth cap: a cycle introduced by
        a bad move would otherwise loop forever, and this is the query every
        breadcrumb render calls.
        """
        chain: list[ResourceFolder] = [folder]
        seen = {folder.id}
        current = folder
        while current.parent_folder_id is not None and len(chain) < 64:
            parent = await self.get_by_id(current.parent_folder_id)
            if parent is None or parent.id in seen:
                break
            chain.append(parent)
            seen.add(parent.id)
            current = parent
        return list(reversed(chain))

    async def descendant_ids(self, folder_id: int) -> set[int]:
        """Every folder beneath this one, used to refuse a move into a
        folder's own subtree (which would detach that subtree from the
        tree entirely)."""
        found: set[int] = set()
        frontier = [folder_id]
        while frontier and len(found) < 10_000:
            stmt = select(ResourceFolder.id).where(
                ResourceFolder.parent_folder_id.in_(frontier)
            )
            next_ids = [i for i in (await self.session.execute(stmt)).scalars().all() if i not in found]
            found.update(next_ids)
            frontier = next_ids
        return found


class ResourceRepository(BaseRepository[Resource]):
    model = Resource

    def _base(self) -> Select[tuple[Resource]]:
        return select(Resource).options(
            selectinload(Resource.folder),
            selectinload(Resource.course),
            selectinload(Resource.uploader),
            selectinload(Resource.versions).selectinload(ResourceVersion.resource),
        )

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> Resource | None:
        stmt = self._base().where(Resource.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_share_token(self, token: str) -> Resource | None:
        stmt = self._base().where(
            Resource.share_token == token, Resource.is_deleted.is_(False)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def search(
        self,
        params: PageParams,
        *,
        course_scope: "Scope",
        batch_scope: "Scope",
        extra_resource_ids: set[int] | None = None,
        folder_id: int | None = None,
        course_id: int | None = None,
        resource_type: ResourceType | None = None,
        query: str | None = None,
        include_deleted: bool = False,
        include_restricted: bool = False,
    ) -> tuple[Sequence[Resource], int]:
        stmt = self._base()

        if not include_deleted:
            stmt = stmt.where(Resource.is_deleted.is_(False))

        # Filtered in the query, not after it. Restricted rows are never loaded
        # for someone who may not see them, so a paging count cannot reveal
        # that there are files here they cannot name -- and the "unrestricted
        # scope" shortcut below must not be read as covering this, because it
        # is about *reachability*, which is a different question.
        if not include_restricted:
            stmt = stmt.where(Resource.is_restricted.is_(False))

        # Reachable through the resource's course, its batch, or an explicit
        # grant/share. Unrestricted callers skip the whole filter.
        if not (course_scope.unrestricted or batch_scope.unrestricted):
            conditions = []
            if course_scope.ids:
                conditions.append(Resource.course_id.in_(course_scope.ids))
            if batch_scope.ids:
                conditions.append(Resource.batch_id.in_(batch_scope.ids))
            if extra_resource_ids:
                conditions.append(Resource.id.in_(extra_resource_ids))
            if conditions:
                stmt = stmt.where(or_(*conditions))
            else:
                from sqlalchemy import false

                stmt = stmt.where(false())

        if folder_id is not None:
            stmt = stmt.where(Resource.folder_id == folder_id)
        if course_id is not None:
            stmt = stmt.where(Resource.course_id == course_id)
        if resource_type is not None:
            stmt = stmt.where(Resource.resource_type == resource_type)
        if query:
            stmt = stmt.where(func.lower(Resource.name).like(f"%{query.strip().lower()}%"))

        stmt = stmt.order_by(Resource.created_at.desc())
        return await self.paginate(stmt, params)  # type: ignore[return-value]

    async def next_version_number(self, resource_id: int) -> int:
        stmt = select(func.coalesce(func.max(ResourceVersion.version_number), 0)).where(
            ResourceVersion.resource_id == resource_id
        )
        return int((await self.session.execute(stmt)).scalar_one()) + 1

    async def versions_for(self, resource_id: int) -> list[ResourceVersion]:
        stmt = (
            select(ResourceVersion)
            .where(ResourceVersion.resource_id == resource_id)
            .order_by(ResourceVersion.version_number.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def version(self, resource_id: int, number: int) -> ResourceVersion | None:
        stmt = select(ResourceVersion).where(
            ResourceVersion.resource_id == resource_id,
            ResourceVersion.version_number == number,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


class ResourcePermissionRepository(BaseRepository[ResourcePermission]):
    model = ResourcePermission

    async def for_resource(self, resource_id: int) -> list[ResourcePermission]:
        stmt = select(ResourcePermission).where(ResourcePermission.resource_id == resource_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def for_folder(self, folder_id: int) -> list[ResourcePermission]:
        stmt = select(ResourcePermission).where(ResourcePermission.folder_id == folder_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, permission_id: int) -> ResourcePermission | None:
        return await self.session.get(ResourcePermission, permission_id)

    async def matching(
        self, *, resource_id: int | None, folder_id: int | None,
        scope_type, scope_id: int
    ) -> ResourcePermission | None:
        stmt = select(ResourcePermission).where(
            ResourcePermission.scope_type == scope_type,
            ResourcePermission.scope_id == scope_id,
        )
        stmt = (
            stmt.where(ResourcePermission.resource_id == resource_id)
            if resource_id is not None
            else stmt.where(ResourcePermission.folder_id == folder_id)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def levels_for_resource(
        self, resource_id: int, pairs: Sequence[tuple[str, int]]
    ) -> list[ResourcePermissionLevel]:
        """Every level granted on this resource through any of the caller's scopes.

        Returns all of them rather than a maximum: the caller combines these with
        the share and the role baseline, and doing the comparison in one place
        keeps the ladder's semantics out of SQL.
        """
        if not pairs:
            return []
        clauses = [
            (ResourcePermission.scope_type == scope_type)
            & (ResourcePermission.scope_id == scope_id)
            for scope_type, scope_id in pairs
        ]
        stmt = select(ResourcePermission.level).where(
            ResourcePermission.resource_id == resource_id, or_(*clauses)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def resource_ids_for_scopes(
        self, pairs: Sequence[tuple[str, int]]
    ) -> set[int]:
        """Resources explicitly granted to any of the caller's scopes."""
        if not pairs:
            return set()
        clauses = [
            (ResourcePermission.scope_type == scope_type)
            & (ResourcePermission.scope_id == scope_id)
            for scope_type, scope_id in pairs
        ]
        stmt = select(ResourcePermission.resource_id).where(
            ResourcePermission.resource_id.is_not(None), or_(*clauses)
        )
        return set((await self.session.execute(stmt)).scalars().all())


class SharedResourceRepository(BaseRepository[SharedResource]):
    model = SharedResource

    def _base(self) -> Select[tuple[SharedResource]]:
        return select(SharedResource).options(
            selectinload(SharedResource.resource),
            selectinload(SharedResource.shared_with_user),
            selectinload(SharedResource.shared_by_user),
        )

    async def for_resource(self, resource_id: int) -> list[SharedResource]:
        stmt = self._base().where(SharedResource.resource_id == resource_id)
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def shared_with(self, user_id: int) -> list[SharedResource]:
        stmt = self._base().where(SharedResource.shared_with_user_id == user_id)
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def resource_ids_shared_with(self, user_id: int) -> set[int]:
        stmt = select(SharedResource.resource_id).where(
            SharedResource.shared_with_user_id == user_id
        )
        return set((await self.session.execute(stmt)).scalars().all())

    async def existing(self, *, resource_id: int, user_id: int) -> SharedResource | None:
        stmt = select(SharedResource).where(
            SharedResource.resource_id == resource_id,
            SharedResource.shared_with_user_id == user_id,
        )
        return (await self.session.execute(stmt)).scalars().first()

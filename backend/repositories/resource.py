"""Resource, folder, version, permission and sharing queries."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.orm import raiseload, selectinload

from backend.models.resource import (
    Resource,
    ResourceFolder,
    ResourcePermission,
    ResourceVersion,
    SharedFolder,
    SharedResource,
)
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams
from backend.utils.enums import ResourcePermissionLevel, ResourceType

from backend.models.identity.user import User

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


#: What a loaded resource carries: the flat fields its responses read, and
#: nothing behind them.
#:
#: Every relationship on these models is `lazy="selectin"`, so loading *one*
#: resource used to load its course -- and through the course every batch,
#: every session, every enrolment, every other resource in the course, and
#: every user on any of them with their city, country and organisations.
#: Measured on a course with 7 batches and 20 sessions: sharing 12 files cost
#: 3,256 queries and 20 seconds, which is the 30-second proxy timeout in
#: production once the course is busier. `raiseload("*")` on the nested side
#: makes a read that reaches further fail loudly in a test, instead of
#: quietly reintroducing the cascade.
RESOURCE_LOAD = (
    selectinload(Resource.folder).raiseload("*"),
    selectinload(Resource.course).raiseload("*"),
    selectinload(Resource.batch).raiseload("*"),
    selectinload(Resource.uploader).raiseload("*"),
    selectinload(Resource.versions).raiseload("*"),
    # `passive_deletes=True`, so deleting a resource never needs this loaded.
    raiseload(Resource.shared_resources),
)


class ResourceRepository(BaseRepository[Resource]):
    model = Resource

    def _base(self) -> Select[tuple[Resource]]:
        return select(Resource).options(*RESOURCE_LOAD)

    async def by_public_ids(self, public_ids: Sequence[uuid.UUID]) -> list[Resource]:
        """Several resources in one round trip, with the same bounded graph."""
        if not public_ids:
            return []
        stmt = self._base().where(Resource.public_id.in_(list(public_ids)))
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def ids_in_folders(self, folder_ids: set[int], *, limit: int) -> list[int]:
        """Live resources directly inside these folders, at most ``limit``."""
        if not folder_ids:
            return []
        stmt = (
            select(Resource.id)
            .where(Resource.folder_id.in_(folder_ids), Resource.is_deleted.is_(False))
            .order_by(Resource.id)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def live_in_folder(self, folder_id: int, *, include_restricted: bool) -> list[Resource]:
        """The files directly inside one folder, for a shared-folder listing."""
        stmt = self._base().where(
            Resource.folder_id == folder_id, Resource.is_deleted.is_(False)
        )
        if not include_restricted:
            stmt = stmt.where(Resource.is_restricted.is_(False))
        stmt = stmt.order_by(func.lower(Resource.name), Resource.id)
        return list((await self.session.execute(stmt)).scalars().unique().all())


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
        root_only: bool = False,
        course_id: int | None = None,
        resource_type: ResourceType | None = None,
        query: str | None = None,
        include_deleted: bool = False,
        include_restricted: bool = False,
        uploader_id: int | None = None,
        status: str | None = None,
    ) -> tuple[Sequence[Resource], int]:
        stmt = self._base()

        if status == "deleted":
            stmt = stmt.where(Resource.is_deleted.is_(True))
        elif status == "active":
            stmt = stmt.where(Resource.is_deleted.is_(False))
        elif status == "all":
            # Both active and deleted resources
            pass
        elif not include_deleted:
            stmt = stmt.where(Resource.is_deleted.is_(False))
        else:
            # Recycle bin listing
            stmt = stmt.where(Resource.is_deleted.is_(True))

        if uploader_id is not None:
            stmt = stmt.where(Resource.uploaded_by == uploader_id)


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
        elif root_only:
            # `folder_id=None` means "don't filter", which is what a *search*
            # wants -- so there was no way to ask for the files that sit at the
            # root and nowhere else. Browsing the library root therefore listed
            # every file in every folder, and moving a file into a folder left
            # it sitting in the root as well. `ResourceFolderRepository` has
            # always made this distinction (`parent_folder_id.is_(None)`); the
            # resource side simply never did.
            stmt = stmt.where(Resource.folder_id.is_(None))
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

    async def levels_for_resources(
        self, resource_ids: Sequence[int], pairs: Sequence[tuple[str, int]]
    ) -> dict[int, list[ResourcePermissionLevel]]:
        """`levels_for_resource`, for many resources in one query."""
        if not pairs or not resource_ids:
            return {}
        clauses = [
            (ResourcePermission.scope_type == scope_type)
            & (ResourcePermission.scope_id == scope_id)
            for scope_type, scope_id in pairs
        ]
        stmt = select(ResourcePermission.resource_id, ResourcePermission.level).where(
            ResourcePermission.resource_id.in_(list(resource_ids)), or_(*clauses)
        )
        found: dict[int, list[ResourcePermissionLevel]] = {}
        for resource_id, level in (await self.session.execute(stmt)).all():
            found.setdefault(resource_id, []).append(level)
        return found

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
        # The same bounded graph as `RESOURCE_LOAD`, and for the people only
        # what `_share_response` prints: names, and the recipient's roles for
        # the role label. Unbounded, every row of "Shared with me" loaded the
        # file's whole course and both users' whole profiles.
        file = selectinload(SharedResource.resource)
        return select(SharedResource).options(
            file.selectinload(Resource.course).raiseload("*"),
            file.selectinload(Resource.batch).raiseload("*"),
            file.selectinload(Resource.folder).raiseload("*"),
            file.raiseload("*"),
            selectinload(SharedResource.shared_with_user)
            .selectinload(User.roles)
            .raiseload("*"),
            selectinload(SharedResource.shared_with_user).raiseload("*"),
            selectinload(SharedResource.shared_by_user).raiseload("*"),
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

    async def levels_for_user(
        self, resource_ids: Sequence[int], user_id: int
    ) -> dict[int, ResourcePermissionLevel]:
        """`{resource_id: level}` of direct shares to one person."""
        if not resource_ids:
            return {}
        stmt = select(SharedResource.resource_id, SharedResource.level).where(
            SharedResource.resource_id.in_(list(resource_ids)),
            SharedResource.shared_with_user_id == user_id,
        )
        return {rid: level for rid, level in (await self.session.execute(stmt)).all()}

    async def existing(self, *, resource_id: int, user_id: int) -> SharedResource | None:
        # Callers read `level` and delete the row; nothing reaches through it.
        stmt = select(SharedResource).options(raiseload("*")).where(
            SharedResource.resource_id == resource_id,
            SharedResource.shared_with_user_id == user_id,
        )
        return (await self.session.execute(stmt)).scalars().first()


#: How far a share reaches up or down the folder tree. Folders are created by
#: people, and nobody nests a course library sixty-four levels deep; the cap
#: exists so a cycle written by a bad move (which `move_folder` refuses, but a
#: migration or a direct edit would not) cannot turn a query into a loop.
MAX_FOLDER_DEPTH = 64
#: The most folders one person's shared trees may expand to in a listing.
MAX_SHARED_FOLDERS = 5_000

_UP = text(
    """
    WITH RECURSIVE up(start_id, folder_id, depth) AS (
        SELECT f.id, f.id, 0 FROM resource_folders f WHERE f.id = ANY(:folder_ids)
        UNION ALL
        SELECT up.start_id, f.parent_folder_id, up.depth + 1
        FROM up JOIN resource_folders f ON f.id = up.folder_id
        WHERE f.parent_folder_id IS NOT NULL AND up.depth < :max_depth
    )
    SELECT up.start_id, sf.level
    FROM up JOIN shared_folders sf
      ON sf.folder_id = up.folder_id AND sf.shared_with_user_id = :user_id
    """
)

_DOWN = text(
    """
    WITH RECURSIVE down(folder_id, depth) AS (
        SELECT sf.folder_id, 0 FROM shared_folders sf WHERE sf.shared_with_user_id = :user_id
        UNION
        SELECT f.id, down.depth + 1
        FROM down JOIN resource_folders f ON f.parent_folder_id = down.folder_id
        WHERE down.depth < :max_depth
    )
    SELECT DISTINCT folder_id FROM down LIMIT :limit
    """
)


class SharedFolderRepository(BaseRepository[SharedFolder]):
    model = SharedFolder

    async def levels_through_tree(
        self, folder_ids: set[int], user_id: int
    ) -> dict[int, list[ResourcePermissionLevel]]:
        """``{folder_id: [levels]}``: what ``user_id`` holds on each folder
        through a share on it or on any ancestor. One query for any number of
        folders, whatever their depth."""
        if not folder_ids:
            return {}
        rows = await self.session.execute(
            _UP, {"folder_ids": list(folder_ids), "user_id": user_id, "max_depth": MAX_FOLDER_DEPTH}
        )
        found: dict[int, list[ResourcePermissionLevel]] = {}
        for start_id, level in rows.all():
            found.setdefault(start_id, []).append(ResourcePermissionLevel(level))
        return found

    async def reachable_folder_ids(self, user_id: int) -> set[int]:
        """Every folder inside a tree shared with ``user_id``, roots included."""
        rows = await self.session.execute(
            _DOWN, {"user_id": user_id, "max_depth": MAX_FOLDER_DEPTH, "limit": MAX_SHARED_FOLDERS}
        )
        return set(rows.scalars().all())

    def _listed(self) -> Select[tuple[SharedFolder]]:
        folder = selectinload(SharedFolder.folder)
        return select(SharedFolder).options(
            folder.selectinload(ResourceFolder.course).raiseload("*"),
            folder.selectinload(ResourceFolder.batch).raiseload("*"),
            folder.raiseload("*"),
            selectinload(SharedFolder.shared_with_user).selectinload(User.roles).raiseload("*"),
            selectinload(SharedFolder.shared_with_user).raiseload("*"),
            selectinload(SharedFolder.shared_by_user).raiseload("*"),
        )

    async def shared_with(self, user_id: int) -> list[SharedFolder]:
        stmt = self._listed().where(SharedFolder.shared_with_user_id == user_id)
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def for_folder(self, folder_id: int) -> list[SharedFolder]:
        stmt = self._listed().where(SharedFolder.folder_id == folder_id).order_by(SharedFolder.id)
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def existing(self, *, folder_id: int, user_id: int) -> SharedFolder | None:
        stmt = select(SharedFolder).options(raiseload("*")).where(
            SharedFolder.folder_id == folder_id, SharedFolder.shared_with_user_id == user_id
        )
        return (await self.session.execute(stmt)).scalars().first()

"""Learning resources and file management (spec §10–§11).

Bytes never touch this module's callers: uploads arrive as a `UploadFile`,
are validated here, and are handed to whichever `StorageBackend`
`STORAGE_MODE` selected. Everything the database stores is an opaque storage
*key*, so moving from local disk to R2 changes one env var and nothing else.

**A resource's visibility has three independent routes**, and that is the
whole shape of spec §11's cascade: the course it belongs to, the batch it
belongs to, or an explicit grant (`resource_permissions`) / share
(`shared_resources`). A student on a different course who has been handed one
file must be able to open that file and nothing else, which neither the
course nor the batch route can express.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime
from typing import Sequence

from fastapi import UploadFile
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession


from backend.core.config import get_settings
from backend.core.resource_access import at_least, highest
from backend.core.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from backend.core.logging import get_logger
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.identity.user import User
from backend.models.resource import (
    Resource,
    ResourceFolder,
    ResourcePermission,
    ResourceVersion,
    SharedResource,
)
from backend.repositories.resource import (
    FolderRepository,
    ResourcePermissionRepository,
    ResourceRepository,
    SharedResourceRepository,
)
from backend.core.privacy import visible_username
from backend.schemas.base import PageParams
from backend.schemas.resource import (
    DeletionImpactResponse,
    FolderCreateRequest,
    FolderUpdateRequest,
    GrantInfo,
    GrantPermissionRequest,
    ResourceImpactItem,
    ResourceUpdateRequest,
    SharedUserInfo,
)
from backend.services import audit_service
from backend.core.permissions import Action as _Act, Module as _Mod, perm as _perm
from backend.services.audit_service import AuditAction
from backend.services.batch_service import BatchService
from backend.services.resource_audience import ResourceShareAudience, display_name, role_label
from backend.services.course_service import CourseService
from backend.services.scope import ScopeResolver
from backend.storage import get_storage
from backend.storage.base import build_key
from backend.utils.enums import ResourcePermissionLevel, ResourceScopeType, ResourceType


logger = get_logger(__name__)

_UNSET = object()

#: Holding this is what separates staff from the audience a restricted file is
#: kept away from. Resolved as a permission rather than a role name so an
#: institution can add a registrar or an external examiner later.
_VIEW_RESTRICTED = _perm(_Mod.RESOURCE, _Act.VIEW_RESTRICTED)


class ResourceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.resources = ResourceRepository(session)
        self.folders = FolderRepository(session)
        self.permissions = ResourcePermissionRepository(session)
        self.shares = SharedResourceRepository(session)
        self.courses = CourseService(session)
        self.batches = BatchService(session)
        self.scopes = ScopeResolver(session)
        self.storage = get_storage()
        self.settings = get_settings().storage

    # -- folders -------------------------------------------------------------

    async def list_folders(
        self,
        *,
        actor: User,
        parent_public_id: uuid.UUID | None,
        course_public_id: uuid.UUID | None,
        batch_public_id: uuid.UUID | None,
    ) -> list[ResourceFolder]:
        parent_id = None
        course_id = None
        batch_id = None

        if parent_public_id is not None:
            parent = await self.get_folder(parent_public_id, actor=actor)
            parent_id = parent.id
        else:
            if course_public_id is not None:
                course_id = (await self.courses.get(course_public_id, actor=actor)).id
            if batch_public_id is not None:
                batch_id = (await self.batches.get(batch_public_id, actor=actor)).id

        rows = await self.folders.children_of(
            parent_id, course_id=course_id, batch_id=batch_id
        )
        # Filtered by the *same* rule `get_folder` applies, because the listing
        # and the thing it links to must agree. It did not: `children_of` has no
        # reachability filter, so the list showed every folder at that level to
        # everyone -- opening one then answered "Folder not found", and the
        # names of folders belonging to other people's courses were readable by
        # anybody who could reach this endpoint. A list is a disclosure, not a
        # convenience.
        #
        # Filtered rather than refused: a tutor opening the library should see
        # their own courses' folders, not an error because somebody else's is at
        # the same level.
        reachable = []
        for row in rows:
            if await self._folder_reachable(row, actor):
                reachable.append(row)
        return reachable

    async def get_folder(self, public_id: uuid.UUID, *, actor: User) -> ResourceFolder:
        folder = await self.folders.get_by_public_id_full(public_id)
        if folder is None:
            raise NotFoundError("Folder not found.")
        if not await self._folder_reachable(folder, actor):
            raise NotFoundError("Folder not found.")
        return folder

    async def create_folder(
        self, payload: FolderCreateRequest, *, actor: User
    ) -> ResourceFolder:
        parent = None
        course_id = None
        batch_id = None

        if payload.parent_id is not None:
            parent = await self.get_folder(payload.parent_id, actor=actor)
            # A child inherits its anchor rather than accepting its own: a
            # subtree whose branches claimed different courses would be
            # reachable by two different audiences at once.
            course_id = parent.course_id
            batch_id = parent.batch_id
        else:
            if payload.course_id is not None:
                course_id = (await self.courses.get(payload.course_id, actor=actor)).id
            if payload.batch_id is not None:
                batch = await self.batches.get(payload.batch_id, actor=actor)
                batch_id = batch.id
                if course_id is None:
                    course_id = batch.course_id

        if await self.folders.sibling_named(
            name=payload.name,
            parent_id=parent.id if parent else None,
            course_id=course_id,
            batch_id=batch_id,
        ):
            raise ConflictError("A folder with that name already exists here.")

        folder = ResourceFolder(
            name=payload.name,
            parent_folder_id=parent.id if parent else None,
            course_id=course_id,
            batch_id=batch_id,
            created_by=actor.id,
            created_at=datetime.now(UTC),
        )
        # Initialise the collections before the object becomes persistent.
        # `children`/`resources` are `lazy="selectin"`, which only loads them
        # for objects fetched *by a query* -- a brand-new instance has them
        # unloaded, and the unit of work touches them while flushing the
        # bidirectional parent/children link, which under asyncio raises
        # MissingGreenlet rather than quietly issuing a SELECT.
        folder.children = []
        folder.resources = []
        self.session.add(folder)
        await self.session.flush()

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="resource_folder",
            entity_id=folder.id,
            details={"name": folder.name},
        )
        # Re-read so `parent`/`course`/`batch`/`creator` are eager-loaded for
        # the response; they are unloaded on the instance just constructed.
        return await self.folders.get_by_public_id_full(folder.public_id)  # type: ignore[return-value]

    async def update_folder(
        self, public_id: uuid.UUID, payload: FolderUpdateRequest, *, actor: User
    ) -> ResourceFolder:
        folder = await self.get_folder(public_id, actor=actor)
        changes = payload.model_dump(exclude_unset=True)

        new_parent_id = folder.parent_folder_id
        if "parent_id" in changes:
            if changes["parent_id"] is None:
                new_parent_id = None
            else:
                target = await self.get_folder(changes["parent_id"], actor=actor)
                if target.id == folder.id:
                    raise ConflictError("A folder cannot be its own parent.")
                if target.id in await self.folders.descendant_ids(folder.id):
                    # Moving a folder inside its own subtree detaches that
                    # whole subtree from the tree -- it becomes unreachable
                    # from any root while still existing.
                    raise ConflictError("A folder cannot be moved inside itself.")
                new_parent_id = target.id
                folder.course_id = target.course_id
                folder.batch_id = target.batch_id

        new_name = changes.get("name", folder.name)
        if await self.folders.sibling_named(
            name=new_name,
            parent_id=new_parent_id,
            course_id=folder.course_id,
            batch_id=folder.batch_id,
            exclude_id=folder.id,
        ):
            raise ConflictError("A folder with that name already exists there.")

        folder.name = new_name
        folder.parent_folder_id = new_parent_id

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="resource_folder",
            entity_id=folder.id,
            details={"fields": sorted(changes)},
        )
        await self.session.flush()
        # The parent changed underneath an already-loaded `parent`, so the
        # response would otherwise report where the folder used to live.
        self.session.expire(folder, ["parent", "course", "batch"])
        return await self.folders.get_by_public_id_full(folder.public_id)  # type: ignore[return-value]

    async def delete_folder(self, public_id: uuid.UUID, *, actor: User) -> None:
        folder = await self.get_folder(public_id, actor=actor)
        children, resources = await self.folders.counts(folder.id)

        if children or resources:
            # The FK cascades, so deleting would silently take the whole
            # subtree and every file in it. Emptying first is deliberate.
            raise ConflictError(
                "This folder is not empty.",
                details={"subfolders": children, "resources": resources},
            )

        entity_id = folder.id
        await self.session.delete(folder)
        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="resource_folder",
            entity_id=entity_id,
        )

    async def folder_path(self, folder: ResourceFolder) -> list[str]:
        return [f.name for f in await self.folders.ancestors(folder)]

    # -- resources -----------------------------------------------------------

    async def list_resources(
        self,
        params: PageParams,
        *,
        actor: User,
        folder_public_id: uuid.UUID | None = None,
        root_only: bool = False,
        course_public_id: uuid.UUID | None = None,
        resource_type: ResourceType | None = None,
        query: str | None = None,
        include_deleted: bool = False,
        uploader_public_id: uuid.UUID | None = None,
        only_mine: bool = False,
        status: str | None = None,
    ) -> tuple[Sequence[Resource], int]:
        folder_id = None
        if folder_public_id is not None:
            folder_id = (await self.get_folder(folder_public_id, actor=actor)).id

        course_id = None
        if course_public_id is not None:
            course_id = (await self.courses.get(course_public_id, actor=actor)).id

        uploader_id: int | None = None
        if only_mine:
            uploader_id = actor.id
        elif uploader_public_id is not None:
            user = await self._load_user(uploader_public_id)
            uploader_id = user.id

        course_scope = await self.scopes.visible_course_ids(actor)
        batch_scope = await self.scopes.visible_batch_ids(actor)
        extra = await self._explicitly_granted_resource_ids(actor)

        is_super = getattr(actor, "is_super_admin", False) or any(
            (r.name or "").upper() == "SUPER_ADMIN" for r in (getattr(actor, "roles", []) or [])
        )
        can_manage = await self._can_manage(actor) or is_super

        resolved_status = status
        if resolved_status in ("all", "deleted") and not can_manage:
            resolved_status = "active"

        return await self.resources.search(
            params,
            course_scope=course_scope,
            batch_scope=batch_scope,
            extra_resource_ids=extra,
            folder_id=folder_id,
            root_only=root_only and folder_id is None and not query,
            course_id=course_id,
            resource_type=resource_type,
            query=query,
            include_deleted=include_deleted and can_manage,
            include_restricted=self.may_see_restricted(actor),
            uploader_id=uploader_id,
            status=resolved_status,
        )


    @staticmethod
    def may_see_restricted(actor: User) -> bool:
        return _VIEW_RESTRICTED in ScopeResolver.held_permissions(actor)

    async def get(self, public_id: uuid.UUID, *, actor: User) -> Resource:
        row = await self.resources.get_by_public_id_full(public_id)
        if row is None:
            raise NotFoundError("Resource not found.")

        # Checked first, and deliberately *before* reachability: a restricted
        # file is refused to a student even when it was shared with them
        # directly. A restriction that a share could override would protect
        # nothing, and sharing is exactly how this material moves between
        # staff. 404, not 403 -- a file this person should never have been
        # offered must not be provable to exist.
        if row.is_restricted and not self.may_see_restricted(actor):
            raise NotFoundError("Resource not found.")

        if not await self._resource_reachable(row, actor):
            raise NotFoundError("Resource not found.")
        if row.is_deleted and not await self._can_manage(actor):
            # A soft-deleted resource is gone as far as its audience is
            # concerned; only someone who could restore it may still see it.
            raise NotFoundError("Resource not found.")
        return row

    async def upload(
        self,
        *,
        upload: UploadFile,
        actor: User,
        name: str | None,
        resource_type: ResourceType,
        folder_public_id: uuid.UUID | None,
        course_public_id: uuid.UUID | None,
        batch_public_id: uuid.UUID | None,
    ) -> Resource:
        folder = None
        course_id = None
        batch_id = None

        if folder_public_id is not None:
            folder = await self.get_folder(folder_public_id, actor=actor)
            course_id = folder.course_id
            batch_id = folder.batch_id
        else:
            if course_public_id is not None:
                course_id = (await self.courses.get(course_public_id, actor=actor)).id
            if batch_public_id is not None:
                batch = await self.batches.get(batch_public_id, actor=actor)
                batch_id = batch.id
                if course_id is None:
                    course_id = batch.course_id

        if course_id is None and batch_id is None:
            raise ValidationError(
                "A resource must belong to a folder, a course, or a batch."
            )

        data = await self._read_and_validate(upload)

        resource = Resource(
            resource_type=resource_type,
            name=name or upload.filename or "untitled",
            course_id=course_id,
            batch_id=batch_id,
            folder_id=folder.id if folder else None,
            uploaded_by=actor.id,
            modified_by=actor.id,
            is_deleted=False,
            created_at=datetime.now(UTC),
        )
        # Same reason as `create_folder`: unloaded collections on a new
        # instance become a lazy load during flush, which asyncio refuses.
        resource.versions = []
        resource.shared_resources = []
        self.session.add(resource)
        await self.session.flush()

        await self._store_new_version(
            resource=resource, data=data, upload=upload, actor=actor, change_note=None
        )

        audit_service.record(
            self.session,
            action=AuditAction.UPLOAD,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="resource",
            entity_id=resource.id,
            details={"name": resource.name, "size": len(data), "mime": upload.content_type},
        )
        return await self.resources.get_by_public_id_full(resource.public_id)  # type: ignore[return-value]

    async def upload_version(
        self,
        public_id: uuid.UUID,
        *,
        upload: UploadFile,
        actor: User,
        change_note: str | None,
    ) -> Resource:
        """Replace the file, keeping every earlier version (spec §10)."""
        resource = await self.get(public_id, actor=actor)
        await self.require_level(resource, actor, ResourcePermissionLevel.EDIT)
        data = await self._read_and_validate(upload)

        await self._store_new_version(
            resource=resource, data=data, upload=upload, actor=actor, change_note=change_note
        )
        resource.modified_by = actor.id

        audit_service.record(
            self.session,
            action=AuditAction.UPLOAD,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="resource",
            entity_id=resource.id,
            details={"new_version": True, "note": change_note},
        )
        self.session.expire(resource, ["versions"])
        return await self.resources.get_by_public_id_full(public_id)  # type: ignore[return-value]

    async def _store_new_version(
        self,
        *,
        resource: Resource,
        data: bytes,
        upload: UploadFile,
        actor: User,
        change_note: str | None,
    ) -> ResourceVersion:
        number = await self.resources.next_version_number(resource.id)
        key = build_key(prefix=f"resources/{resource.public_id}", filename=upload.filename)

        stored = await self.storage.save(key, data, content_type=upload.content_type)

        version = ResourceVersion(
            resource_id=resource.id,
            version_number=number,
            path=stored.key,
            mime_type=stored.mime_type,
            size=stored.size,
            uploaded_by=actor.id,
            change_note=change_note,
            created_at=datetime.now(UTC),
        )
        self.session.add(version)

        # The denormalised pointer on `Resource` is what "the current file"
        # means; keeping it in step here is the whole reason those columns
        # exist rather than joining to the newest version on every read.
        resource.path = stored.key
        resource.mime_type = stored.mime_type
        resource.size = stored.size

        await self.session.flush()
        # The row was inserted directly rather than appended to
        # `resource.versions`, so that collection still holds whatever it was
        # initialised or loaded with -- an empty list for a brand-new
        # resource, which made every fresh upload report `current_version: 0`.
        self.session.expire(resource, ["versions"])
        return version

    async def _read_and_validate(self, upload: UploadFile) -> bytes:
        data = await upload.read()

        if not data:
            raise ValidationError("The uploaded file is empty.")

        if len(data) > self.settings.max_upload_bytes:
            raise ValidationError(
                "File exceeds the maximum upload size.",
                details={
                    "max_bytes": self.settings.max_upload_bytes,
                    "received_bytes": len(data),
                },
            )

        allowed = self.settings.allowed_mime_types
        if allowed:
            content_type = (upload.content_type or "").split(";")[0].strip().lower()
            if content_type not in allowed:
                # Allowlist, not blocklist: a blocklist of dangerous types is
                # always one new format behind, while this fails closed on
                # anything unanticipated.
                raise ValidationError(
                    "That file type is not accepted.",
                    details={"content_type": content_type or None},
                )
        return data

    async def update(
        self, public_id: uuid.UUID, payload: ResourceUpdateRequest, *, actor: User
    ) -> Resource:
        resource = await self.get(public_id, actor=actor)
        await self.require_level(resource, actor, ResourcePermissionLevel.EDIT)
        changes = payload.model_dump(exclude_unset=True)

        if changes.get("is_restricted"):
            # Restricting is a withdrawal, so it has to withdraw everything --
            # including a public link issued while the file was open. Leaving
            # one live would mean the file is staff-only to everyone except
            # whoever already has the URL.
            if not self.may_see_restricted(actor):
                raise AuthorizationError(
                    "You cannot mark a file staff-only unless you can see staff-only files."
                )
            resource.share_token = None

        if "folder_id" in changes:
            if changes["folder_id"] is None:
                resource.folder_id = None
            else:
                folder = await self.get_folder(changes["folder_id"], actor=actor)
                resource.folder_id = folder.id
                # Moving a file between folders moves it between audiences;
                # its anchor follows the folder rather than being left
                # pointing at the course it used to live under.
                resource.course_id = folder.course_id
                resource.batch_id = folder.batch_id
            changes.pop("folder_id")

        for field, value in changes.items():
            setattr(resource, field, value)
        resource.modified_by = actor.id

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="resource",
            entity_id=resource.id,
            details={"fields": sorted(payload.model_dump(exclude_unset=True))},
        )
        self.session.expire(resource, ["folder", "course"])
        return await self.resources.get_by_public_id_full(public_id)  # type: ignore[return-value]

    async def copy(
        self,
        public_id: uuid.UUID,
        *,
        actor: User,
        target_folder_id: uuid.UUID | None,
        name: str | None,
    ) -> Resource:
        """Duplicate a resource, including its current bytes.

        The stored object is copied rather than referenced: two rows sharing
        one key would mean deleting either one takes the other's file with
        it.
        """
        source = await self.get(public_id, actor=actor)
        if not source.path:
            raise ConflictError("This resource has no file to copy.")

        folder = None
        course_id = source.course_id
        batch_id = source.batch_id
        if target_folder_id is not None:
            folder = await self.get_folder(target_folder_id, actor=actor)
            course_id = folder.course_id
            batch_id = folder.batch_id

        chunks: list[bytes] = []
        async for chunk in await self.storage.open_stream(source.path):
            chunks.append(chunk)
        data = b"".join(chunks)

        copy = Resource(
            resource_type=source.resource_type,
            name=name or f"{source.name} (copy)",
            course_id=course_id,
            batch_id=batch_id,
            folder_id=folder.id if folder else None,
            uploaded_by=actor.id,
            modified_by=actor.id,
            is_deleted=False,
            created_at=datetime.now(UTC),
        )
        copy.versions = []
        copy.shared_resources = []
        self.session.add(copy)
        await self.session.flush()

        key = build_key(prefix=f"resources/{copy.public_id}", filename=source.name)
        stored = await self.storage.save(key, data, content_type=source.mime_type)
        self.session.add(
            ResourceVersion(
                resource_id=copy.id,
                version_number=1,
                path=stored.key,
                mime_type=stored.mime_type,
                size=stored.size,
                uploaded_by=actor.id,
                change_note=f"Copied from {source.name}",
                created_at=datetime.now(UTC),
            )
        )
        copy.path = stored.key
        copy.mime_type = stored.mime_type
        copy.size = stored.size
        await self.session.flush()
        # This path builds its version row inline rather than through
        # `_store_new_version`, so it needs the same expiry -- without it the
        # copy reported `current_version: 0`.
        self.session.expire(copy, ["versions"])

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="resource",
            entity_id=copy.id,
            details={"copied_from": str(source.public_id)},
        )
        return await self.resources.get_by_public_id_full(copy.public_id)  # type: ignore[return-value]

    async def soft_delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        resource = await self.get(public_id, actor=actor)
        await self.require_level(resource, actor, ResourcePermissionLevel.MANAGE)
        if resource.is_deleted:
            raise ConflictError("This resource is already deleted.")

        resource.is_deleted = True
        resource.deleted_at = datetime.now(UTC)
        resource.modified_by = actor.id

        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="resource",
            entity_id=resource.id,
            details={"soft": True},
        )

    async def soft_delete_many(
        self, public_ids: Sequence[uuid.UUID], *, actor: User
    ) -> int:
        count = 0
        for public_id in public_ids:
            try:
                resource = await self.get(public_id, actor=actor)
            except NotFoundError:
                continue

            actual = await self.effective_level(resource, actor)
            if not at_least(actual, ResourcePermissionLevel.MANAGE):
                continue

            if resource.is_deleted:
                continue

            resource.is_deleted = True
            resource.deleted_at = datetime.now(UTC)
            resource.modified_by = actor.id

            audit_service.record(
                self.session,
                action=AuditAction.DELETE,
                actor_user_id=actor.id,
                actor_email=actor.email,
                entity_type="resource",
                entity_id=resource.id,
                details={"soft": True, "bulk": True},
            )
            count += 1
        return count

    async def restore(self, public_id: uuid.UUID, *, actor: User) -> Resource:
        resource = await self.resources.get_by_public_id_full(public_id)
        if resource is None or not await self._resource_reachable(resource, actor):
            raise NotFoundError("Resource not found.")
        await self.require_level(resource, actor, ResourcePermissionLevel.MANAGE)
        if not resource.is_deleted:
            raise ConflictError("This resource is not deleted.")

        resource.is_deleted = False
        resource.deleted_at = None
        resource.modified_by = actor.id

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="resource",
            entity_id=resource.id,
            details={"restored": True},
        )
        return resource

    async def restore_many(
        self, public_ids: Sequence[uuid.UUID], *, actor: User
    ) -> int:
        count = 0
        for public_id in public_ids:
            resource = await self.resources.get_by_public_id_full(public_id)
            if resource is None or not await self._resource_reachable(resource, actor):
                continue

            actual = await self.effective_level(resource, actor)
            if not at_least(actual, ResourcePermissionLevel.MANAGE):
                continue

            if not resource.is_deleted:
                continue

            resource.is_deleted = False
            resource.deleted_at = None
            resource.modified_by = actor.id

            audit_service.record(
                self.session,
                action=AuditAction.UPDATE,
                actor_user_id=actor.id,
                actor_email=actor.email,
                entity_type="resource",
                entity_id=resource.id,
                details={"restored": True, "bulk": True},
            )
            count += 1
        return count

    async def purge(self, public_id: uuid.UUID, *, actor: User, force: bool = False) -> None:
        """Permanently remove the row and every stored version."""
        resource = await self.resources.get_by_public_id_full(public_id)
        if resource is None or not await self._resource_reachable(resource, actor):
            raise NotFoundError("Resource not found.")
        await self.require_level(resource, actor, ResourcePermissionLevel.MANAGE)

        is_super = getattr(actor, "is_super_admin", False) or any(
            (r.name or "").upper() == "SUPER_ADMIN" for r in (getattr(actor, "roles", []) or [])
        )
        if not resource.is_deleted and not (is_super or force):
            raise ConflictError("Delete the resource before purging it.")

        # Clean up any direct shares and scope permissions first
        stmt_perms = delete(ResourcePermission).where(ResourcePermission.resource_id == resource.id)
        await self.session.execute(stmt_perms)
        stmt_shares = delete(SharedResource).where(SharedResource.resource_id == resource.id)
        await self.session.execute(stmt_shares)

        versions = await self.resources.versions_for(resource.id)
        paths_to_delete = {v.path for v in versions if v.path}
        if resource.path:
            paths_to_delete.add(resource.path)

        for path in paths_to_delete:
            try:
                await self.storage.delete(path)
            except Exception:  # noqa: BLE001
                logger.warning("Failed to delete stored object", extra={"key": path})

        entity_id = resource.id
        await self.session.delete(resource)

        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="resource",
            entity_id=entity_id,
            details={"purged": True, "versions": len(versions), "force": force or is_super},
        )

    async def purge_many(
        self, public_ids: Sequence[uuid.UUID], *, actor: User, force: bool = False
    ) -> int:
        """Permanently remove multiple resources and every stored version."""
        is_super = getattr(actor, "is_super_admin", False) or any(
            (r.name or "").upper() == "SUPER_ADMIN" for r in (getattr(actor, "roles", []) or [])
        )
        count = 0
        for public_id in public_ids:
            resource = await self.resources.get_by_public_id_full(public_id)
            if resource is None or not await self._resource_reachable(resource, actor):
                continue

            actual = await self.effective_level(resource, actor)
            if not at_least(actual, ResourcePermissionLevel.MANAGE):
                continue

            if not resource.is_deleted and not (is_super or force):
                continue

            # Clean up direct shares and scope permissions
            stmt_perms = delete(ResourcePermission).where(ResourcePermission.resource_id == resource.id)
            await self.session.execute(stmt_perms)
            stmt_shares = delete(SharedResource).where(SharedResource.resource_id == resource.id)
            await self.session.execute(stmt_shares)

            versions = await self.resources.versions_for(resource.id)
            paths_to_delete = {v.path for v in versions if v.path}
            if resource.path:
                paths_to_delete.add(resource.path)

            for path in paths_to_delete:
                try:
                    await self.storage.delete(path)
                except Exception:  # noqa: BLE001
                    logger.warning("Failed to delete stored object", extra={"key": path})

            entity_id = resource.id
            await self.session.delete(resource)

            audit_service.record(
                self.session,
                action=AuditAction.DELETE,
                actor_user_id=actor.id,
                actor_email=actor.email,
                entity_type="resource",
                entity_id=entity_id,
                details={"purged": True, "versions": len(versions), "bulk": True, "force": force or is_super},
            )
            count += 1

        return count

    async def purge_all(
        self, *, actor: User, in_bin_only: bool = True
    ) -> int:
        """Permanently remove all resources in the recycle bin or the entire library.

        When `in_bin_only=False`, this requires Super Admin authority because it
        permanently wipes all active files.
        """
        is_super = getattr(actor, "is_super_admin", False) or any(
            (r.name or "").upper() == "SUPER_ADMIN" for r in (getattr(actor, "roles", []) or [])
        )
        if not in_bin_only and not is_super:
            raise AuthorizationError("Only super administrators can permanently delete all resources.")

        stmt = select(Resource)
        if in_bin_only:
            stmt = stmt.where(Resource.is_deleted.is_(True))

        if not ScopeResolver.is_unrestricted(actor):
            course_scope = await self.scopes.visible_course_ids(actor)
            batch_scope = await self.scopes.visible_batch_ids(actor)
            conds = []
            if course_scope.ids:
                conds.append(Resource.course_id.in_(course_scope.ids))
            if batch_scope.ids:
                conds.append(Resource.batch_id.in_(batch_scope.ids))
            if conds:
                stmt = stmt.where(or_(*conds))
            else:
                return 0

        resources = list((await self.session.execute(stmt)).scalars().all())
        count = 0
        for resource in resources:
            if not is_super:
                actual = await self.effective_level(resource, actor)
                if not at_least(actual, ResourcePermissionLevel.MANAGE):
                    continue

            # Clean up direct shares and permissions
            stmt_perms = delete(ResourcePermission).where(ResourcePermission.resource_id == resource.id)
            await self.session.execute(stmt_perms)
            stmt_shares = delete(SharedResource).where(SharedResource.resource_id == resource.id)
            await self.session.execute(stmt_shares)

            versions = await self.resources.versions_for(resource.id)
            paths_to_delete = {v.path for v in versions if v.path}
            if resource.path:
                paths_to_delete.add(resource.path)

            for path in paths_to_delete:
                try:
                    await self.storage.delete(path)
                except Exception:  # noqa: BLE001
                    logger.warning("Failed to delete stored object", extra={"key": path})

            entity_id = resource.id
            await self.session.delete(resource)

            audit_service.record(
                self.session,
                action=AuditAction.DELETE,
                actor_user_id=actor.id,
                actor_email=actor.email,
                entity_type="resource",
                entity_id=entity_id,
                details={"purged": True, "versions": len(versions), "purge_all": True},
            )
            count += 1

        return count

    async def get_deletion_impact(
        self, public_ids: Sequence[uuid.UUID], *, actor: User
    ) -> DeletionImpactResponse:
        """Inspect dependencies and affected users before permanent deletion."""
        items: list[ResourceImpactItem] = []
        total_direct_shares = 0
        total_grants = 0
        all_affected_users: set[uuid.UUID] = set()

        for public_id in public_ids:
            resource = await self.resources.get_by_public_id_full(public_id)
            if resource is None or not await self._resource_reachable(resource, actor):
                continue

            shares = await self.shares.for_resource(resource.id)
            direct_shares: list[SharedUserInfo] = []
            for s in shares:
                if s.shared_with_user:
                    all_affected_users.add(s.shared_with_user.public_id)
                    direct_shares.append(
                        SharedUserInfo(
                            user_id=s.shared_with_user.public_id,
                            name=display_name(s.shared_with_user),
                            email_or_username=s.shared_with_user.email,
                            role=role_label(s.shared_with_user),
                            level=s.level,
                            shared_by_name=display_name(s.shared_by_user) if s.shared_by_user else None,
                            created_at=s.created_at,
                        )
                    )

            perms = await self.permissions.for_resource(resource.id)
            grants: list[GrantInfo] = []
            for p in perms:
                grants.append(
                    GrantInfo(
                        scope_type=p.scope_type,
                        scope_id=p.scope_id,
                        scope_label=f"{p.scope_type.value} #{p.scope_id}",
                        level=p.level,
                        created_at=p.created_at,
                    )
                )

            total_direct_shares += len(direct_shares)
            total_grants += len(grants)

            items.append(
                ResourceImpactItem(
                    resource_id=resource.public_id,
                    name=resource.name or "Untitled",
                    is_deleted=resource.is_deleted,
                    uploaded_by_username=visible_username(resource.uploader) if resource.uploader else None,
                    course_title=resource.course.title if resource.course else None,
                    batch_code=resource.batch.batch_code if resource.batch else None,
                    direct_shares_count=len(direct_shares),
                    direct_shares=direct_shares,
                    grants_count=len(grants),
                    grants=grants,
                    estimated_affected_users=len(direct_shares),
                )
            )

        return DeletionImpactResponse(
            resources=items,
            total_resources=len(items),
            total_direct_shares=total_direct_shares,
            total_grants=total_grants,
            total_affected_users=len(all_affected_users),
        )



    # -- download ------------------------------------------------------------

    async def resolve_download(
        self, public_id: uuid.UUID, *, actor: User, version: int | None = None
    ) -> tuple[Resource, str, str | None]:
        """Authorise, then return ``(resource, storage_key, presigned_url)``.

        The permission check always happens here, before any URL is minted --
        a presigned link is only ever handed to someone already entitled to
        the file.
        """
        resource = await self.get(public_id, actor=actor)
        await self.require_level(resource, actor, ResourcePermissionLevel.DOWNLOAD)

        key = resource.path
        if version is not None:
            row = await self.resources.version(resource.id, version)
            if row is None:
                raise NotFoundError("Version not found.")
            key = row.path

        if not key:
            raise NotFoundError("This resource has no file.")

        audit_service.record(
            self.session,
            action=AuditAction.DOWNLOAD,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="resource",
            entity_id=resource.id,
            details={"version": version},
        )
        return resource, key, self.storage.presigned_url(key)

    #: Types the console will render in place. Everything else is offered as a
    #: download instead, because previewing it means handing the browser bytes a
    #: stranger uploaded and asking it to interpret them.
    #:
    #: `image/svg+xml` and `text/html` are deliberately **absent**. An SVG is a
    #: document that can carry script, and both execute in this origin if served
    #: inline -- which would turn "preview the file a tutor shared" into session
    #: theft. They are downloadable, just not rendered.
    #:
    #: The two OOXML entries are here for the same reason the two above are
    #: not, read the other way round. **The browser never interprets them**:
    #: the console fetches the bytes with `fetch`, unzips them, parses the XML
    #: with `DOMParser` (which executes nothing) and builds elements from the
    #: result. Nothing is ever handed to `innerHTML`, and the response still
    #: carries `nosniff` and the sandbox CSP, so a crafted `.docx` has nothing
    #: to be interpreted *as*. The legacy binary `.doc` and `.xls` stay out:
    #: they are not ZIPs, the console cannot read them, and admitting a type
    #: nothing can render would turn a clear "download this" into a parse
    #: error.
    PREVIEWABLE_TYPES: frozenset[str] = frozenset({
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "image/png", "image/jpeg", "image/gif", "image/webp", "image/avif", "image/bmp",
        "audio/mpeg", "audio/mp4", "audio/ogg", "audio/wav", "audio/webm",
        "video/mp4", "video/webm", "video/ogg", "video/quicktime",
        "text/plain", "text/markdown", "text/csv", "text/tab-separated-values",
    })

    @classmethod
    def is_previewable(cls, mime_type: str | None) -> bool:
        return (mime_type or "").split(";")[0].strip().lower() in cls.PREVIEWABLE_TYPES

    async def resolve_preview(
        self, public_id: uuid.UUID, *, actor: User
    ) -> tuple[Resource, str]:
        """Authorise a read-in-place and return ``(resource, storage_key)``.

        Requires only VIEW -- that is the whole point of the level existing.
        Returns the key rather than a presigned URL even on R2: a presigned URL
        is a bare link to the object, and handing one to a viewer who may not
        download defeats the distinction this method is enforcing.
        """
        resource = await self.get(public_id, actor=actor)
        await self.require_level(resource, actor, ResourcePermissionLevel.VIEW)

        if not resource.path:
            raise NotFoundError("This resource has no file.")
        if not self.is_previewable(resource.mime_type):
            raise ValidationError(
                "This file type cannot be shown in the browser.",
                details={"mime_type": resource.mime_type},
            )
        return resource, resource.path

    async def resolve_share_link(self, token: str) -> tuple[Resource, str]:
        """Unauthenticated access via a share token.

        The token *is* the authorisation, so it is compared in constant time
        and the lookup is deliberately narrow -- no scoping, no user, and a
        soft-deleted resource is simply not found.
        """
        if not token or len(token) < 16:
            raise NotFoundError("Resource not found.")

        resource = await self.resources.get_by_share_token(token)
        if resource is None or not resource.path:
            raise NotFoundError("Resource not found.")

        if not secrets.compare_digest(resource.share_token or "", token):
            raise NotFoundError("Resource not found.")

        # Checked here as well as at issue time, and that repetition is the
        # point: a file can be restricted *after* a link was handed out, and
        # restricting it has to revoke the link rather than leaving an
        # unauthenticated door open behind the new audience rule.
        if resource.is_restricted:
            raise NotFoundError("Resource not found.")

        return resource, resource.path

    # -- permissions and sharing --------------------------------------------

    async def list_permissions(
        self, *, actor: User, resource_public_id: uuid.UUID | None,
        folder_public_id: uuid.UUID | None
    ) -> list[ResourcePermission]:
        if resource_public_id is not None:
            resource = await self.get(resource_public_id, actor=actor)
            return await self.permissions.for_resource(resource.id)
        if folder_public_id is not None:
            folder = await self.get_folder(folder_public_id, actor=actor)
            return await self.permissions.for_folder(folder.id)
        raise ValidationError("Specify either resource_id or folder_id.")

    async def grant_permission(
        self,
        *,
        actor: User,
        payload: GrantPermissionRequest,
        resource_public_id: uuid.UUID | None,
        folder_public_id: uuid.UUID | None,
    ) -> ResourcePermission:
        resource_id = None
        folder_id = None
        if resource_public_id is not None:
            resource = await self.get(resource_public_id, actor=actor)
            await self.require_level(resource, actor, ResourcePermissionLevel.MANAGE)
            resource_id = resource.id
        elif folder_public_id is not None:
            folder_id = (await self.get_folder(folder_public_id, actor=actor)).id
        else:
            raise ValidationError("Specify either resource_id or folder_id.")

        scope_id, label = await self._resolve_scope(
            payload.scope_type, payload.scope_public_id, actor=actor
        )

        existing = await self.permissions.matching(
            resource_id=resource_id,
            folder_id=folder_id,
            scope_type=payload.scope_type,
            scope_id=scope_id,
        )
        if existing is not None:
            existing.level = payload.level
            row = existing
        else:
            row = ResourcePermission(
                resource_id=resource_id,
                folder_id=folder_id,
                scope_type=payload.scope_type,
                scope_id=scope_id,
                level=payload.level,
                granted_by=actor.id,
                created_at=datetime.now(UTC),
            )
            self.session.add(row)
        await self.session.flush()

        audit_service.record(
            self.session,
            action=AuditAction.PERMISSION_CHANGE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="resource_permission",
            entity_id=row.id,
            details={"scope": f"{payload.scope_type.value}:{label}", "level": payload.level.value},
        )
        return row

    async def revoke_permission(self, permission_id: int, *, actor: User) -> None:
        row = await self.permissions.get(permission_id)
        if row is None:
            raise NotFoundError("Permission not found.")

        # Scope-check through whatever the grant targets, so a permission id
        # from another course's resource is not actionable.
        if row.resource_id is not None:
            target = await self.session.get(Resource, row.resource_id)
            if target is None or not await self._resource_reachable(target, actor):
                raise NotFoundError("Permission not found.")
        elif row.folder_id is not None:
            folder = await self.folders.get_by_id(row.folder_id)
            if folder is None or not await self._folder_reachable(folder, actor):
                raise NotFoundError("Permission not found.")

        await self.session.delete(row)
        audit_service.record(
            self.session,
            action=AuditAction.PERMISSION_CHANGE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="resource_permission",
            entity_id=permission_id,
            details={"revoked": True},
        )

    async def share(
        self,
        public_id: uuid.UUID,
        user_public_ids: Sequence[uuid.UUID],
        *,
        actor: User,
        level: ResourcePermissionLevel = ResourcePermissionLevel.VIEW,
    ) -> list[SharedResource]:
        """Share a file with named people, at a stated level.

        `level` used to be unreachable: the column existed and `effective_level`
        read it, but nothing ever set it, so every share took the server default
        and "let them watch it without keeping a copy" could not be expressed --
        which is the whole of what the brief asks for.

        **Who may receive it is checked here, not in the picker.** Holding
        `resource.update` used to mean a tutor could share any file they
        managed with any user id in the system -- a colleague's whole class,
        or a corporate manager at an unrelated employer -- because the request
        body named the recipients and nothing read it back against a rule.
        `ResourceShareAudience` is that rule, and it is the same one the
        picker is drawn from, so the list a sharer sees and the list the
        server accepts cannot drift apart.
        """
        resource = await self.get(public_id, actor=actor)
        await self.require_level(resource, actor, ResourcePermissionLevel.MANAGE)

        users = await ResourceShareAudience(self.session).resolve(actor, list(user_public_ids))

        if resource.is_restricted:
            # Sharing is how staff material travels, so it is allowed -- but
            # only to people who could have seen the file anyway. Otherwise a
            # share row would exist that `get()` then refuses, which reads to
            # the recipient as the system losing a file.
            blocked = [u for u in users if not self.may_see_restricted(u)]
            if blocked:
                raise ValidationError(
                    "This file is staff-only and cannot be shared with these people.",
                    details={"users": sorted(u.username or str(u.public_id) for u in blocked)},
                )

        for user in users:
            existing = await self.shares.existing(resource_id=resource.id, user_id=user.id)
            if existing is not None:
                # Re-sharing is how a level is changed; skipping would make
                # "share this read-only" silently do nothing to someone who
                # already had it at DOWNLOAD.
                existing.level = level
                continue
            self.session.add(
                SharedResource(
                    resource_id=resource.id,
                    shared_with_user_id=user.id,
                    shared_by_user_id=actor.id,
                    level=level,
                    created_at=datetime.now(UTC),
                )
            )
        await self.session.flush()

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="resource",
            entity_id=resource.id,
            details={
                # The audit trail records *who*, by stable id, not by login
                # name -- which in this deployment is an email address, and
                # the one thing a share must not copy into another table.
                "shared_with": sorted(str(u.public_id) for u in users),
                "level": level.value,
            },
        )
        return await self.shares.for_resource(resource.id)

    async def share_many(
        self,
        resource_public_ids: Sequence[uuid.UUID],
        user_public_ids: Sequence[uuid.UUID],
        *,
        actor: User,
        level: ResourcePermissionLevel = ResourcePermissionLevel.VIEW,
    ) -> list[SharedResource]:
        """Hand several files to several people in one act.

        All or nothing, and that is the point: "share this week's material
        with the class" is one decision, and a partial result -- four of six
        files delivered, with no indication which two were refused -- leaves
        the sharer believing they did something they did not. Every file is
        authorised and every recipient resolved before the first row is
        written, so the refusal arrives before anything has happened.

        One pass over the audience rather than one per file: the answer cannot
        change within a request, and asking six times is six times the work for
        the same answer.
        """
        if not resource_public_ids:
            raise ValidationError("Choose at least one file to share.")

        users = await ResourceShareAudience(self.session).resolve(actor, list(user_public_ids))

        resources: list[Resource] = []
        for resource_public_id in dict.fromkeys(resource_public_ids):
            resource = await self.get(resource_public_id, actor=actor)
            await self.require_level(resource, actor, ResourcePermissionLevel.MANAGE)
            resources.append(resource)

        restricted = [r for r in resources if r.is_restricted]
        if restricted:
            blocked = [u for u in users if not self.may_see_restricted(u)]
            if blocked:
                raise ValidationError(
                    "Some of these files are staff-only and cannot be shared with "
                    "these people.",
                    details={"files": sorted(r.name or str(r.public_id) for r in restricted)},
                )

        written: list[SharedResource] = []
        for resource in resources:
            for user in users:
                existing = await self.shares.existing(resource_id=resource.id, user_id=user.id)
                if existing is not None:
                    existing.level = level
                    continue
                row = SharedResource(
                    resource_id=resource.id,
                    shared_with_user_id=user.id,
                    shared_by_user_id=actor.id,
                    level=level,
                    created_at=datetime.now(UTC),
                )
                self.session.add(row)
                written.append(row)
        await self.session.flush()

        for resource in resources:
            audit_service.record(
                self.session,
                action=AuditAction.UPDATE,
                actor_user_id=actor.id,
                actor_email=actor.email,
                entity_type="resource",
                entity_id=resource.id,
                details={
                    "shared_with": sorted(str(u.public_id) for u in users),
                    "level": level.value,
                },
            )

        rows: list[SharedResource] = []
        for resource in resources:
            rows.extend(await self.shares.for_resource(resource.id))
        return rows

    async def unshare(
        self, public_id: uuid.UUID, user_public_id: uuid.UUID, *, actor: User
    ) -> None:
        resource = await self.get(public_id, actor=actor)
        user = await self._load_user(user_public_id)

        row = await self.shares.existing(resource_id=resource.id, user_id=user.id)
        if row is None:
            raise NotFoundError("Share not found.")

        await self.session.delete(row)
        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="resource",
            entity_id=resource.id,
            details={"unshared": user.username},
        )

    async def set_share_link(
        self, public_id: uuid.UUID, *, enabled: bool, actor: User
    ) -> Resource:
        """Issue or revoke a public, unauthenticated download link."""
        resource = await self.get(public_id, actor=actor)
        await self.require_level(resource, actor, ResourcePermissionLevel.MANAGE)

        if enabled and resource.is_restricted:
            # A link that needs no sign-in cannot respect an audience rule --
            # anyone holding the string is outside every check this platform
            # makes. Refusing is the only honest answer; the alternative is a
            # control that appears to work and silently does not.
            raise ValidationError(
                "This file is staff-only, so it cannot have a public link. "
                "Share it with named people instead."
            )

        # 256 bits: the token is the only thing standing between the file and
        # anyone on the internet, so it has to be unguessable rather than
        # merely unique.
        resource.share_token = secrets.token_urlsafe(32) if enabled else None
        resource.modified_by = actor.id

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="resource",
            entity_id=resource.id,
            details={"share_link": "issued" if enabled else "revoked"},
        )
        return resource

    # -- visibility ----------------------------------------------------------

    async def effective_level(
        self, resource: Resource, actor: User
    ) -> ResourcePermissionLevel | None:
        """What `actor` may do with `resource`. `None` means no access at all.

        Three routes, and the most capable of them wins:

        1. **Unrestricted** (Super Admin) -- MANAGE, always.
        2. **Owning the space.** A file inside a course or batch the caller
           already administers takes its level from their *global* resource
           permissions: `resource.delete` -> MANAGE, `resource.update` -> EDIT,
           otherwise VIEW. This is what makes a tutor able to manage their own
           course's materials without a grant being written for every file.
        3. **An explicit grant or share** on this one file. Foreign content is
           governed only by what was actually granted, so holding
           `resource.delete` globally does not let staff delete a file that was
           shared with them read-only -- the old behaviour, and the reason the
           level column existed but changed nothing.
        """
        if ScopeResolver.is_unrestricted(actor):
            return ResourcePermissionLevel.MANAGE

        from backend.api.deps import resolve_permissions
        from backend.core.permissions import Action, Module, perm

        held = resolve_permissions(actor)
        if perm(Module.RESOURCE, Action.READ) not in held:
            return None

        # -- route 2: the caller administers the space the file sits in
        owned: ResourcePermissionLevel | None = None
        course_scope = await self.scopes.visible_course_ids(actor)
        batch_scope = await self.scopes.visible_batch_ids(actor)
        in_own_space = (
            resource.course_id is not None and course_scope.allows(resource.course_id)
        ) or (resource.batch_id is not None and batch_scope.allows(resource.batch_id))
        if in_own_space:
            if perm(Module.RESOURCE, Action.DELETE) in held:
                owned = ResourcePermissionLevel.MANAGE
            elif perm(Module.RESOURCE, Action.UPDATE) in held:
                owned = ResourcePermissionLevel.EDIT
            else:
                owned = ResourcePermissionLevel.VIEW

        # -- route 3: an explicit grant against one of the caller's scopes
        pairs: list[tuple[str, int]] = [(ResourceScopeType.USER.value, actor.id)]
        pairs += [(ResourceScopeType.COURSE.value, cid) for cid in course_scope.ids]
        pairs += [(ResourceScopeType.BATCH.value, bid) for bid in batch_scope.ids]
        session_scope = await self.scopes.visible_session_ids(actor)
        pairs += [(ResourceScopeType.SESSION.value, sid) for sid in session_scope.ids]
        granted = await self.permissions.levels_for_resource(resource.id, pairs)

        # -- route 3b: a direct person-to-person share
        share = await self.shares.existing(resource_id=resource.id, user_id=actor.id)
        share_level = share.level if share is not None else None

        return highest(owned, share_level, *granted)

    async def require_level(
        self, resource: Resource, actor: User, level: ResourcePermissionLevel
    ) -> None:
        """Refuse unless the caller reaches `level` on this file.

        `AuthorizationError`, not `NotFoundError`: by the time this runs the
        caller has already been shown the file exists -- they listed it, or they
        opened it. Pretending it vanished when they press Download would be
        confusing rather than protective. Reachability, which *is* the secret,
        is still answered with a 404 by `get()`.
        """
        actual = await self.effective_level(resource, actor)
        if not at_least(actual, level):
            raise AuthorizationError(
                f"You have {actual.value.lower() if actual else 'no'} access to this file; "
                f"{level.value.lower()} is required."
            )

    async def _explicitly_granted_resource_ids(self, actor: User) -> set[int]:
        """Resources reachable by grant or share rather than by course/batch."""
        if ScopeResolver.is_unrestricted(actor):
            return set()

        pairs: list[tuple[str, int]] = [(ResourceScopeType.USER.value, actor.id)]

        course_scope = await self.scopes.visible_course_ids(actor)
        pairs += [(ResourceScopeType.COURSE.value, cid) for cid in course_scope.ids]
        batch_scope = await self.scopes.visible_batch_ids(actor)
        pairs += [(ResourceScopeType.BATCH.value, bid) for bid in batch_scope.ids]
        session_scope = await self.scopes.visible_session_ids(actor)
        pairs += [(ResourceScopeType.SESSION.value, sid) for sid in session_scope.ids]

        granted = await self.permissions.resource_ids_for_scopes(pairs)
        shared = await self.shares.resource_ids_shared_with(actor.id)
        return granted | shared

    async def _resource_reachable(self, resource: Resource, actor: User) -> bool:
        if ScopeResolver.is_unrestricted(actor):
            return True

        course_scope = await self.scopes.visible_course_ids(actor)
        if resource.course_id is not None and course_scope.allows(resource.course_id):
            return True

        batch_scope = await self.scopes.visible_batch_ids(actor)
        if resource.batch_id is not None and batch_scope.allows(resource.batch_id):
            return True

        # Third route: an explicit grant or a direct share. This is what lets
        # one file be handed to someone outside the course without opening
        # the whole course to them.
        return resource.id in await self._explicitly_granted_resource_ids(actor)

    async def _folder_reachable(self, folder: ResourceFolder, actor: User) -> bool:
        if ScopeResolver.is_unrestricted(actor):
            return True

        course_scope = await self.scopes.visible_course_ids(actor)
        if folder.course_id is not None and course_scope.allows(folder.course_id):
            return True

        batch_scope = await self.scopes.visible_batch_ids(actor)
        if folder.batch_id is not None and batch_scope.allows(folder.batch_id):
            return True
        return False

    # -- helpers -------------------------------------------------------------

    async def _resolve_scope(
        self, scope_type: ResourceScopeType, public_id: uuid.UUID, *, actor: User
    ) -> tuple[int, str]:
        """Turn a scope's public_id into its internal id, checking the actor
        can actually see the thing they are granting against."""
        if scope_type is ResourceScopeType.COURSE:
            course = await self.courses.get(public_id, actor=actor)
            return course.id, course.title
        if scope_type is ResourceScopeType.BATCH:
            batch = await self.batches.get(public_id, actor=actor)
            return batch.id, batch.batch_code
        if scope_type is ResourceScopeType.SESSION:
            stmt = select(BatchSession).where(BatchSession.public_id == public_id)
            row = (await self.session.execute(stmt)).scalar_one_or_none()
            if row is None:
                raise NotFoundError("Session not found.")
            scope = await self.scopes.visible_session_ids(actor)
            if not scope.allows(row.id):
                raise NotFoundError("Session not found.")
            return row.id, str(row.public_id)
        user = await self._load_user(public_id)
        return user.id, user.username

    async def _can_manage(self, actor: User) -> bool:
        from backend.api.deps import resolve_permissions
        from backend.core.permissions import Action, Module, perm

        return perm(Module.RESOURCE, Action.DELETE) in resolve_permissions(actor)

    async def _load_user(self, public_id: uuid.UUID) -> User:
        stmt = select(User).where(User.public_id == public_id)
        user = (await self.session.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise NotFoundError("User not found.")
        return user

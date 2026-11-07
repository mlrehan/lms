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
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Sequence

from fastapi import UploadFile
from sqlalchemy import delete, literal_column, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload


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
    SharedFolder,
    SharedResource,
)
from backend.repositories.resource import (
    FolderRepository,
    ResourcePermissionRepository,
    ResourceRepository,
    SharedFolderRepository,
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
from backend.services.scope import Scope, ScopeResolver
from backend.storage import get_storage
from backend.storage.base import build_key
from backend.utils.enums import ResourcePermissionLevel, ResourceScopeType, ResourceType


logger = get_logger(__name__)


@dataclass
class ShareOutcome:
    """What a share did, for the response and the log."""

    files: int
    folders: int
    people: int
    created: int = 0
    updated: int = 0
    unchanged: int = 0

    def add(self, counts: tuple[int, int, int]) -> None:
        self.created += counts[0]
        self.updated += counts[1]
        self.unchanged += counts[2]

_UNSET = object()

#: Holding this is what separates staff from the audience a restricted file is
#: kept away from. Resolved as a permission rather than a role name so an
#: institution can add a registrar or an external examiner later.
_VIEW_RESTRICTED = _perm(_Mod.RESOURCE, _Act.VIEW_RESTRICTED)

#: Files a person reaches through shared folders that the library listing
#: will consider. A listing is paged anyway; this bounds the IN-list the
#: search is handed, not what the person may open.
MAX_LISTED_FROM_FOLDERS = 10_000
#: Levels a share may grant. EDIT and MANAGE are what owning a course's space
#: confers; handing them to a person by share would let a student delete a
#: tutor's material or re-share it onward.
SHAREABLE_LEVELS = (ResourcePermissionLevel.VIEW, ResourcePermissionLevel.DOWNLOAD)


class ResourceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.resources = ResourceRepository(session)
        self.folders = FolderRepository(session)
        self.permissions = ResourcePermissionRepository(session)
        self.shares = SharedResourceRepository(session)
        self.shared_folders = SharedFolderRepository(session)
        self._scope_cache: dict[int, tuple[Scope, Scope, Scope]] = {}
        self._shared_folder_cache: dict[int, set[int]] = {}
        self._batch_course: dict[int, int | None] = {}
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
        # Skipping the recycle bin is a Super Admin's act and must be asked for
        # (`force`). `force` from anyone else is ignored: it arrives in the
        # request, so honouring it for every holder of `resource.delete` made
        # the two-step, recoverable deletion a one-step irreversible one.
        if not resource.is_deleted and not (is_super and force):
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
            details={"purged": True, "versions": len(versions), "force": bool(force and is_super)},
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

            if not resource.is_deleted and not (is_super and force):
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
                details={"purged": True, "versions": len(versions), "bulk": True, "force": bool(force and is_super)},
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
        """Share one file with named people, at a stated level.

        The same path as `share_many`, so one file and twelve are authorised and
        written by the same rule. Returns the file's whole share list, which is
        what the file's own panel draws.
        """
        resource = await self.get(public_id, actor=actor)
        await self.share_many([public_id], user_public_ids, actor=actor, level=level)
        return await self.shares.for_resource(resource.id)

    async def share_many(
        self,
        resource_public_ids: Sequence[uuid.UUID],
        user_public_ids: Sequence[uuid.UUID],
        *,
        actor: User,
        level: ResourcePermissionLevel = ResourcePermissionLevel.VIEW,
        folder_public_ids: Sequence[uuid.UUID] = (),
    ) -> ShareOutcome:
        """Hand files and folders to people in one act.

        **All or nothing.** "Share this week's material with the class" is one
        decision, and a partial result leaves the sharer believing they did
        something they did not. Every file and folder is authorised and every
        recipient resolved before anything is written, so a refusal arrives
        before anything has happened.

        **Who may receive it is checked here, not in the picker.**
        `ResourceShareAudience` is the rule, and it is the same one the picker
        is drawn from, so the list a sharer sees and the list the server accepts
        cannot drift apart.

        **Duplicates are the database's to refuse.** `UNIQUE (resource_id,
        shared_with_user_id)` -- and the same on folders -- is the guard, and the
        write is one `INSERT ... ON CONFLICT` per table. A share that already
        exists at this level writes nothing and raises nothing; one at another
        level has its level changed, because re-sharing is how a level is
        changed. That is also what makes a retry safe: a request the gateway
        gave up on, sent again, lands on the rows the first one wrote. There is
        no check-then-insert to race.

        **Cost is flat in the number of files.** Scopes are resolved once,
        files and folders are loaded in one query each, and their levels are
        computed in bulk. The previous version authorised file by file and read
        every file's whole share list back, which is how twelve files to one
        student came to cost several thousand queries and the gateway timeout.
        """
        if level not in SHAREABLE_LEVELS:
            raise ValidationError("A share may grant View or Download, nothing more.")

        file_ids = list(dict.fromkeys(resource_public_ids))
        folder_ids = list(dict.fromkeys(folder_public_ids))
        if not file_ids and not folder_ids:
            raise ValidationError("Choose at least one file or folder to share.")

        users = await ResourceShareAudience(self.session).resolve(actor, list(user_public_ids))

        resources = await self._authorise_files_for_sharing(file_ids, actor)
        folders = await self._authorise_folders_for_sharing(folder_ids, actor)

        restricted = [r for r in resources if r.is_restricted]
        if restricted:
            # Sharing is how staff material travels, so it is allowed -- but
            # only to people who could have seen the file anyway. Otherwise a
            # share row would exist that `get()` then refuses, which reads to
            # the recipient as the system losing a file. (A folder needs no
            # such check: staff-only files inside it are withheld from a
            # non-staff recipient when they are read, by the same rule.)
            blocked = [u for u in users if not self.may_see_restricted(u)]
            if blocked:
                raise ValidationError(
                    "Some of these files are staff-only and cannot be shared with "
                    "these people.",
                    details={"files": sorted(r.name or str(r.public_id) for r in restricted)},
                )

        now = datetime.now(UTC)
        outcome = ShareOutcome(files=len(resources), folders=len(folders), people=len(users))
        if resources:
            outcome.add(
                await self._upsert_shares(
                    SharedResource,
                    "resource_id",
                    "uq_shared_resources_resource_user",
                    [
                        {
                            "resource_id": r.id,
                            "shared_with_user_id": u.id,
                            "shared_by_user_id": actor.id,
                            "level": level,
                            "created_at": now,
                        }
                        for r in resources
                        for u in users
                    ],
                )
            )
        if folders:
            outcome.add(
                await self._upsert_shares(
                    SharedFolder,
                    "folder_id",
                    "uq_shared_folders_folder_user",
                    [
                        {
                            "folder_id": f.id,
                            "shared_with_user_id": u.id,
                            "shared_by_user_id": actor.id,
                            "level": level,
                            "created_at": now,
                        }
                        for f in folders
                        for u in users
                    ],
                )
            )

        # The audit trail records *who*, by stable id, not by login name --
        # which in this deployment is an email address, and the one thing a
        # share must not copy into another table.
        recipients = sorted(str(u.public_id) for u in users)
        for resource in resources:
            audit_service.record(
                self.session,
                action=AuditAction.UPDATE,
                actor_user_id=actor.id,
                actor_email=actor.email,
                entity_type="resource",
                entity_id=resource.id,
                details={"shared_with": recipients, "level": level.value},
            )
        for folder in folders:
            audit_service.record(
                self.session,
                action=AuditAction.UPDATE,
                actor_user_id=actor.id,
                actor_email=actor.email,
                entity_type="resource_folder",
                entity_id=folder.id,
                details={"shared_with": recipients, "level": level.value},
            )
        logger.info(
            "resources.shared",
            # Prefixed: `created` is a reserved LogRecord attribute, and the
            # logging module refuses to let `extra` overwrite one.
            extra={
                "share_files": outcome.files,
                "share_folders": outcome.folders,
                "share_people": outcome.people,
                "share_created": outcome.created,
                "share_updated": outcome.updated,
                "share_unchanged": outcome.unchanged,
            },
        )
        return outcome

    async def _authorise_files_for_sharing(
        self, public_ids: list[uuid.UUID], actor: User
    ) -> list[Resource]:
        """Load and authorise every file, in bulk, by `get()`'s rules plus MANAGE.

        The refusals keep `get()`'s shape: a file the caller cannot reach, or a
        staff-only one they may not see, is "not found" -- which file is missing
        is not told, because that would confirm which of the others exist. A
        file they can see but not manage is a 403, as before.
        """
        if not public_ids:
            return []
        resources = await self.resources.by_public_ids(public_ids)
        if len(resources) != len(public_ids):
            raise NotFoundError("Resource not found.")
        for resource in resources:
            if resource.is_restricted and not self.may_see_restricted(actor):
                raise NotFoundError("Resource not found.")
        levels = await self.effective_levels(resources, actor)
        for resource in resources:
            actual = levels.get(resource.id)
            if actual is None:
                raise NotFoundError("Resource not found.")
            if not at_least(actual, ResourcePermissionLevel.MANAGE):
                raise AuthorizationError(
                    f"You have {actual.value.lower()} access to {resource.name}; "
                    "manage is required to share it."
                )
        deleted = [r for r in resources if r.is_deleted]
        if deleted:
            # Its audience would get "not found" for it: `get()` hides a deleted
            # file from everyone who cannot restore it.
            raise ValidationError(
                "Files in the recycle bin cannot be shared. Restore them first.",
                details={"files": sorted(r.name or str(r.public_id) for r in deleted)},
            )
        return resources

    async def _authorise_folders_for_sharing(
        self, public_ids: list[uuid.UUID], actor: User
    ) -> list[ResourceFolder]:
        if not public_ids:
            return []
        stmt = select(ResourceFolder).options(raiseload("*")).where(
            ResourceFolder.public_id.in_(public_ids)
        )
        folders = list((await self.session.execute(stmt)).scalars().all())
        if len(folders) != len(public_ids):
            raise NotFoundError("Folder not found.")
        for folder in folders:
            actual = await self.folder_level(folder, actor)
            if actual is None:
                raise NotFoundError("Folder not found.")
            if not at_least(actual, ResourcePermissionLevel.MANAGE):
                raise AuthorizationError(
                    f"You have {actual.value.lower()} access to {folder.name}; "
                    "manage is required to share it."
                )
        return folders

    async def _upsert_shares(
        self, model: type, target: str, constraint: str, rows: list[dict]
    ) -> tuple[int, int, int]:
        """Write share rows; ``(created, updated, unchanged)``.

        ``RETURNING`` yields a row for every insert and every *changed* update,
        and ``xmax = 0`` tells the two apart (a freshly inserted tuple has no
        deleting transaction). A row already at this level matches the
        ``WHERE`` and returns nothing, which is the "unchanged" count.
        """
        if not rows:
            return 0, 0, 0
        # **One global order, or two shares deadlock.** Postgres takes a row
        # lock per conflicting row, in the order the VALUES list gives them.
        # Two tutors sharing overlapping files with overlapping students, in
        # different orders, each end up holding a row the other is waiting
        # for -- found by the load test, where one in ~150 bursts died with
        # `deadlock detected`. Sorted by the conflict key, every transaction
        # locks in the same order, so one simply waits for the other.
        rows = sorted(rows, key=lambda row: (row[target], row["shared_with_user_id"]))
        stmt = pg_insert(model).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint=constraint,
            set_={"level": stmt.excluded.level},
            where=model.level.is_distinct_from(stmt.excluded.level),
        ).returning(literal_column("xmax = 0").label("inserted"))
        written = (await self.session.execute(stmt)).scalars().all()
        created = sum(1 for inserted in written if inserted)
        updated = len(written) - created
        return created, updated, len(rows) - len(written)

    async def unshare_folder(
        self, folder_public_id: uuid.UUID, user_public_id: uuid.UUID, *, actor: User
    ) -> None:
        """Withdraw a folder share.

        Removes exactly what that share granted. A file inside the folder that
        was also shared with the person directly is a separate row, and so is a
        share of another folder above or below this one; both survive.
        """
        folder = await self.get_folder(folder_public_id, actor=actor)
        if not at_least(await self.folder_level(folder, actor), ResourcePermissionLevel.MANAGE):
            raise AuthorizationError("Manage access to this folder is required.")
        user = await self._load_user(user_public_id)
        row = await self.shared_folders.existing(folder_id=folder.id, user_id=user.id)
        if row is None:
            raise NotFoundError("Share not found.")
        await self.session.delete(row)
        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="resource_folder",
            entity_id=folder.id,
            details={"unshared": str(user.public_id)},
        )

    async def folder_shares(self, folder_public_id: uuid.UUID, *, actor: User) -> list[SharedFolder]:
        """Who this folder has been shared with -- for the people who may change it."""
        folder = await self.get_folder(folder_public_id, actor=actor)
        if not at_least(await self.folder_level(folder, actor), ResourcePermissionLevel.MANAGE):
            raise AuthorizationError("Manage access to this folder is required.")
        return await self.shared_folders.for_folder(folder.id)

    # -- what has been shared with me ----------------------------------------

    async def shared_library(
        self, actor: User
    ) -> tuple[list[SharedFolder], list[SharedResource], dict[int, tuple[uuid.UUID, str]]]:
        """Folders and files shared with the caller, and the courses they belong to.

        The course is the file's or folder's own -- its ``course_id``, or its
        batch's course -- and never anything the sharer said. Returned as a map
        from internal course id so the API can group without a query per row.
        Staff-only and deleted files are left out here for the same reason
        `get()` refuses them: listing a file that will not open is a broken
        promise.
        """
        folders = await self.shared_folders.shared_with(actor.id)
        files = [
            s
            for s in await self.shares.shared_with(actor.id)
            if s.resource is not None
            and not s.resource.is_deleted
            and (not s.resource.is_restricted or self.may_see_restricted(actor))
        ]
        courses = await self.course_labels(
            [(f.folder.course_id, f.folder.batch_id) for f in folders]
            + [(s.resource.course_id, s.resource.batch_id) for s in files]
        )
        return folders, files, courses

    async def shared_folder_contents(
        self, folder_public_id: uuid.UUID, *, actor: User
    ) -> tuple[ResourceFolder, ResourcePermissionLevel, list[ResourceFolder],
               list[ResourceFolder], list[tuple[Resource, ResourcePermissionLevel]]]:
        """One folder inside a tree shared with the caller.

        Returns ``(folder, level, path, child_folders, files)``. Reachable only
        through a share: this is the recipient's view, and "inside a course I
        administer" is answered by the library, not here. ``path`` starts at
        the shared folder and never above it -- the folders above a share are
        somebody else's, and their names are not part of what was handed over.
        """
        stmt = select(ResourceFolder).options(raiseload("*")).where(
            ResourceFolder.public_id == folder_public_id
        )
        folder = (await self.session.execute(stmt)).scalar_one_or_none()
        if folder is None:
            raise NotFoundError("Folder not found.")
        through = (await self.shared_folders.levels_through_tree({folder.id}, actor.id)).get(
            folder.id
        )
        level = highest(*(through or []))
        if level is None:
            raise NotFoundError("Folder not found.")

        roots = {row.folder_id for row in await self.shared_folders.shared_with(actor.id)}
        path: list[ResourceFolder] = []
        for ancestor in reversed(await self.folders.ancestors(folder)):
            path.append(ancestor)
            if ancestor.id in roots:
                break
        path.reverse()

        children_stmt = (
            select(ResourceFolder)
            .options(raiseload("*"))
            .where(ResourceFolder.parent_folder_id == folder.id)
            .order_by(ResourceFolder.name)
        )
        children = list((await self.session.execute(children_stmt)).scalars().all())

        files = await self.resources.live_in_folder(
            folder.id, include_restricted=self.may_see_restricted(actor)
        )
        levels = await self.effective_levels(files, actor)
        return (
            folder,
            level,
            path,
            children,
            [(f, levels.get(f.id) or level) for f in files],
        )

    async def course_labels(
        self, anchors: Sequence[tuple[int | None, int | None]]
    ) -> dict[int, tuple[uuid.UUID, str]]:
        """``{course_id: (public_id, title)}`` for these (course, batch) anchors.

        Two queries for any number of rows: one to turn batch-only anchors into
        their course, one for the titles.
        """
        course_ids = {c for c, _ in anchors if c is not None}
        batch_only = {b for c, b in anchors if c is None and b is not None}
        if batch_only:
            rows = await self.session.execute(
                select(Batch.id, Batch.course_id).where(Batch.id.in_(batch_only))
            )
            self._batch_course = {bid: cid for bid, cid in rows.all()}
            course_ids |= {c for c in self._batch_course.values() if c is not None}
        if not course_ids:
            return {}
        rows = await self.session.execute(
            select(Course.id, Course.public_id, Course.title).where(Course.id.in_(course_ids))
        )
        return {cid: (pid, title) for cid, pid, title in rows.all()}

    def course_of(self, course_id: int | None, batch_id: int | None) -> int | None:
        """The course a file or folder belongs to, after `_course_labels`."""
        if course_id is not None:
            return course_id
        if batch_id is not None:
            return self._batch_course.get(batch_id)
        return None

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
        return (await self.effective_levels([resource], actor))[resource.id]

    async def effective_levels(
        self, resources: Sequence[Resource], actor: User
    ) -> dict[int, ResourcePermissionLevel | None]:
        """`effective_level` for many files, at the cost of one.

        The caller's scopes are resolved once and every per-file lookup is a
        single query over all the files. Asking file by file is what made a
        twelve-file share issue several thousand queries: each file re-derived
        the same course, batch and session scopes from scratch.

        Route 4 sits beside the other three: **a folder shared with the
        caller**, on the file's folder or any folder above it. It is computed
        from the tree at read time, so a file moved out of a shared folder
        stops being covered the moment it moves.
        """
        if not resources:
            return {}
        if ScopeResolver.is_unrestricted(actor):
            return {r.id: ResourcePermissionLevel.MANAGE for r in resources}

        from backend.api.deps import resolve_permissions
        from backend.core.permissions import Action, Module, perm

        held = resolve_permissions(actor)
        explicit = await self._explicit_levels(resources, actor)
        if perm(Module.RESOURCE, Action.READ) not in held:
            # **A share is reachable by the person it was shared with, whatever
            # their role.** Guardians and corporate managers hold no
            # `resource.*` permission, and they are in the share audience by
            # design -- so this used to answer None for everything handed to
            # them, and a file "shared with a guardian" could never be opened.
            # Only the space route below needs the permission: that is the one
            # that would open a ward's whole course.
            return {r.id: highest(*explicit.get(r.id, [])) for r in resources}

        # -- route 2: the baseline for files in a space the caller administers
        if perm(Module.RESOURCE, Action.DELETE) in held:
            baseline = ResourcePermissionLevel.MANAGE
        elif perm(Module.RESOURCE, Action.UPDATE) in held:
            baseline = ResourcePermissionLevel.EDIT
        else:
            baseline = ResourcePermissionLevel.VIEW

        course_scope, batch_scope, _ = await self._scopes(actor)

        found: dict[int, ResourcePermissionLevel | None] = {}
        for resource in resources:
            in_own_space = (
                resource.course_id is not None and course_scope.allows(resource.course_id)
            ) or (resource.batch_id is not None and batch_scope.allows(resource.batch_id))
            found[resource.id] = highest(
                baseline if in_own_space else None, *explicit.get(resource.id, [])
            )
        return found

    async def _scopes(self, actor: User) -> tuple[Scope, Scope, Scope]:
        """The caller's course, batch and session scopes, resolved once.

        A service instance lives for one request, and nothing in this module
        changes enrolments or teaching assignments, so the answer cannot move
        under it. Without this, listing a library of forty folders resolved the
        same scopes forty times over.
        """
        cached = self._scope_cache.get(actor.id)
        if cached is None:
            cached = (
                await self.scopes.visible_course_ids(actor),
                await self.scopes.visible_batch_ids(actor),
                await self.scopes.visible_session_ids(actor),
            )
            self._scope_cache[actor.id] = cached
        return cached

    async def _grant_pairs(self, actor: User) -> list[tuple[str, int]]:
        course_scope, batch_scope, session_scope = await self._scopes(actor)
        pairs: list[tuple[str, int]] = [(ResourceScopeType.USER.value, actor.id)]
        pairs += [(ResourceScopeType.COURSE.value, cid) for cid in course_scope.ids]
        pairs += [(ResourceScopeType.BATCH.value, bid) for bid in batch_scope.ids]
        pairs += [(ResourceScopeType.SESSION.value, sid) for sid in session_scope.ids]
        return pairs

    async def _explicit_levels(
        self, resources: Sequence[Resource], actor: User
    ) -> dict[int, list[ResourcePermissionLevel]]:
        """Levels from grants, direct shares and shared folders, per file.

        Three queries whatever the number of files: these are the routes that
        reach a file *outside* the caller's own courses, and the ones that let
        one file be handed over without opening a whole course.
        """
        ids = [r.id for r in resources]
        granted = await self.permissions.levels_for_resources(ids, await self._grant_pairs(actor))
        shared = await self.shares.levels_for_user(ids, actor.id)
        through_folders = await self.shared_folders.levels_through_tree(
            {r.folder_id for r in resources if r.folder_id is not None}, actor.id
        )
        found: dict[int, list[ResourcePermissionLevel]] = {}
        for resource in resources:
            levels = list(granted.get(resource.id, []))
            if resource.id in shared:
                levels.append(shared[resource.id])
            if resource.folder_id is not None:
                levels += through_folders.get(resource.folder_id, [])
            if levels:
                found[resource.id] = levels
        return found

    async def folder_level(
        self, folder: ResourceFolder, actor: User
    ) -> ResourcePermissionLevel | None:
        """What `actor` may do with a folder and everything beneath it.

        The same routes as a file, minus grants (folder grants are recorded by
        `grant_permission` but have never been enforced anywhere, and turning
        them on silently is a different change): owning the space, or a share
        of this folder or one above it.
        """
        if ScopeResolver.is_unrestricted(actor):
            return ResourcePermissionLevel.MANAGE

        from backend.api.deps import resolve_permissions
        from backend.core.permissions import Action, Module, perm

        held = resolve_permissions(actor)
        owned: ResourcePermissionLevel | None = None
        course_scope, batch_scope, _ = await self._scopes(actor)
        if perm(Module.RESOURCE, Action.READ) in held and (
            (folder.course_id is not None and course_scope.allows(folder.course_id))
            or (folder.batch_id is not None and batch_scope.allows(folder.batch_id))
        ):
            if perm(Module.RESOURCE, Action.DELETE) in held:
                owned = ResourcePermissionLevel.MANAGE
            elif perm(Module.RESOURCE, Action.UPDATE) in held:
                owned = ResourcePermissionLevel.EDIT
            else:
                owned = ResourcePermissionLevel.VIEW

        through = await self.shared_folders.levels_through_tree({folder.id}, actor.id)
        return highest(owned, *through.get(folder.id, []))

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

        granted = await self.permissions.resource_ids_for_scopes(await self._grant_pairs(actor))
        shared = await self.shares.resource_ids_shared_with(actor.id)
        in_shared_folders = await self.resources.ids_in_folders(
            await self._shared_folder_ids(actor), limit=MAX_LISTED_FROM_FOLDERS
        )
        return granted | shared | set(in_shared_folders)

    async def _shared_folder_ids(self, actor: User) -> set[int]:
        """Every folder inside a tree shared with the caller. Cached per request."""
        if actor.id not in self._shared_folder_cache:
            self._shared_folder_cache[actor.id] = await self.shared_folders.reachable_folder_ids(
                actor.id
            )
        return self._shared_folder_cache[actor.id]

    async def _resource_reachable(self, resource: Resource, actor: User) -> bool:
        if ScopeResolver.is_unrestricted(actor):
            return True

        if self._may_read_spaces(actor):
            course_scope, batch_scope, _ = await self._scopes(actor)
            if resource.course_id is not None and course_scope.allows(resource.course_id):
                return True
            if resource.batch_id is not None and batch_scope.allows(resource.batch_id):
                return True

        # Third route: an explicit grant, a direct share, or a folder shared
        # with the caller that this file sits inside. This is what lets one
        # file -- or one folder of them -- be handed to someone outside the
        # course without opening the whole course to them.
        return bool((await self._explicit_levels([resource], actor)).get(resource.id))

    async def _folder_reachable(self, folder: ResourceFolder, actor: User) -> bool:
        if ScopeResolver.is_unrestricted(actor):
            return True

        if self._may_read_spaces(actor):
            course_scope, batch_scope, _ = await self._scopes(actor)
            if folder.course_id is not None and course_scope.allows(folder.course_id):
                return True
            if folder.batch_id is not None and batch_scope.allows(folder.batch_id):
                return True
        return folder.id in await self._shared_folder_ids(actor)

    @staticmethod
    def _may_read_spaces(actor: User) -> bool:
        """May this person read the materials of the courses they can see?

        The routes that read files and the shared-with-me screens are open to
        any signed-in person, because a share is reachable by whoever it was
        shared with. This is what keeps that from widening: a guardian can see
        their ward's batches, and without this check would reach every file in
        those courses. Only a holder of `resource.read` reaches files through a
        course or batch; everyone else reaches exactly what was shared.
        """
        return _perm(_Mod.RESOURCE, _Act.READ) in ScopeResolver.held_permissions(actor)

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

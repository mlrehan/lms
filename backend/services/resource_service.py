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
from sqlalchemy import select
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
from backend.schemas.base import PageParams
from backend.schemas.resource import (
    FolderCreateRequest,
    FolderUpdateRequest,
    GrantPermissionRequest,
    ResourceUpdateRequest,
)
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.batch_service import BatchService
from backend.services.course_service import CourseService
from backend.services.scope import ScopeResolver
from backend.storage import get_storage
from backend.storage.base import build_key
from backend.utils.enums import ResourcePermissionLevel, ResourceScopeType, ResourceType

logger = get_logger(__name__)

_UNSET = object()


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

        return await self.folders.children_of(parent_id, course_id=course_id, batch_id=batch_id)

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
        course_public_id: uuid.UUID | None = None,
        resource_type: ResourceType | None = None,
        query: str | None = None,
        include_deleted: bool = False,
    ) -> tuple[Sequence[Resource], int]:
        folder_id = None
        if folder_public_id is not None:
            folder_id = (await self.get_folder(folder_public_id, actor=actor)).id

        course_id = None
        if course_public_id is not None:
            course_id = (await self.courses.get(course_public_id, actor=actor)).id

        course_scope = await self.scopes.visible_course_ids(actor)
        batch_scope = await self.scopes.visible_batch_ids(actor)
        extra = await self._explicitly_granted_resource_ids(actor)

        return await self.resources.search(
            params,
            course_scope=course_scope,
            batch_scope=batch_scope,
            extra_resource_ids=extra,
            folder_id=folder_id,
            course_id=course_id,
            resource_type=resource_type,
            query=query,
            include_deleted=include_deleted and await self._can_manage(actor),
        )

    async def get(self, public_id: uuid.UUID, *, actor: User) -> Resource:
        row = await self.resources.get_by_public_id_full(public_id)
        if row is None:
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

    async def purge(self, public_id: uuid.UUID, *, actor: User) -> None:
        """Permanently remove the row and every stored version."""
        resource = await self.resources.get_by_public_id_full(public_id)
        if resource is None or not await self._resource_reachable(resource, actor):
            raise NotFoundError("Resource not found.")
        await self.require_level(resource, actor, ResourcePermissionLevel.MANAGE)
        if not resource.is_deleted:
            # Purge is the second half of a two-step delete on purpose: an
            # irreversible destroy reachable in one call is how files get
            # lost to a mis-click.
            raise ConflictError("Delete the resource before purging it.")

        versions = await self.resources.versions_for(resource.id)
        for version in versions:
            try:
                await self.storage.delete(version.path)
            except Exception:  # noqa: BLE001
                # Best effort: an orphaned object is reclaimable dead weight,
                # whereas failing here would leave a row nobody can remove.
                logger.warning("Failed to delete stored object", extra={"key": version.path})

        entity_id = resource.id
        await self.session.delete(resource)

        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="resource",
            entity_id=entity_id,
            details={"purged": True, "versions": len(versions)},
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
    PREVIEWABLE_TYPES: frozenset[str] = frozenset({
        "application/pdf",
        "image/png", "image/jpeg", "image/gif", "image/webp", "image/avif", "image/bmp",
        "audio/mpeg", "audio/mp4", "audio/ogg", "audio/wav", "audio/webm",
        "video/mp4", "video/webm", "video/ogg", "video/quicktime",
        "text/plain", "text/markdown", "text/csv",
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
        self, public_id: uuid.UUID, user_public_ids: Sequence[uuid.UUID], *, actor: User
    ) -> list[SharedResource]:
        resource = await self.get(public_id, actor=actor)
        await self.require_level(resource, actor, ResourcePermissionLevel.MANAGE)

        stmt = select(User).where(User.public_id.in_(list(user_public_ids)))
        users = list((await self.session.execute(stmt)).scalars().unique().all())
        missing = set(user_public_ids) - {u.public_id for u in users}
        if missing:
            raise ValidationError(
                "Unknown user(s).",
                details={"unknown_users": sorted(str(m) for m in missing)},
            )

        for user in users:
            if await self.shares.existing(resource_id=resource.id, user_id=user.id):
                continue
            self.session.add(
                SharedResource(
                    resource_id=resource.id,
                    shared_with_user_id=user.id,
                    shared_by_user_id=actor.id,
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
            details={"shared_with": sorted(u.username for u in users)},
        )
        return await self.shares.for_resource(resource.id)

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

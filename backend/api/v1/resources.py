"""Resource and file-management endpoints (spec §10–§11)."""

from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Path, Query, Response, UploadFile, status
from fastapi.responses import RedirectResponse, StreamingResponse

from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.resource import Resource, ResourceFolder, ResourcePermission, SharedResource
from backend.schemas.base import Page, PageParams
from backend.schemas.resource import (
    FolderCreateRequest,
    FolderResponse,
    FolderSummary,
    FolderUpdateRequest,
    GrantPermissionRequest,
    ResourceCopyRequest,
    ResourcePermissionResponse,
    ResourceResponse,
    ResourceSummary,
    ResourceUpdateRequest,
    ResourceVersionResponse,
    ShareLinkResponse,
    ShareResourceRequest,
    SharedResourceResponse,
)
from backend.services.resource_service import ResourceService
from backend.storage import get_storage
from backend.utils.enums import ResourceType

router = APIRouter(tags=["Resources & files"])


def _folder_response(
    f: ResourceFolder, *, children: int = 0, resources: int = 0, path: list[str] | None = None
) -> FolderResponse:
    return FolderResponse(
        public_id=f.public_id,
        name=f.name,
        created_at=f.created_at,
        parent_id=f.parent.public_id if f.parent else None,
        course_id=f.course.public_id if f.course else None,
        course_title=f.course.title if f.course else None,
        batch_id=f.batch.public_id if f.batch else None,
        batch_code=f.batch.batch_code if f.batch else None,
        created_by_username=f.creator.username if f.creator else None,
        child_folder_count=children,
        resource_count=resources,
        path=path or [],
    )


def _resource_response(r: Resource) -> ResourceResponse:
    versions = sorted(r.versions or [], key=lambda v: v.version_number, reverse=True)
    return ResourceResponse(
        public_id=r.public_id,
        name=r.name,
        resource_type=r.resource_type,
        mime_type=r.mime_type,
        size=r.size,
        created_at=r.created_at,
        folder_id=r.folder.public_id if r.folder else None,
        folder_name=r.folder.name if r.folder else None,
        course_id=r.course.public_id if r.course else None,
        course_title=r.course.title if r.course else None,
        uploaded_by_username=r.uploader.username if r.uploader else None,
        updated_at=r.updated_at,
        is_deleted=r.is_deleted,
        deleted_at=r.deleted_at,
        current_version=versions[0].version_number if versions else 0,
        versions=[
            ResourceVersionResponse(
                version_number=v.version_number,
                mime_type=v.mime_type,
                size=v.size,
                change_note=v.change_note,
                created_at=v.created_at,
            )
            for v in versions
        ],
        has_share_link=bool(r.share_token),
    )


def _permission_response(p: ResourcePermission, label: str | None = None) -> ResourcePermissionResponse:
    return ResourcePermissionResponse(
        id=p.id,
        scope_type=p.scope_type,
        scope_id=p.scope_id,
        scope_label=label,
        level=p.level,
        resource_id=None,
        folder_id=None,
        created_at=p.created_at,
    )


def _share_response(s: SharedResource) -> SharedResourceResponse:
    return SharedResourceResponse(
        resource_id=s.resource.public_id,
        resource_name=s.resource.name,
        shared_with_username=s.shared_with_user.username if s.shared_with_user else None,
        shared_by_username=s.shared_by_user.username if s.shared_by_user else None,
        created_at=s.created_at,
    )


async def _stream(key: str, *, filename: str | None, mime_type: str | None) -> StreamingResponse:
    """Stream a stored object back through this server.

    Used whenever the backend has no direct URL (local storage). The
    permission check has already happened, so the bytes are served here
    rather than exposing the storage path.
    """
    stream = await get_storage().open_stream(key)
    safe = quote(filename or "download")
    return StreamingResponse(
        stream,
        media_type=mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename*=UTF-8\'\'{safe}'},
    )


# =============================================================================
# FOLDERS
# =============================================================================


@router.get("/folders", response_model=list[FolderSummary], summary="List folders")
async def list_folders(
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.READ)))
    ],
    parent_id: Annotated[uuid.UUID | None, Query(description="Omit for root folders.")] = None,
    course_id: Annotated[uuid.UUID | None, Query()] = None,
    batch_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[FolderSummary]:
    rows = await ResourceService(session).list_folders(
        actor=actor,
        parent_public_id=parent_id,
        course_public_id=course_id,
        batch_public_id=batch_id,
    )
    return [FolderSummary.model_validate(f) for f in rows]


@router.post(
    "/folders",
    response_model=FolderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a folder",
)
async def create_folder(
    payload: FolderCreateRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.CREATE)))
    ],
) -> FolderResponse:
    """A root folder must name a course or batch; a child inherits its
    parent's, so a subtree cannot span two audiences."""
    return _folder_response(await ResourceService(session).create_folder(payload, actor=actor))


@router.get("/folders/{folder_id}", response_model=FolderResponse, summary="Get one folder")
async def get_folder(
    folder_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.READ)))
    ],
) -> FolderResponse:
    service = ResourceService(session)
    folder = await service.get_folder(folder_id, actor=actor)
    children, resources = await service.folders.counts(folder.id)
    return _folder_response(
        folder,
        children=children,
        resources=resources,
        path=await service.folder_path(folder),
    )


@router.patch(
    "/folders/{folder_id}", response_model=FolderResponse, summary="Rename or move a folder"
)
async def update_folder(
    folder_id: uuid.UUID,
    payload: FolderUpdateRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.UPDATE)))
    ],
) -> FolderResponse:
    """Moving a folder into its own subtree is refused — it would detach that
    subtree from every root."""
    return _folder_response(
        await ResourceService(session).update_folder(folder_id, payload, actor=actor)
    )


@router.delete(
    "/folders/{folder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an empty folder",
)
async def delete_folder(
    folder_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.DELETE)))
    ],
) -> Response:
    """Refused while it holds subfolders or resources — the FK cascades, so
    deleting would silently take the whole subtree with it."""
    await ResourceService(session).delete_folder(folder_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# RESOURCES
# =============================================================================


@router.get("/resources", response_model=Page[ResourceSummary], summary="List resources")
async def list_resources(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.READ)))
    ],
    folder_id: Annotated[uuid.UUID | None, Query()] = None,
    course_id: Annotated[uuid.UUID | None, Query()] = None,
    resource_type: Annotated[ResourceType | None, Query()] = None,
    query: Annotated[str | None, Query(max_length=100)] = None,
    include_deleted: Annotated[bool, Query(description="Requires resource.delete.")] = False,
) -> Page[ResourceSummary]:
    """Visible through three independent routes: the resource's course, its
    batch, or an explicit permission grant / direct share."""
    rows, total = await ResourceService(session).list_resources(
        params,
        actor=actor,
        folder_public_id=folder_id,
        course_public_id=course_id,
        resource_type=resource_type,
        query=query,
        include_deleted=include_deleted,
    )
    return Page.build(
        [ResourceSummary.model_validate(r) for r in rows], total=total, params=params
    )


@router.post(
    "/resources",
    response_model=ResourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file",
)
async def upload_resource(
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.CREATE)))
    ],
    file: Annotated[UploadFile, File()],
    resource_type: Annotated[ResourceType, Form()] = ResourceType.lecture_sheet,
    name: Annotated[str | None, Form()] = None,
    folder_id: Annotated[uuid.UUID | None, Form()] = None,
    course_id: Annotated[uuid.UUID | None, Form()] = None,
    batch_id: Annotated[uuid.UUID | None, Form()] = None,
) -> ResourceResponse:
    """Multipart upload. The stored filename is a generated UUID — the
    client's filename is used only to recover an extension, and only after
    sanitising, so a crafted name cannot traverse or be executed.

    Content type is checked against an allowlist (`STORAGE_ALLOWED_MIME_TYPES`)
    and size against `STORAGE_MAX_UPLOAD_BYTES`.
    """
    return _resource_response(
        await ResourceService(session).upload(
            upload=file,
            actor=actor,
            name=name,
            resource_type=resource_type,
            folder_public_id=folder_id,
            course_public_id=course_id,
            batch_public_id=batch_id,
        )
    )


@router.get("/resources/{resource_id}", response_model=ResourceResponse, summary="Get one resource")
async def get_resource(
    resource_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.READ)))
    ],
) -> ResourceResponse:
    return _resource_response(await ResourceService(session).get(resource_id, actor=actor))


@router.post(
    "/resources/{resource_id}/versions",
    response_model=ResourceResponse,
    summary="Upload a new version",
)
async def upload_version(
    resource_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.UPDATE)))
    ],
    file: Annotated[UploadFile, File()],
    change_note: Annotated[str | None, Form()] = None,
) -> ResourceResponse:
    """Spec §10's versioning: the new file becomes current and every earlier
    version stays downloadable."""
    return _resource_response(
        await ResourceService(session).upload_version(
            resource_id, upload=file, actor=actor, change_note=change_note
        )
    )


@router.get("/resources/{resource_id}/download", summary="Download a resource")
async def download_resource(
    resource_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.READ)))
    ],
    version: Annotated[int | None, Query(ge=1, description="Defaults to the current version.")] = None,
):
    """Authorises first, then either streams the bytes (local storage) or
    redirects to a short-lived presigned URL (R2) so file traffic bypasses
    this server. The link is only minted after the permission check."""
    resource, key, url = await ResourceService(session).resolve_download(
        resource_id, actor=actor, version=version
    )
    if url:
        return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    return await _stream(key, filename=resource.name, mime_type=resource.mime_type)


@router.patch(
    "/resources/{resource_id}", response_model=ResourceResponse, summary="Update or move a resource"
)
async def update_resource(
    resource_id: uuid.UUID,
    payload: ResourceUpdateRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.UPDATE)))
    ],
) -> ResourceResponse:
    """Metadata and location only — replacing the file is a version upload."""
    return _resource_response(
        await ResourceService(session).update(resource_id, payload, actor=actor)
    )


@router.post(
    "/resources/{resource_id}/copy",
    response_model=ResourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Copy a resource",
)
async def copy_resource(
    resource_id: uuid.UUID,
    payload: ResourceCopyRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.CREATE)))
    ],
) -> ResourceResponse:
    """The stored bytes are duplicated, not referenced — two rows sharing one
    stored object would mean deleting either takes the other's file."""
    return _resource_response(
        await ResourceService(session).copy(
            resource_id,
            actor=actor,
            target_folder_id=payload.target_folder_id,
            name=payload.name,
        )
    )


@router.delete(
    "/resources/{resource_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a resource (recoverable)",
)
async def delete_resource(
    resource_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.DELETE)))
    ],
) -> Response:
    """Soft delete — the file stays in storage and can be restored."""
    await ResourceService(session).soft_delete(resource_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/resources/{resource_id}/restore",
    response_model=ResourceResponse,
    summary="Restore a deleted resource",
)
async def restore_resource(
    resource_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.DELETE)))
    ],
) -> ResourceResponse:
    return _resource_response(await ResourceService(session).restore(resource_id, actor=actor))


@router.delete(
    "/resources/{resource_id}/purge",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently destroy a deleted resource",
)
async def purge_resource(
    resource_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.DELETE)))
    ],
) -> Response:
    """Irreversible, and only reachable on an already-deleted resource — a
    one-call destroy is how files get lost to a mis-click."""
    await ResourceService(session).purge(resource_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# PERMISSIONS (spec §11 cascade)
# =============================================================================


@router.get(
    "/resource-permissions",
    response_model=list[ResourcePermissionResponse],
    summary="List grants on a resource or folder",
)
async def list_permissions(
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.READ)))
    ],
    resource_id: Annotated[uuid.UUID | None, Query()] = None,
    folder_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[ResourcePermissionResponse]:
    rows = await ResourceService(session).list_permissions(
        actor=actor, resource_public_id=resource_id, folder_public_id=folder_id
    )
    return [_permission_response(p) for p in rows]


@router.post(
    "/resource-permissions",
    response_model=ResourcePermissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Grant access at a course, batch, session or user scope",
)
async def grant_permission(
    payload: GrantPermissionRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.UPDATE)))
    ],
    resource_id: Annotated[uuid.UUID | None, Query()] = None,
    folder_id: Annotated[uuid.UUID | None, Query()] = None,
) -> ResourcePermissionResponse:
    """Spec §11's Course → Batch → Session → Individual cascade, as one table.
    Re-granting the same scope updates its level rather than duplicating."""
    return _permission_response(
        await ResourceService(session).grant_permission(
            actor=actor,
            payload=payload,
            resource_public_id=resource_id,
            folder_public_id=folder_id,
        )
    )


@router.delete(
    "/resource-permissions/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a grant",
)
async def revoke_permission(
    permission_id: int,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.UPDATE)))
    ],
) -> Response:
    await ResourceService(session).revoke_permission(permission_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# SHARING
# =============================================================================


@router.post(
    "/resources/{resource_id}/share",
    response_model=list[SharedResourceResponse],
    summary="Share a resource with specific users",
)
async def share_resource(
    resource_id: uuid.UUID,
    payload: ShareResourceRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.UPDATE)))
    ],
) -> list[SharedResourceResponse]:
    """Gives named users access to this one file without opening the course
    it belongs to."""
    rows = await ResourceService(session).share(resource_id, payload.user_ids, actor=actor)
    return [_share_response(s) for s in rows]


@router.delete(
    "/resources/{resource_id}/share/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop sharing with a user",
)
async def unshare_resource(
    resource_id: uuid.UUID,
    user_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.UPDATE)))
    ],
) -> Response:
    await ResourceService(session).unshare(resource_id, user_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/resources/{resource_id}/share-link",
    response_model=ShareLinkResponse,
    summary="Issue or revoke a public link",
)
async def set_share_link(
    resource_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.UPDATE)))
    ],
    enabled: Annotated[bool, Query()] = True,
) -> ShareLinkResponse:
    """The token is the only thing protecting the file, so it is 256 bits of
    randomness and revocable at any time."""
    resource = await ResourceService(session).set_share_link(
        resource_id, enabled=enabled, actor=actor
    )
    return ShareLinkResponse(
        share_token=resource.share_token,
        url_path=f"/api/v1/shared/{resource.share_token}" if resource.share_token else None,
    )


@router.get("/shared-with-me", response_model=list[SharedResourceResponse], summary="Files shared with me")
async def shared_with_me(
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.RESOURCE, Action.READ)))
    ],
) -> list[SharedResourceResponse]:
    rows = await ResourceService(session).shares.shared_with(actor.id)
    return [_share_response(s) for s in rows]


@router.get("/shared/{token}", summary="Download via a public share link")
async def download_shared(token: Annotated[str, Path(min_length=16, max_length=128)], session: DBSession):
    """Deliberately unauthenticated: the token *is* the authorisation.

    Compared in constant time, and a soft-deleted resource is simply not
    found — revoking the link or deleting the file both cut access
    immediately.
    """
    resource, key = await ResourceService(session).resolve_share_link(token)
    url = get_storage().presigned_url(key)
    if url:
        return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    return await _stream(key, filename=resource.name, mime_type=resource.mime_type)

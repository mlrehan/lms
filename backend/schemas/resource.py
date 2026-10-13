"""Resource, folder, version, permission and sharing schemas (spec §10–§11)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field, model_validator

from backend.schemas.base import APIModel, RequestModel
from backend.utils.enums import ResourcePermissionLevel, ResourceScopeType, ResourceType


# =============================================================================
# FOLDERS
# =============================================================================


class FolderSummary(APIModel):
    public_id: uuid.UUID
    name: str
    created_at: datetime


class FolderResponse(FolderSummary):
    parent_id: uuid.UUID | None = None
    course_id: uuid.UUID | None = None
    course_title: str | None = None
    batch_id: uuid.UUID | None = None
    batch_code: str | None = None
    created_by_username: str | None = None
    child_folder_count: int = 0
    resource_count: int = 0
    path: list[str] = Field(
        default_factory=list,
        description="Folder names from the root down to and including this one.",
    )


class FolderCreateRequest(RequestModel):
    name: Annotated[str, Field(min_length=1, max_length=255)]
    parent_id: uuid.UUID | None = Field(
        default=None, description="Omit to create a folder at the root of its course/batch."
    )
    course_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _anchored(self):  # type: ignore[no-untyped-def]
        """A root folder must say where it belongs; a child inherits it.

        Without this a root folder could exist attached to nothing, visible
        to nobody but an unrestricted admin -- the same trap the exam anchor
        constraint exists to prevent.
        """
        if self.parent_id is None and self.course_id is None and self.batch_id is None:
            raise ValueError(
                "a root folder must specify course_id, batch_id, or both"
            )
        return self


class FolderUpdateRequest(RequestModel):
    """Renaming and moving are the same operation on a tree node."""

    name: Annotated[str | None, Field(min_length=1, max_length=255)] = None
    parent_id: uuid.UUID | None = Field(
        default=None, description="New parent. Send explicitly as null to move to the root."
    )


# =============================================================================
# RESOURCES
# =============================================================================


class ResourceVersionResponse(APIModel):
    version_number: int
    mime_type: str | None = None
    size: int | None = None
    change_note: str | None = None
    created_at: datetime
    uploaded_by_username: str | None = None


class ResourceSummary(APIModel):
    public_id: uuid.UUID
    name: str | None = None
    resource_type: ResourceType
    is_restricted: bool = Field(
        default=False,
        description=(
            "Staff-only. A row carrying true is never returned to someone who "
            "may not see such files -- they are filtered out of the query."
        ),
    )
    mime_type: str | None = None
    size: int | None = None
    created_at: datetime


class ResourceResponse(ResourceSummary):
    folder_id: uuid.UUID | None = None
    folder_name: str | None = None
    course_id: uuid.UUID | None = None
    course_title: str | None = None
    batch_id: uuid.UUID | None = None
    uploaded_by_username: str | None = None
    updated_at: datetime | None = None
    is_deleted: bool = False
    deleted_at: datetime | None = None
    current_version: int = 0
    versions: list[ResourceVersionResponse] = Field(default_factory=list)
    has_share_link: bool = Field(
        default=False, description="True when a public share token has been issued."
    )
    # What *this* caller may do with the file. Sent so the console can hide the
    # actions it would be refused rather than offering buttons that 403 -- the
    # server is still the authority, this is only what the UI renders.
    is_restricted: bool = Field(
        default=False,
        description="Staff-only. Never true in a response to someone who may not see such files.",
    )
    my_level: ResourcePermissionLevel | None = Field(
        default=None,
        description="Caller's effective level: VIEW < DOWNLOAD < EDIT < MANAGE.",
    )
    can_preview: bool = Field(
        default=False, description="True when this type can be rendered in the browser."
    )
    # The stored key is deliberately never exposed -- it is an internal
    # storage path, and publishing it invites callers to construct their own
    # URLs against the bucket instead of going through the permission check.


class ResourceUpdateRequest(RequestModel):
    """Metadata only. Replacing the *file* is a new version upload."""

    name: Annotated[str | None, Field(min_length=1, max_length=255)] = None
    resource_type: ResourceType | None = None
    folder_id: uuid.UUID | None = None
    is_restricted: bool | None = Field(
        default=None,
        description=(
            "Staff-only. Hidden from students, guardians and corporate managers "
            "whatever else they have been granted, and cannot carry a public link. "
            "Only settable by someone who can see staff-only files."
        ),
    )


class ResourceCopyRequest(RequestModel):
    target_folder_id: uuid.UUID | None = None
    name: Annotated[str | None, Field(min_length=1, max_length=255)] = None


# =============================================================================
# PERMISSIONS (spec §11's Course -> Batch -> Session -> Individual cascade)
# =============================================================================


class ResourcePermissionResponse(APIModel):
    id: int
    scope_type: ResourceScopeType
    scope_id: int
    scope_label: str | None = Field(
        default=None, description="Human-readable name of the course/batch/session/user."
    )
    level: ResourcePermissionLevel
    resource_id: uuid.UUID | None = None
    folder_id: uuid.UUID | None = None
    granted_by_username: str | None = None
    created_at: datetime


class GrantPermissionRequest(RequestModel):
    scope_type: ResourceScopeType
    scope_public_id: uuid.UUID = Field(
        description="public_id of the course, batch, session or user this grant applies to."
    )
    level: ResourcePermissionLevel


# =============================================================================
# SHARING
# =============================================================================


class SharedResourceResponse(APIModel):
    resource_id: uuid.UUID
    resource_name: str | None = None
    level: ResourcePermissionLevel = Field(
        description="What the recipient may do with it."
    )
    shared_with_user_id: uuid.UUID | None = None
    shared_with_name: str | None = Field(
        default=None,
        description=(
            "The recipient's name. Never their login name: in this deployment "
            "that is their email address, and a share list is not a place to "
            "publish one."
        ),
    )
    shared_with_role: str | None = None
    shared_by_name: str | None = None
    created_at: datetime
    # Enough for a viewer to choose how to render the file without a second
    # request per row. The list screen draws a type icon and a filter from
    # these, and the viewer decides which renderer to mount -- both before any
    # of the bytes are fetched, which is the point.
    resource_type: ResourceType | None = None
    mime_type: str | None = None
    size: int | None = None


class SharePlacement(APIModel):
    """One cohort a candidate belongs to, from the sharer's point of view."""

    batch_code: str | None = None
    course_title: str | None = None


class ShareCandidateResponse(APIModel):
    """A person who may be given a file, and enough to tell them apart.

    Carries no email address and no login name by construction -- there is no
    field for one, which is the difference between a response that declines to
    populate a leak and one that cannot express it.
    """

    public_id: uuid.UUID
    name: str
    role: str = Field(description="Administrator, Tutor, Student, Guardian or Manager.")
    placements: list[SharePlacement] = Field(
        default_factory=list,
        description="Batches and courses this person is in, within the sharer's own scope.",
    )
    relation: str | None = Field(
        default=None,
        description='How a guardian reaches this list, e.g. "Guardian of Jane Doe".',
    )
    more_placements: int = Field(
        default=0, description="Cohorts beyond the ones listed."
    )


class BulkShareRequest(RequestModel):
    """Several files, several people, one decision."""

    resource_ids: list[uuid.UUID] = Field(
        min_length=1, max_length=100, description="Files to share."
    )
    user_ids: list[uuid.UUID] = Field(
        min_length=1, max_length=200, description="People to share them with."
    )
    level: ResourcePermissionLevel = Field(
        default=ResourcePermissionLevel.VIEW,
        description=(
            "What the recipients may do. VIEW lets them read or watch it in "
            "place; DOWNLOAD hands over the bytes. Defaults to the narrower."
        ),
    )


class ShareResourceRequest(RequestModel):
    user_ids: list[uuid.UUID] = Field(
        min_length=1, max_length=200, description="Users to share this resource with."
    )
    level: ResourcePermissionLevel = Field(
        default=ResourcePermissionLevel.VIEW,
        description=(
            "What the recipients may do. VIEW lets them watch or read it in "
            "place without keeping a copy; DOWNLOAD hands over the bytes. "
            "Defaults to VIEW -- the narrower of the two, so a share that "
            "forgets to say grants the less."
        ),
    )


class ShareLinkResponse(APIModel):
    share_token: str | None = None
    url_path: str | None = Field(
        default=None, description="Relative path a recipient can open without signing in."
    )

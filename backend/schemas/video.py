"""Video library request and response shapes.

`source_url` -- the provider's own address -- appears only on
`VideoDetail`, and only for a caller who may edit the video. Everyone else is
given paths on this API (`player_url`, `open_url`, `thumbnail_url`) that
re-check access every time they are followed.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field

from backend.schemas.base import APIModel, RequestModel


class VideoProviderNotes(APIModel):
    """What the LMS can and cannot promise for this provider, in plain words."""

    plays_in_lms: bool
    download: str
    domain_restriction: str
    needs_provider_sign_in: bool


class VideoSummary(APIModel):
    public_id: uuid.UUID
    title: str
    description: str | None = None
    provider: str
    provider_label: str
    plays_in_lms: bool
    thumbnail_url: str | None = Field(
        default=None, description="A path on this API (re-checks access), or null."
    )
    course_id: uuid.UUID | None = None
    course_title: str | None = None
    batch_id: uuid.UUID | None = None
    batch_code: str | None = None
    category_id: uuid.UUID | None = None
    category_name: str | None = None
    owner_name: str | None = None
    is_mine: bool = False
    can_manage: bool = False
    share_count: int | None = Field(
        default=None, description="How many shares it has; only for whoever manages it."
    )
    created_at: datetime


class VideoShareLine(APIModel):
    id: int
    kind: str = Field(description="PERSON or BATCH")
    label: str
    created_at: datetime


class VideoDetail(VideoSummary):
    player_url: str | None = Field(
        default=None, description="Frame this path; null when the provider cannot play in the LMS."
    )
    open_url: str = Field(description="Opens the video on the provider's site, after a re-check.")
    source_url: str | None = Field(
        default=None, description="The provider's address -- only for whoever manages the video."
    )
    notes: VideoProviderNotes
    shares: list[VideoShareLine] | None = None


class VideoCreateRequest(RequestModel):
    title: Annotated[str, Field(min_length=2, max_length=255)]
    url: Annotated[str, Field(min_length=4, max_length=2048)]
    description: Annotated[str | None, Field(max_length=5000)] = None
    course_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None


class VideoUpdateRequest(RequestModel):
    title: Annotated[str | None, Field(min_length=2, max_length=255)] = None
    url: Annotated[str | None, Field(min_length=4, max_length=2048)] = None
    description: Annotated[str | None, Field(max_length=5000)] = None
    course_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None


class VideoShareRequest(RequestModel):
    user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    batch_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class VideoShareResult(APIModel):
    people_added: int
    batches_added: int


class VideoInspectRequest(RequestModel):
    url: Annotated[str, Field(min_length=4, max_length=2048)]


class VideoInspectResponse(APIModel):
    """What the LMS recognises in a pasted link, before anything is saved."""

    provider: str
    provider_label: str
    notes: VideoProviderNotes

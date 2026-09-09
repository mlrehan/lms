"""Course discussion schemas (spec §16)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field

from backend.schemas.base import APIModel, RequestModel
from backend.schemas.messaging import PartyRef


class DiscussionReplyResponse(APIModel):
    public_id: uuid.UUID
    discussion_id: uuid.UUID
    author: PartyRef | None = None
    body: str
    created_at: datetime | None = None


class DiscussionResponse(APIModel):
    public_id: uuid.UUID
    course_id: uuid.UUID
    course_title: str | None = None
    author: PartyRef | None = None
    title: str
    body: str
    is_pinned: bool = False
    is_locked: bool = False
    reply_count: int = 0
    created_at: datetime | None = None


class CreateDiscussionRequest(RequestModel):
    course_id: uuid.UUID
    title: Annotated[str, Field(min_length=1, max_length=255)]
    body: Annotated[str, Field(min_length=1, max_length=20_000)]


class UpdateDiscussionRequest(RequestModel):
    title: Annotated[str | None, Field(min_length=1, max_length=255)] = None
    body: Annotated[str | None, Field(min_length=1, max_length=20_000)] = None
    # Moderation. Held apart from title/body in the service: editing your own
    # words and silencing a thread other people are using are different acts,
    # and only the second one needs to be a tutor of that course.
    is_pinned: bool | None = None
    is_locked: bool | None = None


class ReplyRequest(RequestModel):
    body: Annotated[str, Field(min_length=1, max_length=20_000)]

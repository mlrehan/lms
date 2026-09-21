"""Private message and notification schemas (spec §16)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import Field

from backend.schemas.base import APIModel, RequestModel
from backend.utils.enums import NotificationChannel


class PartyRef(APIModel):
    """The other end of a message, named rather than referenced.

    An inbox that returns bare ids forces the client into an N+1 of user
    lookups just to render a list of names.
    """

    public_id: uuid.UUID
    username: str
    full_name: str | None = None


class UnreadCountResponse(APIModel):
    unread: int


class NotificationResponse(APIModel):
    public_id: uuid.UUID
    channel: NotificationChannel
    type: str
    title: str
    body: str
    meta: dict[str, Any] | None = None
    is_read: bool = False
    sent_at: datetime | None = None


class MarkReadResponse(APIModel):
    updated: int

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


class MessageBox(str, Enum):
    INBOX = "inbox"
    SENT = "sent"
    ALL = "all"


class MessageResponse(APIModel):
    public_id: uuid.UUID
    sender: PartyRef
    recipient: PartyRef
    course_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    subject: str | None = None
    body: str | None = None
    is_read: bool = False
    read_at: datetime | None = None
    created_at: datetime | None = None


class ConversationResponse(APIModel):
    """One row per correspondent, for a mailbox landing page."""

    counterpart: PartyRef
    last_message_id: uuid.UUID
    last_message_at: datetime | None = None
    last_subject: str | None = None
    last_snippet: str | None = None
    unread_count: int = 0
    total_messages: int = 0


class SendMessageRequest(RequestModel):
    recipient_id: uuid.UUID
    subject: Annotated[str | None, Field(max_length=250)] = None
    body: Annotated[str, Field(min_length=1, max_length=20_000)]
    course_id: uuid.UUID | None = Field(
        default=None, description="Optional context: which course this is about."
    )
    batch_id: uuid.UUID | None = Field(
        default=None, description="Optional context: which batch this is about."
    )


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

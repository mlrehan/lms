"""Mail schemas.

People are always `MailPerson`: a name and a role label, **never an email address or login name**. The composer
picks recipients from a directory that returns the same thing, so nothing in the mail feature discloses what
`core/privacy.py` withholds.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import Field

from backend.schemas.base import APIModel, RequestModel


class MailFolder(str, Enum):
    INBOX = "inbox"
    SENT = "sent"
    STARRED = "starred"
    DRAFTS = "drafts"


class MailPerson(APIModel):
    public_id: uuid.UUID
    name: str
    role: str | None = None


class MailAttachmentInfo(APIModel):
    public_id: uuid.UUID
    filename: str
    content_type: str
    size: int


class MailDelivery(APIModel):
    """How the email copies went. Only the sender sees this."""

    enabled: bool = Field(description="False when email delivery is switched off for this deployment.")
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    pending: int = 0
    copy_to_me: str | None = Field(default=None, description="SENT, FAILED or SKIPPED; null when no copy was asked for.")
    failures: list[str] = Field(default_factory=list, description="Recipient names whose email failed.")


class MailListItem(APIModel):
    public_id: uuid.UUID
    thread_id: uuid.UUID
    subject: str
    snippet: str
    sender: MailPerson
    recipients_summary: str
    sent_at: datetime | None = None
    updated_at: datetime | None = None
    is_read: bool
    is_starred: bool
    is_draft: bool
    has_attachments: bool
    thread_count: int = 1
    is_mine: bool = False


class MailMessageView(APIModel):
    public_id: uuid.UUID
    thread_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    subject: str
    body_html: str
    sender: MailPerson
    to: list[MailPerson]
    cc: list[MailPerson]
    bcc: list[MailPerson] = Field(default_factory=list, description="Only ever filled in for the sender.")
    you_were_bcc: bool = False
    sent_at: datetime | None = None
    is_draft: bool = False
    is_read: bool = True
    is_starred: bool = False
    is_mine: bool = False
    attachments: list[MailAttachmentInfo] = Field(default_factory=list)
    delivery: MailDelivery | None = None


class MailThread(APIModel):
    thread_id: uuid.UUID
    subject: str
    messages: list[MailMessageView]


class ComposeRequest(RequestModel):
    to: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    cc: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    bcc: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    subject: str = Field(default="", max_length=600)
    body_html: str = Field(default="", max_length=600_000)
    attachment_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    reply_to_id: uuid.UUID | None = Field(default=None, description="The message being replied to; puts this one in its thread.")
    draft_id: uuid.UUID | None = Field(default=None, description="Send (or update) this saved draft rather than starting a new message.")
    email_copy: bool = Field(default=True, description="Also email a copy to my own address.")


class StateRequest(RequestModel):
    read: bool | None = None
    starred: bool | None = None


class ReplyOptions(APIModel):
    """Who a reply would go to -- already limited to people the caller may write to, so replying to everyone
    never includes somebody they are not allowed to message."""

    reply: list[MailPerson]
    reply_all_to: list[MailPerson]
    reply_all_cc: list[MailPerson]


class DirectoryResponse(APIModel):
    items: list[MailPerson]

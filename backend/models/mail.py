"""Internal mail: messages with several recipients (To / Cc / Bcc), attachments and threads.

This replaces the one-to-one `user_messages`. The shape follows what an inbox needs:

* one **message** row holds what was said, once, however many people it went to;
* one **recipient** row per person holds what is *theirs* about it (read, starred, removed from their view, and
  whether the email copy reached them), so one person deleting a message never touches anyone else's copy;
* **Bcc** is a `kind` on the recipient row, and is only ever disclosed to the sender (see `services/mail_service`);
* a **thread** is a shared `thread_id`, set from the message being replied to, so a conversation reads as one.

Nothing here stores an email address: recipients are users, and an address is read from the user only at the
moment an email copy is sent.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, PublicIdMixin
from backend.models.helpers import bool_column, utc_datetime_column


class MailMessage(Base, PublicIdMixin):
    __tablename__ = "mail_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True, default=uuid.uuid4)
    parent_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("mail_messages.id", ondelete="SET NULL"), nullable=True)
    sender_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    subject: Mapped[str] = mapped_column(String(250), nullable=False, default="")
    # Sanitised HTML (`services/mail_html.py`), never what the browser sent. `body_text` is derived from it, for
    # previews, search and the plain-text part of an email.
    body_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    is_draft: Mapped[bool] = bool_column(default=True, nullable=False)
    sent_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False, onupdate=False, nullable=True)

    # The sender's own view of it: removing a sent message hides it from *their* Sent folder only.
    sender_deleted: Mapped[bool] = bool_column(default=False, nullable=False)
    sender_starred: Mapped[bool] = bool_column(default=False, nullable=False)

    # A copy to the sender's own email, when they asked for one; and how that went.
    email_copy_requested: Mapped[bool] = bool_column(default=False, nullable=False)
    email_copy_status: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    created_at: Mapped[datetime] = utc_datetime_column(default=True, onupdate=False, nullable=False)
    updated_at: Mapped[datetime] = utc_datetime_column(default=True, onupdate=True, nullable=False)

    sender: Mapped["User"] = relationship("User", foreign_keys=[sender_id], lazy="selectin")  # noqa: F821
    recipients: Mapped[List["MailRecipient"]] = relationship(
        back_populates="message", cascade="all, delete-orphan", passive_deletes=True, lazy="selectin", order_by="MailRecipient.id"
    )
    attachments: Mapped[List["MailAttachment"]] = relationship(
        back_populates="message", cascade="all, delete-orphan", passive_deletes=True, lazy="selectin", order_by="MailAttachment.id"
    )

    __table_args__ = (
        Index("ix_mail_messages_sender_sent", "sender_id", "sent_at"),
        Index("ix_mail_messages_thread_sent", "thread_id", "sent_at"),
    )


class MailRecipient(Base):
    __tablename__ = "mail_recipients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(Integer, ForeignKey("mail_messages.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(3), nullable=False, comment="TO, CC or BCC")

    is_read: Mapped[bool] = bool_column(default=False, nullable=False)
    read_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False, onupdate=False, nullable=True)
    is_starred: Mapped[bool] = bool_column(default=False, nullable=False)
    # Removed from *this person's* mailbox; the message and everyone else's copy are untouched.
    is_deleted: Mapped[bool] = bool_column(default=False, nullable=False)

    # The email copy: PENDING until tried, then SENT, FAILED (with a short reason) or SKIPPED (no address, or
    # email delivery switched off). Independent of the in-app copy, which always exists.
    email_status: Mapped[str] = mapped_column(String(10), nullable=False, default="PENDING", server_default="PENDING")
    email_error: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    emailed_at: Mapped[Optional[datetime]] = utc_datetime_column(default=False, onupdate=False, nullable=True)

    message: Mapped[MailMessage] = relationship(back_populates="recipients")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id], lazy="selectin")  # noqa: F821

    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_mail_recipients_message_user"),
        CheckConstraint("kind IN ('TO', 'CC', 'BCC')", name="ck_mail_recipients_kind"),
        # An inbox is "mine, not removed, newest first".
        Index("ix_mail_recipients_user_state", "user_id", "is_deleted", "is_read"),
    )


class MailAttachment(Base, PublicIdMixin):
    __tablename__ = "mail_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # NULL while the file has been uploaded to a draft-in-progress but not yet sent with anything.
    message_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("mail_messages.id", ondelete="CASCADE"), nullable=True, index=True)
    uploader_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = utc_datetime_column(default=True, onupdate=False, nullable=False)

    message: Mapped[Optional[MailMessage]] = relationship(back_populates="attachments")

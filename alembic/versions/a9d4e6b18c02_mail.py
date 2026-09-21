"""Internal mail with Cc/Bcc, attachments and threads, replacing one-to-one user_messages.

Revision ID: a9d4e6b18c02
Revises: f7c3a92d1b48
Create Date: 2026-09-21 14:00:00.000000

`user_messages` held no rows when this ran, so nothing is migrated; the table is dropped rather than left
behind as a second, unused place messages might be.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9d4e6b18c02"
down_revision: Union[str, Sequence[str], None] = "f7c3a92d1b48"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ts(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable, server_default=None if nullable else sa.func.now())


def upgrade() -> None:
    op.create_table(
        "mail_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("mail_messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sender_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject", sa.String(250), nullable=False, server_default=""),
        sa.Column("body_html", sa.Text(), nullable=False, server_default=""),
        sa.Column("body_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_draft", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _ts("sent_at", nullable=True),
        sa.Column("sender_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("sender_starred", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("email_copy_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("email_copy_status", sa.String(10), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_mail_messages_public_id", "mail_messages", ["public_id"], unique=True)
    op.create_index("ix_mail_messages_thread_id", "mail_messages", ["thread_id"])
    op.create_index("ix_mail_messages_sender_id", "mail_messages", ["sender_id"])
    op.create_index("ix_mail_messages_sender_sent", "mail_messages", ["sender_id", "sent_at"])
    op.create_index("ix_mail_messages_thread_sent", "mail_messages", ["thread_id", "sent_at"])

    op.create_table(
        "mail_recipients",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("mail_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(3), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _ts("read_at", nullable=True),
        sa.Column("is_starred", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("email_status", sa.String(10), nullable=False, server_default="PENDING"),
        sa.Column("email_error", sa.String(200), nullable=True),
        _ts("emailed_at", nullable=True),
        sa.UniqueConstraint("message_id", "user_id", name="uq_mail_recipients_message_user"),
        sa.CheckConstraint("kind IN ('TO', 'CC', 'BCC')", name="ck_mail_recipients_kind"),
    )
    op.create_index("ix_mail_recipients_user_state", "mail_recipients", ["user_id", "is_deleted", "is_read"])

    op.create_table(
        "mail_attachments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("mail_messages.id", ondelete="CASCADE"), nullable=True),
        sa.Column("uploader_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        _ts("created_at"),
    )
    op.create_index("ix_mail_attachments_public_id", "mail_attachments", ["public_id"], unique=True)
    op.create_index("ix_mail_attachments_message_id", "mail_attachments", ["message_id"])
    op.create_index("ix_mail_attachments_uploader_id", "mail_attachments", ["uploader_id"])

    op.drop_table("user_messages")


def downgrade() -> None:
    raise NotImplementedError("Mail history cannot be rebuilt into the old one-to-one table; restore from a backup instead.")

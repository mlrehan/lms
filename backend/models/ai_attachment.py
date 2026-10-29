"""Files a person attaches to an AI assistant message.

A file attached in the chat is the person's own working material -- a
notebook a student sent the tutor, a mark scheme, a photo of a whiteboard --
not a course resource. It never enters the resource library, is readable only
by the person who attached it, and goes when their conversation history goes
(retention window, or "Erase conversation memory").

The text is extracted once, at upload, and kept here: the assistant reads it
on every turn that refers to the file, and re-parsing a 20 MB notebook per
turn would make the second question slower than the first. The original bytes
are kept in storage under ``ai-attachments/`` so an image can be shown to the
model and a failed extraction can be investigated.
"""

from __future__ import annotations

from typing import Optional

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, PublicIdMixin, TimestampMixin
from backend.models.helpers import bool_column


class AIAttachment(Base, TimestampMixin, PublicIdMixin):
    __tablename__ = "ai_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # The name as the person's computer gave it, for display only. It never
    # reaches the filesystem: the stored object is named by `storage_key`.
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(127), nullable=False)
    # TEXT / CODE / NOTEBOOK / PDF / DOCX / XLSX / CSV / IMAGE
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    # READY (text or image usable) / EMPTY (readable, no text: a scanned PDF)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    truncated: Mapped[bool] = bool_column(default=False)
    # Pages, notebook cells, sheets -- whatever describes this kind of file.
    details: Mapped[Optional[dict]] = mapped_column(sa.JSON, nullable=True)

    __table_args__ = (
        Index("idx_ai_attachments_user_created", "user_id", "created_at"),
        sa.CheckConstraint("status IN ('READY', 'EMPTY')", name="status"),
    )

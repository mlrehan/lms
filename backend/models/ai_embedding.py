"""AI Vector Embedding & Conversation State Models.

Stores chunked document vectors for permission-aware RAG and user-scoped conversation
sessions for conversational AI state management.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, PublicIdMixin, TimestampMixin
from backend.models.helpers import utc_datetime_column


class ResourceEmbedding(Base, TimestampMixin, PublicIdMixin):
    """Vector embedding chunk for a learning resource, lecture sheet, or document."""

    __tablename__ = "resource_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    resource_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(64), nullable=False, default="text-embedding-3-large")
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False, default=3072)
    course_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=True, index=True
    )
    batch_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("batches.id", ondelete="CASCADE"), nullable=True, index=True
    )
    is_restricted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    resource: Mapped["Resource"] = relationship("Resource", lazy="selectin")

    __table_args__ = (
        Index("idx_resource_embeddings_course_restricted", "course_id", "is_restricted"),
    )


class AIConversationMessage(Base, TimestampMixin, PublicIdMixin):
    """User-scoped conversational message record for persistent chat memory."""

    __tablename__ = "ai_conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user, assistant, system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # Files attached to this (user) message: id, name, kind, size -- never their contents.
    attachments: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["User"] = relationship("User", lazy="selectin")

    __table_args__ = (
        Index("idx_ai_messages_user_created", "user_id", "created_at"),
    )


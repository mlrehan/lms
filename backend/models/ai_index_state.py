"""What the course-material index knows about each resource.

One row per resource, recording which stored file (`source_key`, the storage
key of the version that was current) was indexed, with which embedding model,
and how it went. A resource needs indexing when it has no row, when its
current file differs from the one indexed (a new version was uploaded), or
when the embedding model changed (vectors from different models cannot be
compared, so old chunks would match nothing).

Without this the indexer could not tell "indexed, and contained no text"
from "never looked at", and would retry an unreadable file on every pass.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin


class ResourceIndexState(Base, TimestampMixin):
    __tablename__ = "resource_index_states"

    resource_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True
    )
    source_key: Mapped[str] = mapped_column(String(500), nullable=False)
    # INDEXED / EMPTY (readable, no text) / UNSUPPORTED / FAILED
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    embedding_model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    indexed_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('INDEXED', 'EMPTY', 'UNSUPPORTED', 'FAILED')",
            name="status",
        ),
    )

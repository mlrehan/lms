"""Permission-Aware Vector Retrieval Engine.

Enforces zero-trust row-level scoping and staff-restricted media filtering
prior to vector cosine matching.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.client import OpenAIClient, get_openai_client
from backend.core.logging import get_logger
from backend.models.ai_embedding import ResourceEmbedding
from backend.models.identity.user import User
from backend.models.resource import Resource
from backend.core.errors import NotFoundError
from backend.ai.config import get_ai_settings
from backend.services.resource_service import ResourceService

# Bounds on one search: chunks considered, and distinct files whose access is
# checked. Similarity is computed in Python over JSON vectors, so the first
# bound is what keeps a large library from making search slow.
_MAX_CANDIDATE_CHUNKS = 20_000
_MAX_FILES_CHECKED = 50

logger = get_logger(__name__)


@dataclass
class RetrievedChunk:
    """A matched document chunk with citation and similarity score."""

    chunk_id: str
    resource_id: int
    resource_name: str
    course_id: int | None
    batch_id: int | None
    is_restricted: bool
    text: str
    similarity: float
    chunk_index: int


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Calculate cosine similarity between two float vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class PermissionAwareRetriever:
    """Retrieves document chunks matching query while strictly enforcing caller RBAC and scoping."""

    def __init__(
        self,
        session: AsyncSession,
        client: OpenAIClient | None = None,
    ) -> None:
        self.session = session
        self.client = client or get_openai_client()

    async def search(
        self,
        *,
        query: str,
        user: User,
        course_id: int | None = None,
        limit: int = 5,
        min_similarity: float = 0.35,
    ) -> list[RetrievedChunk]:
        """Perform permission-aware semantic search over indexed learning resources."""
        # 1. Compute query embedding vector
        embeddings = await self.client.create_embeddings([query])
        if not embeddings:
            return []
        query_vector = embeddings[0]

        # 2. Candidates. Every filter here reads the live resource row, never a
        # value copied into the index when it was built: a file marked
        # staff-only, or deleted, after indexing must stop matching at once.
        # Only chunks from the current embedding model are comparable.
        resources = ResourceService(self.session)
        stmt = (
            select(ResourceEmbedding, Resource.public_id, Resource.name)
            .join(Resource, Resource.id == ResourceEmbedding.resource_id)
            .where(
                Resource.is_deleted.is_(False),
                ResourceEmbedding.embedding_model == get_ai_settings().openai_embedding_model,
            )
            .limit(_MAX_CANDIDATE_CHUNKS)
        )
        if not resources.may_see_restricted(user):
            stmt = stmt.where(Resource.is_restricted.is_(False))
        if course_id is not None:
            stmt = stmt.where(Resource.course_id == course_id)

        rows = (await self.session.execute(stmt)).all()
        if not rows:
            return []

        # 3. Rank, then admit each file through ResourceService.get -- the rule
        # the Resources screen uses, including direct shares and staff-only
        # material -- rather than a second, narrower copy of it here.
        ranked = sorted(
            ((_cosine_similarity(query_vector, chunk.embedding), chunk, public_id, name) for chunk, public_id, name in rows),
            key=lambda item: item[0],
            reverse=True,
        )
        allowed: dict[int, bool] = {}
        scored_chunks: list[RetrievedChunk] = []
        for sim, chunk, public_id, name in ranked:
            if sim < min_similarity or len(scored_chunks) >= limit:
                break
            if chunk.resource_id not in allowed:
                if len(allowed) >= _MAX_FILES_CHECKED:
                    break
                try:
                    await resources.get(public_id, actor=user)
                    allowed[chunk.resource_id] = True
                except NotFoundError:
                    allowed[chunk.resource_id] = False
            if not allowed[chunk.resource_id]:
                continue
            scored_chunks.append(
                RetrievedChunk(
                    chunk_id=str(chunk.public_id),
                    resource_id=chunk.resource_id,
                    resource_name=name or "Course Document",
                    course_id=chunk.course_id,
                    batch_id=chunk.batch_id,
                    is_restricted=chunk.is_restricted,
                    text=chunk.chunk_text,
                    similarity=round(sim, 4),
                    chunk_index=chunk.chunk_index,
                )
            )

        # Sort descending by similarity score and truncate to limit
        scored_chunks.sort(key=lambda c: c.similarity, reverse=True)
        return scored_chunks[:limit]


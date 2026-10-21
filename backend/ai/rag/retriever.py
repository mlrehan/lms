"""Permission-Aware Vector Retrieval Engine.

Enforces zero-trust row-level scoping and staff-restricted media filtering
prior to vector cosine matching.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.client import OpenAIClient, get_openai_client
from backend.ai.security import SecurityPolicyEngine
from backend.core.logging import get_logger
from backend.models.ai_embedding import ResourceEmbedding
from backend.models.identity.user import User
from backend.models.resource import Resource
from backend.services.scope import ScopeResolver

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

        # 2. Scope resolution
        resolver = ScopeResolver(self.session)
        visible_courses = await resolver.visible_course_ids(user)
        visible_batches = await resolver.visible_batch_ids(user)
        held_perms = SecurityPolicyEngine.caller_permissions(user)

        # Can caller see staff-restricted files?
        can_view_restricted = "resource.view_restricted" in held_perms or "institution.view_all" in held_perms

        # 3. Base SQL query constrained to caller scope
        stmt = (
            select(
                ResourceEmbedding,
                Resource.name.label("resource_name"),
            )
            .join(Resource, Resource.id == ResourceEmbedding.resource_id)
            .where(Resource.is_deleted.is_(False))
        )

        # Apply restricted materials filter
        if not can_view_restricted:
            stmt = stmt.where(ResourceEmbedding.is_restricted.is_(False))

        # Apply course scope filter
        if course_id is not None:
            if not visible_courses.allows(course_id):
                logger.warning("Caller %s attempted out-of-scope course RAG search: %d", user.public_id, course_id)
                return []
            stmt = stmt.where(ResourceEmbedding.course_id == course_id)
        elif not visible_courses.unrestricted:
            stmt = stmt.where(
                or_(
                    ResourceEmbedding.course_id.in_(visible_courses.ids),
                    ResourceEmbedding.batch_id.in_(visible_batches.ids),
                )
            )

        rows = (await self.session.execute(stmt)).all()
        if not rows:
            return []

        # 4. Rank candidate chunks by vector similarity
        scored_chunks: list[RetrievedChunk] = []
        for embedding_obj, res_name in rows:
            sim = _cosine_similarity(query_vector, embedding_obj.embedding)
            if sim >= min_similarity:
                scored_chunks.append(
                    RetrievedChunk(
                        chunk_id=str(embedding_obj.public_id),
                        resource_id=embedding_obj.resource_id,
                        resource_name=res_name or "Course Document",
                        course_id=embedding_obj.course_id,
                        batch_id=embedding_obj.batch_id,
                        is_restricted=embedding_obj.is_restricted,
                        text=embedding_obj.chunk_text,
                        similarity=round(sim, 4),
                        chunk_index=embedding_obj.chunk_index,
                    )
                )

        # Sort descending by similarity score and truncate to limit
        scored_chunks.sort(key=lambda c: c.similarity, reverse=True)
        return scored_chunks[:limit]


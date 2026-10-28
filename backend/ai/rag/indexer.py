"""Builds the course-material index the assistant searches.

Until this existed nothing wrote to `resource_embeddings`, so every search the
assistant made over course materials came back empty, however the question
was worded.

**What is pending** is decided from the data, not from hooks scattered
through the upload code (`pending_resource_ids`): a live resource with no
index state, or whose current file is not the one indexed (a new version was
uploaded), or whose chunks came from a different embedding model, or whose
last attempt failed long enough ago to retry. Deleted resources are never
indexed, and their chunks are never served -- retrieval checks the live row --
and are removed with the resource by the foreign key.

**Each resource is its own transaction.** One unreadable file must not undo
the files indexed before it, nor hold a lock while OpenAI computes embeddings
for the next.

**Chunks from a file that is no longer current are deleted, always** --
including when re-indexing fails -- so search never quotes a version of a
handout that has been replaced.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.ai.config import get_ai_settings
from backend.ai.rag.chunker import chunk_text
from backend.ai.rag.extract import extract_text, is_supported
from backend.core.logging import get_logger
from backend.models.ai_embedding import ResourceEmbedding
from backend.models.ai_index_state import ResourceIndexState
from backend.models.resource import Resource

logger = get_logger(__name__)

MAX_ATTEMPTS = 5
RETRY_AFTER = timedelta(hours=1)
_EMBED_BATCH = 64


async def pending_resource_ids(session: AsyncSession, *, limit: int, model: str) -> list[int]:
    """Resources whose index is missing, stale, from another model, or due a retry."""
    state = ResourceIndexState
    retry_due = and_(
        state.status == "FAILED",
        state.attempts < MAX_ATTEMPTS,
        state.updated_at < datetime.now(UTC) - RETRY_AFTER,
    )
    stmt = (
        select(Resource.id)
        .outerjoin(state, state.resource_id == Resource.id)
        .where(
            Resource.is_deleted.is_(False),
            Resource.path.is_not(None),
            or_(
                state.resource_id.is_(None),
                state.source_key != Resource.path,
                and_(state.status == "INDEXED", state.embedding_model != model),
                retry_due,
            ),
        )
        .order_by(Resource.id)
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars())


async def _read(storage: Any, key: str, max_bytes: int) -> bytes | None:
    """The stored bytes, or None if the file is larger than we will read."""
    buffer = bytearray()
    # `open_stream` is a coroutine that returns the iterator (the storage
    # protocol, as every other caller uses it), not an async generator itself.
    async for part in await storage.open_stream(key):
        buffer.extend(part)
        if len(buffer) > max_bytes:
            return None
    return bytes(buffer)


async def _record(
    session: AsyncSession, resource: Resource, *, status: str, model: str | None,
    chunks: int = 0, error: str | None = None, failed: bool = False,
) -> None:
    state = await session.get(ResourceIndexState, resource.id)
    if state is None:
        state = ResourceIndexState(resource_id=resource.id, attempts=0, chunk_count=0, source_key=resource.path)
        session.add(state)
    # A new file resets the attempt count: its predecessor's failures say
    # nothing about it.
    if state.source_key != resource.path:
        state.attempts = 0
    state.source_key = resource.path
    state.status = status
    state.embedding_model = model
    state.chunk_count = chunks
    state.error = error[:2000] if error else None
    state.attempts = state.attempts + 1 if failed else 0
    state.indexed_at = None if failed else datetime.now(UTC)
    state.updated_at = datetime.now(UTC)


async def index_resource(session: AsyncSession, resource_id: int, *, storage: Any, client: Any) -> str:
    """Index one resource in the caller's transaction. Returns the outcome status."""
    settings = get_ai_settings()
    model = settings.openai_embedding_model
    resource = await session.get(Resource, resource_id)
    if resource is None or resource.is_deleted or not resource.path:
        return "SKIPPED"

    # Whatever happens next, chunks of any earlier file are not served.
    await session.execute(delete(ResourceEmbedding).where(ResourceEmbedding.resource_id == resource.id))

    if not is_supported(resource.mime_type):
        await _record(session, resource, status="UNSUPPORTED", model=None, error=f"type {resource.mime_type}")
        return "UNSUPPORTED"
    if resource.size and resource.size > settings.rag_max_file_bytes:
        await _record(session, resource, status="UNSUPPORTED", model=None, error="file too large to index")
        return "UNSUPPORTED"

    try:
        data = await _read(storage, resource.path, settings.rag_max_file_bytes)
        if data is None:
            await _record(session, resource, status="UNSUPPORTED", model=None, error="file too large to index")
            return "UNSUPPORTED"
        extracted = extract_text(data, resource.mime_type)
        pieces = chunk_text(extracted.text)[: settings.rag_max_chunks_per_resource]
        if not pieces:
            await _record(session, resource, status="EMPTY", model=model)
            return "EMPTY"

        vectors: list[list[float]] = []
        for start in range(0, len(pieces), _EMBED_BATCH):
            vectors.extend(await client.create_embeddings(pieces[start:start + _EMBED_BATCH], model=model))
        if len(vectors) != len(pieces):
            raise ValueError(f"expected {len(pieces)} embeddings, received {len(vectors)}")
    except Exception as exc:  # noqa: BLE001 -- recorded, retried later, never raised into the loop
        logger.warning("Indexing resource %s failed: %s", resource.id, exc)
        await _record(session, resource, status="FAILED", model=model, error=str(exc), failed=True)
        return "FAILED"

    for index, (piece, vector) in enumerate(zip(pieces, vectors, strict=True)):
        session.add(ResourceEmbedding(
            resource_id=resource.id,
            chunk_index=index,
            chunk_text=piece,
            embedding=vector,
            embedding_model=model,
            dimensions=len(vector),
            course_id=resource.course_id,
            batch_id=resource.batch_id,
            is_restricted=bool(resource.is_restricted),
            metadata_json={"source_key": resource.path, "truncated": extracted.truncated},
        ))
    await _record(session, resource, status="INDEXED", model=model, chunks=len(pieces))
    return "INDEXED"


async def index_pending(
    session_factory: async_sessionmaker[AsyncSession], *, storage: Any, client: Any, limit: int
) -> dict[str, int]:
    """One pass: index up to `limit` pending resources, each in its own transaction."""
    model = get_ai_settings().openai_embedding_model
    async with session_factory() as session:
        ids = await pending_resource_ids(session, limit=limit, model=model)
    outcomes: dict[str, int] = {}
    for resource_id in ids:
        try:
            async with session_factory.begin() as session:
                status = await index_resource(session, resource_id, storage=storage, client=client)
        except Exception:  # noqa: BLE001
            logger.exception("Indexing resource %s raised; continuing with the rest", resource_id)
            status = "ERROR"
        outcomes[status] = outcomes.get(status, 0) + 1
    return outcomes


async def run_index_scheduler(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Index pending resources every `AI_RAG_INDEX_INTERVAL_SECONDS`, for ever."""
    from backend.ai.client import get_openai_client
    from backend.storage.factory import get_storage

    settings = get_ai_settings()
    client = get_openai_client()
    storage = get_storage()
    while True:
        # Wait first: a process that only lives briefly (a test client, a
        # restart loop) never makes a paid embedding call it did not need.
        await asyncio.sleep(settings.rag_index_interval_seconds)
        try:
            outcomes = await index_pending(
                session_factory, storage=storage, client=client, limit=settings.rag_index_batch_size
            )
            if outcomes:
                logger.info("Course-material index pass", extra={"outcomes": outcomes})
        except Exception:  # noqa: BLE001 -- a bad pass must not end the loop
            logger.exception("Course-material index pass failed")

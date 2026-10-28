"""Process-wide resources the AI layer borrows from the application.

Tools run inside a request and receive that request's session, which is right
for their own reads and writes. A few need something that outlives the request
-- the sync tool hands work to a background task -- and used to build a fresh
`DatabaseManager` (a whole engine and connection pool) on every call, which
was never disposed. The application's own engine is registered here at
startup instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass
class AIRuntime:
    session_factory: async_sessionmaker[AsyncSession]
    event_bus: Any = None


_runtime: AIRuntime | None = None


def configure_ai_runtime(*, session_factory: async_sessionmaker[AsyncSession], event_bus: Any = None) -> None:
    """Called once from the application lifespan."""
    global _runtime
    _runtime = AIRuntime(session_factory=session_factory, event_bus=event_bus)


@lru_cache(maxsize=1)
def _fallback_runtime() -> AIRuntime:
    """For a process that never ran the lifespan (a script, a test): one
    engine for the life of the process, not one per call."""
    from backend.core.config import get_settings
    from backend.db.manager import DatabaseManager

    db = DatabaseManager(get_settings().database, application_name="ai_runtime")
    return AIRuntime(session_factory=db.session_factory)


def get_ai_runtime() -> AIRuntime:
    return _runtime if _runtime is not None else _fallback_runtime()

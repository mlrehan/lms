from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.db.manager import DatabaseManager
from backend.realtime.bus import build_bus

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    db = DatabaseManager(
        settings.database,
        application_name=settings.app.name,
    )

    app.state.db = db

    # Built before the first request rather than lazily: `build_bus` refuses
    # the memory backend in a deployed environment, and a deployment that is
    # going to be refused should be refused at startup, not on whichever
    # request first opens a stream.
    app.state.event_bus = (
        build_bus(settings.realtime, deployed=settings.app.is_deployed)
        if settings.realtime.enabled
        else None
    )
    if app.state.event_bus is not None:
        logger.info(
            "Realtime enabled", extra={"backend": settings.realtime.backend.value}
        )

    # Fail fast on startup if the database is unreachable, rather than
    # accepting traffic and failing on the first request that needs it.
    await db.ping()

    try:
        yield
    finally:
        if app.state.event_bus is not None:
            await app.state.event_bus.close()
        await db.dispose()

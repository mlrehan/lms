import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.db.manager import DatabaseManager
from backend.realtime.bus import build_bus
from backend.realtime.presence import build_presence_store
from backend.services.sync_pipeline_service import SyncPipelineService
from backend.services.sync_schedule import run_sync_scheduler

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

    # Presence rides on the realtime heartbeat, so it exists exactly when the
    # stream does. Built here for the same reason as the bus: the memory
    # adapter is refused in a deployed environment, and that refusal belongs at
    # startup rather than on whichever request first asks who is online.
    app.state.presence = (
        build_presence_store(settings.realtime, deployed=settings.app.is_deployed)
        if settings.realtime.enabled
        else None
    )

    # Fail fast on startup if the database is unreachable, rather than
    # accepting traffic and failing on the first request that needs it.
    await db.ping()

    scheduler_task: asyncio.Task[None] | None = None
    if settings.lait.is_configured:
        sync_service = SyncPipelineService(
            db.session_factory,
            settings,
            event_bus=app.state.event_bus,
        )
        try:
            await sync_service.current()
        except Exception:
            logger.exception("Failed to reap stale sync runs on startup")
        scheduler_task = asyncio.create_task(
            run_sync_scheduler(db.session_factory, sync_service)
        )
        app.state.sync_scheduler_task = scheduler_task
        logger.info("Automatic sync background scheduler task started")
    else:
        app.state.sync_scheduler_task = None

    try:
        yield
    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
        if app.state.event_bus is not None:
            await app.state.event_bus.close()
        if getattr(app.state, "presence", None) is not None:
            await app.state.presence.close()
        await db.dispose()

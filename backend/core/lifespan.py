from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.core.config import get_settings
from backend.db.manager import DatabaseManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    db = DatabaseManager(
        settings.database,
        application_name=settings.app.name,
    )

    app.state.db = db

    # Fail fast on startup if the database is unreachable, rather than
    # accepting traffic and failing on the first request that needs it.
    await db.ping()

    try:
        yield
    finally:
        await db.dispose()

"""FastAPI application entry point.

Run with:

    uvicorn backend.main:app --reload

Everything this module wires together already existed as isolated, correctly
designed pieces (settings validation, structured logging, the database
lifecycle, request-context middleware, the AppError hierarchy) -- none of it
was previously connected to an actual `FastAPI()` instance, so none of it
could be exercised by a real request. This is that connection.
"""

from __future__ import annotations

import asyncio
import sys

# psycopg's async mode cannot run under Windows' default ProactorEventLoop
# (it needs select()/poll(), which Proactor doesn't implement) -- this must
# be set before any event loop is created, i.e. before uvicorn (or anything
# else async) starts, or every database call fails with
# "Psycopg cannot use the 'ProactorEventLoop' to run in async mode."
# No-op on any other platform.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from backend.api.middleware import RequestContextMiddleware
from backend.api.router import router
from backend.core.config import get_settings
from backend.core.errors import AppError, ServiceUnavailableError
from backend.core.lifespan import lifespan
from backend.core.logging import configure_logging, get_logger
from backend.db.manager import DatabaseManager

settings = get_settings()
configure_logging(settings.logging)
logger = get_logger(__name__)

app = FastAPI(
    title=settings.app.name,
    version=settings.app.version,
    debug=settings.app.debug,
    lifespan=lifespan,
)

# Order matters: Starlette runs middleware in reverse of the order added, so
# TrustedHostMiddleware (reject unknown Host headers outright) sits outside
# CORS, which sits outside request-context tagging/logging.
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.api.trusted_hosts)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Every deliberately-raised error already knows its own status code and
    a safe-to-display message; this just puts that on the wire."""
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Anything that isn't an AppError is a bug, not an expected outcome --
    log the real exception server-side, but never echo its detail to the
    client."""
    logger.exception("Unhandled exception", extra={"path": request.url.path})
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."},
    )


@app.get("/livez")
async def liveness() -> dict:
    """Dependency-free liveness probe -- must never fail because of the
    database, or a Postgres blip would take down every pod's liveness check
    and trigger a mass, unnecessary restart."""
    return {"status": "alive"}


@app.get("/readyz")
async def readiness(request: Request) -> JSONResponse:
    """Readiness probe: actually pings Postgres through the pool this
    process would use to serve a real request -- proof the session layer
    works, not just that the process is running."""
    db: DatabaseManager = request.app.state.db
    try:
        await db.ping()
    except Exception as exc:  # noqa: BLE001 - readiness must report, never crash
        raise ServiceUnavailableError("Database is not reachable.") from exc
    return JSONResponse({"status": "ready"})


app.include_router(router, prefix=settings.api.prefix)


def _serve() -> None:
    """Run the ASGI server on an event loop psycopg can actually use.

    Setting `WindowsSelectorEventLoopPolicy` (top of this file) is not
    sufficient here: `uvicorn.run()` builds its own loop and does not
    reliably honour the policy, so the server came up on a ProactorEventLoop
    and every database call failed at startup with psycopg's
    "cannot use the 'ProactorEventLoop'" error -- while the same code worked
    fine under the test client, which does honour it.

    Constructing the loop explicitly through `asyncio.Runner(loop_factory=...)`
    removes the guesswork: this is the loop the server gets, whatever any
    policy says. On non-Windows platforms the default loop is already
    selector-based, so `loop_factory` stays None and nothing changes.
    """
    import selectors

    import uvicorn

    config = uvicorn.Config(
        app,
        host=settings.server.host,
        port=settings.server.port,
        log_config=None,  # keep our own structured JSON logging
    )
    server = uvicorn.Server(config)

    loop_factory = None
    if sys.platform == "win32":
        def loop_factory():  # type: ignore[misc]
            return asyncio.SelectorEventLoop(selectors.SelectSelector())

    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(server.serve())


if __name__ == "__main__":
    _serve()

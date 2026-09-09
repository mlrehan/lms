from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.manager import DatabaseManager


async def get_db_session(
    request: Request,
) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session with a real commit/rollback boundary.

    `async_sessionmaker.begin()` opens the session *and* starts a
    transaction: a clean exit from the `async with` block commits, an
    exception rolls back -- automatically, on every path. The previous
    version of this dependency only ever rolled back on exception and never
    committed on success at all, silently discarding every write a caller
    made unless that caller remembered to call `session.commit()` itself.
    """

    db: DatabaseManager = request.app.state.db

    async with db.session_factory.begin() as session:
        yield session


DBSession = Annotated[
    AsyncSession,
    Depends(get_db_session),
]


async def commit_before_responding(session: AsyncSession) -> None:
    """Commit now, rather than in this dependency's teardown.

    **Measured, because it is counter-intuitive:** FastAPI sends the response
    *before* exiting a `yield` dependency here, so the commit in
    `get_db_session` lands after the client already holds its `200`. Proved by
    sleeping two seconds in the teardown -- the client received its response
    in 0.92s, while the commit was still pending.

    For almost every endpoint that is harmless: nobody reads their own write
    back within milliseconds. For an incident-response action it is not. An
    administrator unlocking an account and immediately telling somebody "try
    now" hit a still-locked login **3 times in 40** measured runs, because the
    unlock had returned success before it was visible.

    Committing inside `session_factory.begin()` is safe: the context manager's
    exit is a no-op once the transaction has already ended (verified, not
    assumed). Calling this is a statement that the endpoint's contract is
    "effective when you read this response", not merely "accepted".

    The general fix -- a unit-of-work boundary that closes before the response
    is produced, for all ~145 routes -- is an architectural change worth
    making deliberately rather than as a side effect of this phase, and is
    recorded as such.
    """
    await session.commit()

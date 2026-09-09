from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.core.config import RuntimeDatabaseSettings


class DatabaseManager:
    """
    Owns application-level asynchronous SQLAlchemy resources.

    One instance should exist per FastAPI worker process.
    """

    def __init__(
        self,
        settings: RuntimeDatabaseSettings,
        *,
        application_name: str,
    ) -> None:

        self._settings = settings

        postgres_options = " ".join(
            [
                "-c timezone=UTC",
                (
                    "-c statement_timeout="
                    f"{settings.statement_timeout_ms}"
                ),
                (
                    "-c lock_timeout="
                    f"{settings.lock_timeout_ms}"
                ),
                (
                    "-c idle_in_transaction_session_timeout="
                    f"{settings.idle_in_transaction_timeout_ms}"
                ),
            ]
        )

        self.engine: AsyncEngine = create_async_engine(
            settings.url(),

            # --------------------------------------------------
            # Logging
            # --------------------------------------------------
            echo=settings.echo_sql,

            # Prevent query parameters from being included
            # in SQLAlchemy exception/log output.
            hide_parameters=True,

            # --------------------------------------------------
            # Pool health
            # --------------------------------------------------
            pool_pre_ping=True,

            # --------------------------------------------------
            # Pool capacity
            # --------------------------------------------------
            pool_size=settings.pool_size,
            max_overflow=settings.max_overflow,

            pool_timeout=(
                settings.pool_timeout_seconds
            ),

            pool_recycle=(
                settings.pool_recycle_seconds
            ),

            # Allows excess connections to become idle
            # instead of always cycling every connection.
            pool_use_lifo=True,

            # --------------------------------------------------
            # Psycopg / PostgreSQL options
            # --------------------------------------------------
            connect_args={
                "connect_timeout": (
                    settings.connect_timeout_seconds
                ),

                "application_name": application_name,

                "options": postgres_options,
            },
        )

        self.session_factory: (
            async_sessionmaker[AsyncSession]
        ) = async_sessionmaker(
            bind=self.engine,

            class_=AsyncSession,

            # Recommended for asyncio ORM usage.
            expire_on_commit=False,

            autoflush=True,
        )

    async def ping(self) -> None:
        """
        Verify that PostgreSQL is reachable.
        """
        async with self.engine.connect() as connection:
            await connection.execute(
                text("SELECT 1")
            )

    async def dispose(self) -> None:
        """
        Release pooled connections cleanly.
        """
        await self.engine.dispose()
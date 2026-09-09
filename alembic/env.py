from __future__ import annotations

import logging
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.pool import NullPool

from backend.core.config import get_migration_database_settings
from backend.models.base import Base

# =============================================================================
# MODEL REGISTRATION
# =============================================================================
#
# IMPORTANT:
#
# Alembic autogenerate can only see models whose Table objects have already
# been registered in Base.metadata.
#
# Therefore this import must cause ALL SQLAlchemy model modules to be imported.
#
# backend/models/__init__.py imports every mapped model used by the
# application (identity, course/batch, enrollment, attendance, resources,
# assignments, quizzes, exams, grade book, certificates/badges,
# notifications/messaging, audit, geo, administration).
#
# The imported name is intentionally unused; importing it performs model
# registration as a side effect.
#

from backend import models as _models  # noqa: F401, E402


# =============================================================================
# ALEMBIC CONFIGURATION
# =============================================================================

config = context.config
logger = logging.getLogger("alembic.env")


# =============================================================================
# LOGGING
# =============================================================================
#
# Use the logging configuration defined in alembic.ini when available.
#
# disable_existing_loggers=False is important when Alembic is invoked from
# another Python process because we do not want fileConfig() to unexpectedly
# disable application loggers.
#

if config.config_file_name is not None:
    fileConfig(
        config.config_file_name,
        disable_existing_loggers=False,
    )


# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================
#
# CRITICAL SECURITY BOUNDARY:
#
# This loads ONLY:
#
#     DATABASE_HOST
#     DATABASE_PORT
#     DATABASE_NAME
#     DATABASE_SSL_MODE
#     DATABASE_CONNECT_TIMEOUT_SECONDS
#     DATABASE_MIGRATION_USERNAME
#     DATABASE_MIGRATION_PASSWORD
#     DATABASE_MIGRATION_APPLICATION_NAME
#
# It does NOT load the normal FastAPI Settings object and therefore does not
# require:
#
#     DATABASE_RUNTIME_PASSWORD
#     SECURITY_JWT_SECRET
#     SECURITY_MASTER_ENCRYPTION_KEY
#     MAIL_PASSWORD
#     STORAGE_R2_SECRET_ACCESS_KEY
#

db_settings = get_migration_database_settings()

migration_url = db_settings.url()


# =============================================================================
# AUTOGENERATE METADATA
# =============================================================================

target_metadata = Base.metadata


# =============================================================================
# AUTOGENERATE SAFETY
# =============================================================================


def process_revision_directives(
    migration_context: Any,
    revision: Any,
    directives: list[Any],
) -> None:
    """
    Prevent Alembic from creating empty migration files when
    --autogenerate detects no schema changes.

    This only affects:

        alembic revision --autogenerate

    It does NOT prevent explicitly requested blank migrations such as:

        alembic revision -m "manual data migration"

    Manual revisions remain available for data migrations and other
    hand-written operations.
    """

    cmd_opts = config.cmd_opts

    if cmd_opts is None:
        return

    if not getattr(cmd_opts, "autogenerate", False):
        return

    if not directives:
        return

    script = directives[0]

    upgrade_ops = getattr(
        script,
        "upgrade_ops",
        None,
    )

    if (
        upgrade_ops is not None
        and upgrade_ops.is_empty()
    ):
        directives.clear()

        logger.info(
            "No schema changes detected; "
            "no migration revision was generated."
        )


# =============================================================================
# COMMON ALEMBIC CONFIGURATION
# =============================================================================


def configure_context(
    *,
    connection: Connection | None = None,
    url: Any | None = None,
    literal_binds: bool = False,
) -> None:
    """
    Configure Alembic consistently for both online and offline migration modes.

    PostgreSQL is our target database, so batch rendering is deliberately not
    enabled.

    compare_type=True
        Detect changes such as:
            VARCHAR(100) -> VARCHAR(255)
            Integer -> BigInteger

    compare_server_default=True
        Detect server-side default changes such as:
            now()
            true
            generated database defaults

    include_schemas=False
        Limit autogeneration to the application's default schema.

        If this application later intentionally manages multiple PostgreSQL
        schemas, change this deliberately and introduce an include_name or
        include_object filter.
    """

    options: dict[str, Any] = {
        "target_metadata": target_metadata,

        # -------------------------------------------------------------
        # Schema comparison
        # -------------------------------------------------------------

        "compare_type": True,
        "compare_server_default": True,

        # -------------------------------------------------------------
        # Schema scope
        # -------------------------------------------------------------

        "include_schemas": False,

        # -------------------------------------------------------------
        # Revision generation
        # -------------------------------------------------------------

        "process_revision_directives": process_revision_directives,

        # -------------------------------------------------------------
        # Migration version table
        # -------------------------------------------------------------

        "version_table": "alembic_version",

        # -------------------------------------------------------------
        # SQL rendering
        # -------------------------------------------------------------

        "literal_binds": literal_binds,
    }

    if connection is not None:
        options["connection"] = connection

    if url is not None:
        options["url"] = url

    if literal_binds:
        options["dialect_opts"] = {
            "paramstyle": "named",
        }

    context.configure(**options)


# =============================================================================
# OFFLINE MIGRATIONS
# =============================================================================


def run_migrations_offline() -> None:
    """
    Run Alembic in offline / SQL-generation mode.

    Example:

        alembic upgrade head --sql

    No database connection is created.

    The migration URL comes directly from MigrationDatabaseSettings rather
    than alembic.ini, ensuring the configuration remains centralized.

    We pass the SQLAlchemy URL object directly rather than converting it to a
    string. This avoids accidental password masking or manual URL encoding
    problems.
    """

    logger.info(
        "Running Alembic migrations in offline mode."
    )

    configure_context(
        url=migration_url,
        literal_binds=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# =============================================================================
# ONLINE MIGRATIONS
# =============================================================================


def create_migration_engine() -> Engine:
    """
    Create the synchronous SQLAlchemy engine used only for migrations.

    Alembic is intentionally synchronous here.

    Psycopg 3 supports both:

        create_async_engine(...)
            -> FastAPI runtime

    and:

        create_engine(...)
            -> Alembic migrations

    using the same:

        postgresql+psycopg

    SQLAlchemy dialect.

    NullPool is intentional because Alembic is normally a short-lived
    deployment/CI process and does not need the application's persistent
    connection pool.
    """

    return create_engine(
        migration_url,

        # Migrations do not need a persistent QueuePool.
        poolclass=NullPool,

        # Validate connection before SQL execution.
        pool_pre_ping=True,

        # Never echo migration SQL through SQLAlchemy's engine logger
        # merely because the application has debugging enabled.
        echo=False,
    )


def run_migrations_online() -> None:
    """
    Run Alembic using a real PostgreSQL connection.

    The engine always uses DATABASE_MIGRATION_* credentials.

    Transaction ownership is delegated to Alembic. PostgreSQL supports
    transactional DDL for the majority of ordinary schema migration
    operations, and Alembic's dialect determines the appropriate behavior.

    The Engine is disposed explicitly even if migration execution raises an
    exception.
    """

    logger.info(
        "Running Alembic migrations in online mode."
    )

    engine = create_migration_engine()

    try:
        with engine.connect() as connection:

            configure_context(
                connection=connection,
            )

            with context.begin_transaction():
                context.run_migrations()

    finally:
        engine.dispose()


# =============================================================================
# ENTRYPOINT
# =============================================================================

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
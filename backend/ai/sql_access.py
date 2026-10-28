"""What the Super Admin's SQL tool may touch, and the connection it reads through.

**Reads go through a dedicated PostgreSQL role**, not the application's
account. Pattern-matching a query is a second line at best -- the application
account here is often a superuser, for whom a SELECT can call functions that
read server files or end other sessions. The role (`lms_ai_readonly`) is
created by `python -m backend.cli.create_ai_readonly_role` with:

* SELECT on every table **except** those below, and on every column except
  the withheld ones -- granted by name, never by default privileges, so a table
  added later is invisible to the role until the command is run again
  (deny by default, rather than "allowed until somebody remembers");
* no INSERT, UPDATE or DELETE grant on anything. That -- not the read-only
  default below -- is what makes it unable to write: a session can switch
  `default_transaction_read_only` off, and then finds it holds no write
  privilege anyway (proven against the live role);
* `default_transaction_read_only = on` and a short statement timeout, set on
  the role itself;
* no superuser, CREATEDB, CREATEROLE or inherited rights, so it cannot read
  server files (`pg_read_file` is refused) or end another role's sessions
  (`pg_terminate_backend` is refused for them).

**Writes are never made by this role.** A confirmed change runs on the
application's own connection, inside the request's transaction, after every
check in `sql_change_tool.py`.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from backend.ai.config import get_ai_settings
from backend.core.config import get_settings

# Whole tables the role is never granted: credentials, session tokens, push
# keys, and the confirmation tickets of the assistant itself.
WITHHELD_TABLES = frozenset({
    "tokens",
    "google_connections",
    "push_subscriptions",
    "ai_confirmation_tickets",
})

# Columns withheld from otherwise readable tables: each is a credential or a
# capability (a share token is a working link to a file).
WITHHELD_COLUMNS = frozenset({
    ("users", "hashed_password"),
    ("resources", "share_token"),
    ("webhook_endpoints", "secret"),
    ("calendar_feeds", "token_hash"),
})

# Tables a SQL change may never write to. The audit trail exists to
# constrain administrators; permissions decide what everyone may do; the
# others are infrastructure the application owns outright.
WRITE_PROTECTED_TABLES = frozenset({
    "audit_logs",
    "permissions",
    "role_permissions",
    "roles",
    "user_roles",
    "alembic_version",
    *WITHHELD_TABLES,
})

READONLY_STATEMENT_TIMEOUT_MS = 5000


def readonly_configured() -> bool:
    return bool(get_ai_settings().sql_readonly_password.get_secret_value())


@lru_cache(maxsize=1)
def get_readonly_engine() -> AsyncEngine:
    """One small pool for the read-only role, for the life of the process."""
    ai = get_ai_settings()
    url = get_settings().database._build_url(
        username=ai.sql_readonly_username,
        password=ai.sql_readonly_password,
        application_name="lms-ai-readonly",
    )
    return create_async_engine(url, pool_size=2, max_overflow=2, pool_pre_ping=True, hide_parameters=True)

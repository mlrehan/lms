"""Create (or refresh) the read-only PostgreSQL role the AI SQL tool reads through.

    AI_SQL_READONLY_PASSWORD=... python -m backend.cli.create_ai_readonly_role

Idempotent: re-run it after every migration that adds a table, because grants
are made table by table and column by column rather than through default
privileges -- a table nobody has granted stays invisible to the role. That is
the point: a new table holding something sensitive is withheld until someone
runs this, instead of exposed until someone notices.

The password comes from the environment, never an argument (which would land
in shell history and the process list). It runs as the migration account,
which needs CREATEROLE and ownership of the tables.
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine, text

from backend.ai.config import get_ai_settings
from backend.ai.sql_access import READONLY_STATEMENT_TIMEOUT_MS, WITHHELD_COLUMNS, WITHHELD_TABLES
from backend.core.config import get_migration_database_settings


def _ident(name: str) -> str:
    """Quote an identifier. Names come from the catalogue, but quote anyway."""
    return '"' + name.replace('"', '""') + '"'


def plan(conn, role: str) -> list[str]:  # noqa: ANN001
    """The GRANT statements for every readable table and column, from the live catalogue."""
    rows = conn.execute(text(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"
    )).all()
    tables: dict[str, list[str]] = {}
    for table, column in rows:
        tables.setdefault(table, []).append(column)

    statements = []
    for table, columns in tables.items():
        if table in WITHHELD_TABLES:
            continue
        allowed = [c for c in columns if (table, c) not in WITHHELD_COLUMNS]
        if len(allowed) == len(columns):
            statements.append(f"GRANT SELECT ON {_ident(table)} TO {_ident(role)}")
        else:
            cols = ", ".join(_ident(c) for c in allowed)
            statements.append(f"GRANT SELECT ({cols}) ON {_ident(table)} TO {_ident(role)}")
    return statements


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="Print the grants without applying them.")
    args = parser.parse_args(argv)

    ai = get_ai_settings()
    role = ai.sql_readonly_username
    password = os.environ.get("AI_SQL_READONLY_PASSWORD") or ai.sql_readonly_password.get_secret_value()
    if not password and not args.dry_run:
        print("AI_SQL_READONLY_PASSWORD is not set; refusing to create a role without a password.", file=sys.stderr)
        return 2

    engine = create_engine(get_migration_database_settings().url())
    with engine.begin() as conn:
        database = conn.execute(text("SELECT current_database()")).scalar_one()
        grants = plan(conn, role)
        if args.dry_run:
            for statement in grants:
                print(statement)
            return 0

        exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar()
        verb = "ALTER" if exists else "CREATE"
        # The statement is composed by the server's format() from bound values
        # (%I quotes the name, %L the password), so a quote in the password
        # cannot break out of the literal. Python never pastes it into SQL.
        statement = conn.execute(
            text(
                "SELECT format('" + verb + " ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOINHERIT NOREPLICATION', CAST(:role AS text), CAST(:pw AS text))"
            ),
            {"role": role, "pw": password},
        ).scalar_one()
        conn.execute(text(statement))
        conn.execute(text(f"ALTER ROLE {_ident(role)} SET default_transaction_read_only = on"))
        conn.execute(text(f"ALTER ROLE {_ident(role)} SET statement_timeout = {int(READONLY_STATEMENT_TIMEOUT_MS)}"))
        conn.execute(text(f"GRANT CONNECT ON DATABASE {_ident(database)} TO {_ident(role)}"))
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {_ident(role)}"))
        # Start from nothing every run, so a table or column withheld since the
        # last run is actually taken away rather than left granted.
        conn.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {_ident(role)}"))
        for statement in grants:
            conn.execute(text(statement))
    engine.dispose()
    print(f"Role {role}: {verb.lower()}d; SELECT granted on {len(grants)} table(s); "
          f"{len(WITHHELD_TABLES)} table(s) and {len(WITHHELD_COLUMNS)} column(s) withheld.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

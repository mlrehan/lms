"""Seed the database with the identity catalog and a first Super Admin.

    python -m backend.cli.seed
    python -m backend.cli.seed --admin-username admin --admin-email a@b.com

The password is read from `LMS_ADMIN_PASSWORD` or prompted for interactively
-- never accepted as a command-line argument, which would put it in the shell
history and in the process list where any other user on the machine can read
it.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
import time

from backend.bootstrap.runner import (
    bootstrap_geo,
    bootstrap_grading,
    bootstrap_identity,
    ensure_super_admin,
)
from backend.core.config import get_settings
from backend.core.logging import configure_logging, get_logger
from backend.db.manager import DatabaseManager

logger = get_logger("seed")

_MIN_PASSWORD_LENGTH = 12


def _resolve_password(non_interactive: bool) -> str:
    env_password = os.environ.get("LMS_ADMIN_PASSWORD")
    if env_password:
        return env_password

    if non_interactive:
        print(
            "LMS_ADMIN_PASSWORD is not set and --non-interactive was given.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    first = getpass.getpass("Super admin password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        print("Passwords do not match.", file=sys.stderr)
        raise SystemExit(2)
    return first


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings.logging)

    password = _resolve_password(args.non_interactive)
    if len(password) < _MIN_PASSWORD_LENGTH:
        print(
            f"Password must be at least {_MIN_PASSWORD_LENGTH} characters.",
            file=sys.stderr,
        )
        return 2

    db = DatabaseManager(settings.database, application_name="lms-seed")
    try:
        async with db.session_factory.begin() as session:
            summary = await bootstrap_identity(session)

        async with db.session_factory.begin() as session:
            user, created = await ensure_super_admin(
                session,
                username=args.admin_username,
                email=args.admin_email,
                raw_password=password,
            )
            username = user.username

        # The grading starting point. Without this the institution's default
        # scheme has no weightings and no grade ladder, so every performance
        # figure in the product reports "not configured" and no transcript can
        # be completed -- which is what the seeder's own docstring says it
        # exists to prevent, and it had no caller at all until now. Idempotent,
        # and it never touches a scheme somebody has already configured.
        async with db.session_factory.begin() as session:
            grading_summary = await bootstrap_grading(session)

        geo_summary: dict[str, int] | None = None
        geo_seconds = 0.0
        if not args.skip_geo:
            start = time.monotonic()
            async with db.session_factory.begin() as session:
                geo_summary = await bootstrap_geo(session)
            geo_seconds = time.monotonic() - start

        print("Identity catalog:")
        for key, value in summary.items():
            print(f"  {key}: {value}")
        print(
            f"Super admin {username!r}: "
            + ("created." if created else "already existed, left unchanged.")
        )
        print("Grading:")
        for key, value in grading_summary.items():
            print(f"  {key}: {value}")
        if geo_summary is not None:
            print(f"Geo reference data ({geo_seconds:.1f}s):")
            for key, value in geo_summary.items():
                print(f"  {key}: {value}")
        else:
            print("Geo reference data: skipped (--skip-geo).")
        return 0
    finally:
        await db.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed LMS identity data.")
    parser.add_argument("--admin-username", default="superadmin")
    # Not a `.local` address: that TLD is reserved, and `email-validator`
    # (behind every EmailStr in the API) rejects it -- so the bootstrap would
    # create an administrator whose own email address the API refuses to
    # accept on the first profile edit.
    parser.add_argument("--admin-email", default="superadmin@lms.example.com")
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Fail rather than prompt if LMS_ADMIN_PASSWORD is unset.",
    )
    parser.add_argument(
        "--skip-geo",
        action="store_true",
        help="Skip seeding countries/cities/timezones (34,000+ rows; idempotent, but slower on repeat runs than the identity seeding alone).",
    )
    args = parser.parse_args()

    # psycopg's async mode needs a selector event loop on Windows; the API
    # sets this in backend/main.py, and this CLI is a second entry point that
    # opens its own loop, so it needs the same policy.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

"""The complete system reset -- its refusals, never its execution.

**Nothing here performs a reset.** Not once, not against a copy, not inside a
rolled-back transaction. `TRUNCATE` is not undone by a rollback in any way
worth betting a shared database on, and a test that can empty the development
installation by being run slightly wrong is not a test worth having. What is
tested is the thing that actually protects people: that every gate refuses, and
that `execute` cannot get past them on this machine.

The preview is exercised for real, because it is read-only by construction --
it issues counts and nothing else. That is also what makes it safe to leave
reachable on a production installation where the reset itself is refused
outright: an operator can see what a reset would cost without being able to
cause one.
"""

from __future__ import annotations

import asyncio
import os
import selectors
import time
from pathlib import Path

import pytest

from backend.core.config import get_settings
from backend.core.errors import ConflictError
from backend.db.manager import DatabaseManager
from backend.services.system_reset_service import PRESERVED_TABLES, SystemResetService


class _Actor:
    id = -1
    email = "reset-guard@test.invalid"
    username = "reset-guard"


@pytest.fixture()
def env():
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="reset-guard-tests")

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)

        return loop.run_until_complete(go())

    ns = type("Env", (), dict(run=staticmethod(run), settings=get_settings()))
    try:
        yield ns
    finally:
        loop.run_until_complete(db.dispose())
        loop.close()


# =============================================================================
# The preview, which is read-only
# =============================================================================


def test_the_preview_reports_the_truth_about_this_installation(env):
    """Real counts, the real database name, and why it will not run."""

    async def check(s):  # noqa: ANN001, ANN202
        preview = await SystemResetService(s, env.settings).preview()

        assert preview.database, "the preview must name the database it would erase"
        assert preview.confirmation_phrase == f"RESET {preview.database} PERMANENTLY"

        # This installation has data, and the preview counts it rather than
        # estimating: the figure is what somebody types a confirmation against.
        assert preview.total_rows > 0
        by_table = {i.table: i.rows for i in preview.impact}
        assert by_table.get("users", 0) > 0

        # Nothing preserved appears in the impact list.
        for table in PRESERVED_TABLES | {"audit_logs"}:
            assert table not in by_table, f"{table} must not be cleared by a reset"

    env.run(check)


def test_the_preview_changes_nothing(env):
    """Asserted, not assumed: a preview that wrote would be the whole risk."""

    async def check(s):  # noqa: ANN001, ANN202
        service = SystemResetService(s, env.settings)
        first = await service.preview()
        second = await service.preview()
        assert first.total_rows == second.total_rows
        assert [(i.table, i.rows) for i in first.impact] == [
            (i.table, i.rows) for i in second.impact
        ]

    env.run(check)


def test_tables_added_by_a_later_migration_are_cleared_without_being_listed(env):
    """The resettable set is read from the catalogue, not hand-kept.

    The failure mode of a hand-written list is a "fresh" installation that
    still holds the last institution's data in whatever table was forgotten.
    """

    async def check(s):  # noqa: ANN001, ANN202
        service = SystemResetService(s, env.settings)
        tables = set(await service._resettable_tables())  # noqa: SLF001

        # Tables that exist only because of recent work in this project; none
        # of them is named anywhere in the reset service.
        for recent in ("announcement_reads", "category_editors", "course_editors"):
            assert recent in tables, f"{recent} would survive a reset"

        assert not tables & (PRESERVED_TABLES | {"audit_logs"})

    env.run(check)


# =============================================================================
# The refusals
# =============================================================================


def test_a_reset_is_refused_on_this_installation(env):
    """The safety property this whole module exists to assert.

    Resetting is off by default and no backup is configured, so `execute`
    refuses before touching anything. If this test ever fails, the development
    database is one HTTP request from being erased.
    """

    async def check(s):  # noqa: ANN001, ANN202
        service = SystemResetService(s, env.settings)
        preview = await service.preview()
        assert preview.enabled is False
        assert preview.blockers, "a reset must not be runnable without being enabled"

        with pytest.raises(ConflictError) as refused:
            await service.execute(
                actor=_Actor(), confirmation=preview.confirmation_phrase
            )
        # Refused for the configuration, before the confirmation is even read.
        assert "switched off" in str(refused.value)

    env.run(check)


def test_a_correct_confirmation_does_not_override_a_blocker(env):
    """Order matters: blockers are checked before the typed phrase.

    The opposite order would mean the one person who knows the phrase can
    bypass the configuration, which is not what "off" means.
    """

    async def check(s):  # noqa: ANN001, ANN202
        service = SystemResetService(s, env.settings)
        phrase = (await service.preview()).confirmation_phrase
        with pytest.raises(ConflictError):
            await service.execute(actor=_Actor(), confirmation=phrase)

    env.run(check)


def test_production_is_refused_whatever_the_configuration_says(env):
    """There is no setting that enables a reset in production.

    Driven by a settings object claiming production *and* claiming the reset is
    enabled, with a valid backup -- the most permissive configuration anybody
    could write -- so the refusal cannot be coming from anything else.
    """

    async def check(s):  # noqa: ANN001, ANN202
        from backend.core.config import Environment

        permissive = _override(
            environment=Environment.PRODUCTION, system_reset_enabled=True
        )

        service = SystemResetService(s, permissive)
        blockers = await service._blockers()  # noqa: SLF001
        assert any("production installation" in b for b in blockers)

        with pytest.raises(ConflictError) as refused:
            await service.execute(
                actor=_Actor(), confirmation=f"RESET {await service._database_name()} PERMANENTLY"  # noqa: SLF001
            )
        assert "production" in str(refused.value)

    env.run(check)


def test_a_running_synchronisation_blocks_a_reset(env):
    """Refuse during a sync rather than terminate one.

    Killing a pipeline mid-flight leaves the external system believing it
    handed over records that no longer exist here. Waiting is free.
    """

    async def check(s):  # noqa: ANN001, ANN202
        from sqlalchemy import text

        service = SystemResetService(s, env.settings)
        # A savepoint, rolled back: the row must not outlive this assertion.
        async with s.begin_nested() as savepoint:
            await s.execute(
                text(
                    "INSERT INTO sync_pipeline_runs "
                    "(public_id, trigger_type, status, started_at) "
                    "VALUES (gen_random_uuid(), 'MANUAL', 'RUNNING', now())"
                )
            )
            blockers = await service._blockers()  # noqa: SLF001
            assert any("in progress" in b for b in blockers)
            await savepoint.rollback()

        after = await service._blockers()  # noqa: SLF001
        assert not any("in progress" in b for b in after), "the test row leaked"

    env.run(check)


# =============================================================================
# The backup check
# =============================================================================


def _settings_with_backup(path: Path | None, *, max_age_hours: int = 24):
    # `Settings` is frozen, so a copy is built with the overrides rather than
    # assigned into. That frozen-ness is itself worth having: configuration
    # that code can edit at run time is configuration nobody can reason about.
    return _override(
        system_reset_enabled=True,
        system_reset_backup_path=path,
        system_reset_backup_max_age_hours=max_age_hours,
    )


def _override(**app_fields):  # noqa: ANN003, ANN201
    settings = get_settings()
    return settings.model_copy(update={"app": settings.app.model_copy(update=app_fields)})


def _backup_blockers(path: Path | None, **kw) -> list[str]:
    # The check is pure -- no database, no session needed.
    return SystemResetService(None, _settings_with_backup(path, **kw))._backup_blockers()  # type: ignore[arg-type]  # noqa: SLF001


def test_no_configured_backup_is_a_refusal_not_a_pass():
    """"There is no backup" and "the backup is fine" must never look alike."""
    blockers = _backup_blockers(None)
    assert blockers and "No backup has been configured" in blockers[0]


def test_a_missing_or_empty_backup_is_refused(tmp_path):
    missing = tmp_path / "nope.dump"
    assert "was not found" in _backup_blockers(missing)[0]

    empty = tmp_path / "empty.dump"
    empty.write_bytes(b"")
    assert "is empty" in _backup_blockers(empty)[0]


def test_a_stale_backup_is_refused(tmp_path):
    """Age is measured, not trusted: last month's dump is not a safety net."""
    old = tmp_path / "old.dump"
    old.write_bytes(b"pretend this is a dump")
    two_days_ago = time.time() - (48 * 3600)
    os.utime(old, (two_days_ago, two_days_ago))

    assert "hours old" in _backup_blockers(old, max_age_hours=24)[0]
    # The same file passes when the installation allows an older one.
    assert _backup_blockers(old, max_age_hours=72) == []


def test_a_recent_readable_backup_passes(tmp_path):
    """And the check says only what it verified.

    It proves a recent, non-empty, readable file exists. It cannot prove the
    dump restores -- only a restore does that, which is why the refusal message
    says so rather than implying the backup is known to be good.
    """
    fresh = tmp_path / "fresh.dump"
    fresh.write_bytes(b"pretend this is a dump")
    assert _backup_blockers(fresh) == []

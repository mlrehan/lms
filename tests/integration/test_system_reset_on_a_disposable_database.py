"""The complete system reset, actually performed -- on a database it creates.

**Why this exists.** `test_system_reset_guards.py` proves every gate refuses.
That is the safety property, and it is not the same claim as "the reset works".
A reset that refuses correctly and then, once enabled, truncates the wrong
tables or leaves the installation with no administrator would pass every one of
those tests.

**Why it is safe.** Each test creates its own PostgreSQL database, migrates it,
seeds it, resets it, and drops it. The dev installation is never pointed at,
and `_assert_disposable()` re-checks the name against the configured database
before any statement runs -- so a copy-paste that aimed this at real data fails
on an assertion rather than on a `TRUNCATE`.

**Skipped rather than failed when it cannot create a database.** A CI role
without `CREATEDB` is a legitimate configuration, and a test that cannot
isolate itself must not fall back to a shared database.
"""

from __future__ import annotations

import asyncio
import os
import selectors
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.bootstrap.runner import bootstrap_identity, ensure_super_admin
from backend.core.config import get_migration_database_settings, get_settings
from backend.db.manager import DatabaseManager
from backend.security import password as pwd
from backend.services.system_reset_service import (
    PRESERVED_TABLES,
    SystemResetService,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _Actor:
    """The Super Admin performing the reset, as the service sees it.

    Carries the same three fields a real `User` supplies. The account itself is
    created inside the probe database by the fixture.
    """

    def __init__(self, user_id: int, username: str, email: str) -> None:
        self.id = user_id
        self.username = username
        self.email = email


def _assert_disposable(name: str) -> None:
    """Refuse to operate on anything that is not a database we just made.

    Checked immediately before every destructive step, not once at the top: the
    cost is nothing and the failure it prevents is unrecoverable.
    """
    configured = get_settings().database.name
    assert name.startswith("lms_reset_probe_"), f"{name} is not a probe database"
    assert name != configured, f"refusing to touch the configured database {configured}"


def _admin_url() -> str:
    """A URL for the `postgres` maintenance database, to CREATE/DROP from.

    `CREATE DATABASE` cannot run inside a transaction, and never from a
    connection to the database being created.
    """
    url = get_migration_database_settings().url().set(database="postgres")
    return url.render_as_string(hide_password=False).replace(
        "postgresql+psycopg", "postgresql+psycopg"
    )


@pytest.fixture()
def probe():
    """A migrated, seeded, disposable database. Dropped however the test ends."""
    name = f"lms_reset_probe_{uuid.uuid4().hex[:10]}"
    _assert_disposable(name)

    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    admin = create_async_engine(_admin_url(), isolation_level="AUTOCOMMIT")

    async def create() -> None:
        async with admin.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{name}"'))

    try:
        loop.run_until_complete(create())
    except Exception as exc:  # noqa: BLE001
        loop.run_until_complete(admin.dispose())
        loop.close()
        pytest.skip(f"cannot create a disposable database ({exc}); skipping rather than "
                    "falling back to a shared one")

    # Migrate it with the project's own Alembic configuration, so the probe has
    # the real schema -- triggers, constraints and all -- rather than one built
    # from `metadata.create_all`, which omits the hand-written SQL that the
    # append-only audit trigger lives in.
    env = {**os.environ, "DATABASE_NAME": name}
    migrated = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=600,
    )

    settings = get_settings()
    settings = settings.model_copy(
        update={"database": settings.database.model_copy(update={"name": name})}
    )
    db = DatabaseManager(settings.database, application_name="reset-probe")

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)

        return loop.run_until_complete(go())

    ns = type(
        "Probe", (), dict(
            name=name, settings=settings, run=staticmethod(run),
            migrated=migrated.returncode == 0,
            migration_output=(migrated.stderr or migrated.stdout)[-2000:],
        ),
    )
    try:
        if migrated.returncode != 0:
            pytest.fail(f"alembic upgrade head failed on the probe database:\n{ns.migration_output}")
        yield ns
    finally:
        loop.run_until_complete(db.dispose())

        async def drop() -> None:
            _assert_disposable(name)
            async with admin.connect() as conn:
                await conn.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :n AND pid <> pg_backend_pid()"
                    ),
                    {"n": name},
                )
                await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))

        loop.run_until_complete(drop())
        loop.run_until_complete(admin.dispose())
        loop.close()


def _backup_file(tmp_path: Path) -> Path:
    """A stand-in for a real dump.

    The backup check verifies a recent, non-empty, readable file -- it does not
    and cannot verify that a dump restores. A file here is therefore an honest
    exercise of exactly what the check claims to do, and the check's own
    message says as much.
    """
    path = tmp_path / "probe.dump"
    path.write_bytes(b"not a real dump; the check verifies presence, size and age")
    return path


def _enabled(settings, backup: Path):  # noqa: ANN001, ANN202
    return settings.model_copy(
        update={
            "app": settings.app.model_copy(
                update={"system_reset_enabled": True, "system_reset_backup_path": backup}
            )
        }
    )


async def _seed(s, probe) -> _Actor:  # noqa: ANN001
    """The catalogue, an administrator, and a little of everything else."""
    await bootstrap_identity(s)
    user, _ = await ensure_super_admin(
        s, username="probeadmin", email="probe@test.invalid", raw_password="probe-initial-pw"
    )
    await s.flush()

    course = int(
        (
            await s.execute(
                text(
                    "INSERT INTO courses (title, public_id, status) "
                    "VALUES ('Probe course', gen_random_uuid(), 'DRAFT') RETURNING id"
                )
            )
        ).scalar_one()
    )
    await s.execute(
        text(
            "INSERT INTO batches (batch_code, course_id, public_id) "
            "VALUES ('PROBE-1', :c, gen_random_uuid())"
        ),
        {"c": course},
    )
    await s.execute(
        text(
            "INSERT INTO tokens "
            "(user_id, token_hash, token_type, expires_at, revoked, public_id) "
            "VALUES (:u, 'probe-hash', 'REFRESH', now() + interval '1 day', false, "
            "gen_random_uuid())"
        ),
        {"u": user.id},
    )
    await s.flush()
    return _Actor(user.id, user.username, user.email or "probe@test.invalid")


async def _count(s, table: str) -> int:  # noqa: ANN001
    return int((await s.execute(text(f'SELECT count(*) FROM "{table}"'))).scalar_one())


# =============================================================================


def test_a_reset_empties_the_institution_and_keeps_the_catalogue(probe, tmp_path):
    """The whole operation, end to end, on a database made for it."""

    async def check(s):  # noqa: ANN001, ANN202
        actor = await _seed(s, probe)
        settings = _enabled(probe.settings, _backup_file(tmp_path))
        service = SystemResetService(s, settings)

        preview = await service.preview()
        assert preview.database == probe.name
        assert preview.enabled is True
        assert preview.blockers == [], preview.blockers
        assert preview.total_rows > 0

        _assert_disposable(probe.name)
        outcome = await service.execute(
            actor=actor, confirmation=preview.confirmation_phrase
        )

        # Institutional data is gone.
        for table in ("courses", "batches", "enrollments", "notifications"):
            assert await _count(s, table) == 0, f"{table} survived the reset"

        # The catalogue and the reference data are intact.
        assert await _count(s, "permissions") > 100
        assert await _count(s, "roles") == 6
        assert await _count(s, "role_permissions") > 100

        # Exactly one account, and it is the operator's, able to sign in.
        assert await _count(s, "users") == 1
        row = (
            await s.execute(
                text("SELECT username, hashed_password, status FROM users")
            )
        ).one()
        assert row.username == actor.username
        assert row.status == "ACTIVE"
        assert pwd.verify_password(row.hashed_password, outcome.bootstrap_password), (
            "the password the response showed must be the one that works"
        )
        assert outcome.bootstrap_password != "probe-initial-pw", (
            "a reset must not leave the erased system's password working"
        )

        # Every session was invalidated: the row count is reported and the rows
        # are gone.
        assert outcome.sessions_invalidated >= 1
        assert await _count(s, "tokens") == 0

        assert outcome.rows_deleted >= preview.total_rows - 1
        assert outcome.warnings, "the limits of what a reset clears must be stated"

    probe.run(check)


def test_the_reset_is_recorded_in_an_audit_trail_it_cannot_erase(probe, tmp_path):
    """`audit_logs` is append-only at the database, so the entry survives.

    This is also the test that would have caught the earlier draft offering a
    "clear the audit trail too" option: `trg_audit_logs_append_only` covers
    TRUNCATE, so that option could only ever have failed at run time.
    """

    async def check(s):  # noqa: ANN001, ANN202
        actor = await _seed(s, probe)
        before = await _count(s, "audit_logs")

        service = SystemResetService(s, _enabled(probe.settings, _backup_file(tmp_path)))
        preview = await service.preview()
        _assert_disposable(probe.name)
        await service.execute(actor=actor, confirmation=preview.confirmation_phrase)
        await s.flush()

        assert await _count(s, "audit_logs") > before, "the reset left no record"
        row = (
            await s.execute(
                text(
                    "SELECT entity_type, details FROM audit_logs "
                    "WHERE entity_type = 'system:reset' ORDER BY id DESC LIMIT 1"
                )
            )
        ).one()
        assert row.details["database"] == probe.name
        assert row.details["permanent"] is True
        assert row.details["rows_deleted_total"] > 0

        # And the trail genuinely cannot be emptied, by this or anything else.
        with pytest.raises(Exception) as refused:  # noqa: PT011
            async with s.begin_nested():
                await s.execute(text("TRUNCATE TABLE audit_logs"))
        assert "append-only" in str(refused.value)

    probe.run(check)


def test_identity_sequences_restart_so_the_installation_reads_as_new(probe, tmp_path):
    """`TRUNCATE ... RESTART IDENTITY`, which is why it is not a `DELETE`.

    A "fresh" installation whose first course is number 4,312 is not what
    anybody means by the word.
    """

    async def check(s):  # noqa: ANN001, ANN202
        actor = await _seed(s, probe)
        service = SystemResetService(s, _enabled(probe.settings, _backup_file(tmp_path)))
        preview = await service.preview()
        _assert_disposable(probe.name)
        await service.execute(actor=actor, confirmation=preview.confirmation_phrase)

        first = int(
            (
                await s.execute(
                    text(
                        "INSERT INTO courses (title, public_id, status) "
                        "VALUES ('After the reset', gen_random_uuid(), 'DRAFT') RETURNING id"
                    )
                )
            ).scalar_one()
        )
        assert first == 1, f"the first course after a reset should be 1, not {first}"

    probe.run(check)


def test_a_wrong_confirmation_phrase_resets_nothing(probe, tmp_path):
    """Proven where it can be proven: on a database that may be harmed.

    The guard suite asserts this refusal without ever calling `execute` against
    the dev installation. Here the call is made for real, and the data is still
    there afterwards.
    """

    async def check(s):  # noqa: ANN001, ANN202
        from backend.core.errors import ValidationError

        actor = await _seed(s, probe)
        service = SystemResetService(s, _enabled(probe.settings, _backup_file(tmp_path)))
        courses = await _count(s, "courses")
        assert courses > 0

        for wrong in (
            "RESET PERMANENTLY",
            "reset lms_platform_db permanently",
            f"RESET {probe.name} PERMANENTLY ",  # trailing space is stripped, so this one works
            "",
        ):
            if wrong.strip() == f"RESET {probe.name} PERMANENTLY":
                continue
            with pytest.raises(ValidationError):
                await service.execute(actor=actor, confirmation=wrong)

        assert await _count(s, "courses") == courses, "a refused reset changed data"
        assert await _count(s, "users") >= 1

    probe.run(check)


def test_a_stale_backup_stops_a_reset_that_would_otherwise_run(probe, tmp_path):
    """Everything else in place, and the backup alone refuses it.

    On the dev installation the reset is off anyway, so this is the only place
    the backup gate can be shown to be load-bearing rather than redundant.
    """

    async def check(s):  # noqa: ANN001, ANN202
        from backend.core.errors import ConflictError

        actor = await _seed(s, probe)
        stale = _backup_file(tmp_path)
        os.utime(stale, (0, 0))  # 1970

        service = SystemResetService(s, _enabled(probe.settings, stale))
        preview = await service.preview()
        assert preview.enabled is True
        assert any("hours old" in b for b in preview.blockers)

        with pytest.raises(ConflictError):
            await service.execute(
                actor=actor, confirmation=f"RESET {probe.name} PERMANENTLY"
            )
        assert await _count(s, "courses") > 0, "a blocked reset changed data"

    probe.run(check)


def test_each_gate_refuses_on_its_own_and_changes_nothing(probe, tmp_path):
    """Every blocker, exercised through a real `execute` call.

    The guard suite asserts these refusals against the dev installation
    *without* calling `execute`, because it must never be possible for a bad
    change to erase real data from a test. Here each one is driven through the
    real call, and the data is counted afterwards -- so the refusals are known
    to be load-bearing rather than merely present.
    """

    async def check(s):  # noqa: ANN001, ANN202
        from backend.core.config import Environment
        from backend.core.errors import ConflictError

        actor = await _seed(s, probe)
        backup = _backup_file(tmp_path)
        courses = await _count(s, "courses")
        phrase = f"RESET {probe.name} PERMANENTLY"

        def app(**fields):  # noqa: ANN003, ANN202
            base = _enabled(probe.settings, backup)
            return base.model_copy(update={"app": base.app.model_copy(update=fields)})

        cases = [
            ("production installation", app(environment=Environment.PRODUCTION)),
            ("switched off", app(system_reset_enabled=False)),
            ("No backup has been configured", app(system_reset_backup_path=None)),
        ]
        for expected, settings in cases:
            service = SystemResetService(s, settings)
            blockers = await service._blockers()  # noqa: SLF001
            assert any(expected in b for b in blockers), (expected, blockers)
            with pytest.raises(ConflictError) as refused:
                await service.execute(actor=actor, confirmation=phrase)
            assert expected in str(refused.value)
            assert await _count(s, "courses") == courses, f"{expected}: data changed"

        # A running synchronisation, which is a refusal rather than something
        # this operation terminates.
        await s.execute(
            text(
                "INSERT INTO sync_pipeline_runs "
                "(public_id, trigger_type, status, started_at) "
                "VALUES (gen_random_uuid(), 'MANUAL', 'RUNNING', now())"
            )
        )
        service = SystemResetService(s, _enabled(probe.settings, backup))
        assert any("in progress" in b for b in await service._blockers())  # noqa: SLF001
        with pytest.raises(ConflictError) as refused:
            await service.execute(actor=actor, confirmation=phrase)
        assert "in progress" in str(refused.value)
        assert await _count(s, "courses") == courses

        # And with every gate satisfied it goes through, so none of the above
        # is passing because a reset simply never runs.
        await s.execute(text("UPDATE sync_pipeline_runs SET status = 'SUCCESS'"))
        _assert_disposable(probe.name)
        await SystemResetService(s, _enabled(probe.settings, backup)).execute(
            actor=actor, confirmation=phrase
        )
        assert await _count(s, "courses") == 0

    probe.run(check)


def test_nothing_preserved_is_in_the_list_of_tables_to_clear(probe, tmp_path):
    """Asserted against the probe's real schema, not the dev installation's."""

    async def check(s):  # noqa: ANN001, ANN202
        service = SystemResetService(s, probe.settings)
        tables = set(await service._resettable_tables())  # noqa: SLF001
        assert tables, "the reset would clear nothing at all"
        assert not tables & (PRESERVED_TABLES | {"audit_logs"})

    probe.run(check)

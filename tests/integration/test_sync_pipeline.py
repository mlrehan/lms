"""The "Sync All Data" pipeline against real Postgres, with the steps faked.

The steps themselves are covered by their own suites; what is proved here is
the thing only the orchestrator can get wrong -- the order, the duplicate
guard, what happens to the steps after one fails, and what a retry does and
does not re-run.

The sync services are replaced with recorders, so a test can make step 2 fail
on demand. A live run cannot do that without breaking the upstream API, which
is why the browser pass could confirm the happy path and nothing else.

Rows are created under a unique trigger and removed afterwards; nothing else
in the database is touched.
"""

from __future__ import annotations

import asyncio
import selectors
from typing import Any

import pytest
from sqlalchemy import delete, select, text

from backend.core.config import get_settings
from backend.core.errors import ConflictError
from backend.db.manager import DatabaseManager
from backend.models.sync_pipeline import PIPELINE_STEPS, SyncPipelineJob, SyncPipelineRun
from backend.services import sync_pipeline_service as mod
from backend.services.sync_pipeline_service import ACADEMIC_STEPS, SyncPipelineService


class Recorder:
    """Stands in for the three step implementations."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_on: str | None = None

    def install(self, service: SyncPipelineService, monkeypatch: pytest.MonkeyPatch) -> None:
        async def users(job_id: int, trigger: str, actor_id: int | None) -> None:
            self.calls.append("USERS")
            if self.fail_on == "USERS":
                await service._finish_job(job_id, "FAILED", error="boom")  # noqa: SLF001
                raise mod._StepFailed("the user step failed")  # noqa: SLF001
            await service._finish_job(job_id, "COMPLETED", processed=3, succeeded=3, failed=0)  # noqa: SLF001

        async def managers(job_id: int, actor_id: int | None) -> None:
            self.calls.append("MANAGERS")
            if self.fail_on == "MANAGERS":
                await service._finish_job(job_id, "FAILED", error="boom")  # noqa: SLF001
                raise mod._StepFailed("the manager step failed")  # noqa: SLF001
            await service._finish_job(job_id, "COMPLETED", processed=5, succeeded=5, failed=0)  # noqa: SLF001

        async def academic(run_id: int, trigger: str, actor_id: int | None) -> None:
            self.calls.append("ACADEMIC")
            async with service._factory() as session:  # noqa: SLF001
                rows = (
                    await session.execute(
                        select(SyncPipelineJob.id, SyncPipelineJob.step).where(
                            SyncPipelineJob.pipeline_run_id == run_id,
                            SyncPipelineJob.step.in_(ACADEMIC_STEPS),
                        )
                    )
                ).all()
            if self.fail_on == "COURSES":
                for job_id, _step in rows:
                    await service._finish_job(job_id, "FAILED", error="boom")  # noqa: SLF001
                raise mod._StepFailed("the academic step failed")  # noqa: SLF001
            for job_id, _step in rows:
                await service._finish_job(  # noqa: SLF001
                    job_id, "COMPLETED", processed=7, succeeded=7, failed=0
                )

        monkeypatch.setattr(service, "_step_users", users)
        monkeypatch.setattr(service, "_step_managers", managers)
        monkeypatch.setattr(service, "_step_academic", academic)


@pytest.fixture()
def env(monkeypatch):  # noqa: ANN001, ANN201
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="pipeline-tests")
    service = SyncPipelineService(db.session_factory, get_settings())
    recorder = Recorder()
    recorder.install(service, monkeypatch)
    created: list[int] = []

    def start(trigger: str = "MANUAL") -> SyncPipelineRun:
        run = loop.run_until_complete(
            service.start(trigger_type=trigger, triggered_by_user_id=None)
        )
        created.append(run.id)
        return run

    def jobs(run_id: int) -> list[SyncPipelineJob]:
        async def go() -> list[SyncPipelineJob]:
            async with db.session_factory() as session:
                return list(
                    (
                        await session.execute(
                            select(SyncPipelineJob)
                            .where(SyncPipelineJob.pipeline_run_id == run_id)
                            .order_by(SyncPipelineJob.position)
                        )
                    ).scalars().all()
                )

        return loop.run_until_complete(go())

    ns = type(
        "Env", (),
        dict(
            loop=loop, db=db, service=service, recorder=recorder,
            start=staticmethod(start), jobs=staticmethod(jobs),
            run=staticmethod(lambda coro: loop.run_until_complete(coro)),
        ),
    )
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as session:
                if created:
                    await session.execute(
                        delete(SyncPipelineJob).where(
                            SyncPipelineJob.pipeline_run_id.in_(created)
                        )
                    )
                    await session.execute(
                        delete(SyncPipelineRun).where(SyncPipelineRun.id.in_(created))
                    )
                # Any row this test file left RUNNING would block every later run.
                await session.execute(
                    text("DELETE FROM sync_pipeline_runs WHERE status = 'RUNNING'")
                )

        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


# -- the order ---------------------------------------------------------------


def test_the_six_steps_are_laid_out_in_dependency_order(env):  # noqa: ANN001, ANN201
    run = env.start()
    assert [j.step for j in env.jobs(run.id)] == list(PIPELINE_STEPS)
    assert [j.position for j in env.jobs(run.id)] == [0, 1, 2, 3, 4, 5]
    assert {j.status for j in env.jobs(run.id)} == {"PENDING"}


def test_steps_run_in_that_order_and_the_academic_sync_runs_once(env):  # noqa: ANN001, ANN201
    """Courses, batches, sessions and enrolments are one academic run, so the
    three steps after COURSES must not each start another."""
    run = env.start()
    env.run(env.service.execute(run.id))
    assert env.recorder.calls == ["USERS", "MANAGERS", "ACADEMIC"]
    assert [j.status for j in env.jobs(run.id)] == ["COMPLETED"] * 6


def test_a_clean_run_is_completed_and_counts_up(env):  # noqa: ANN001, ANN201
    run = env.start()
    finished = env.run(env.service.execute(run.id))
    assert finished.status == "COMPLETED"
    assert sum(j.processed for j in env.jobs(run.id)) == 3 + 5 + 7 * 4


# -- duplicate prevention ----------------------------------------------------


def test_a_second_pipeline_cannot_start_while_one_runs(env):  # noqa: ANN001, ANN201
    """Refused by the partial unique index, not by a check in the service."""
    env.start()
    with pytest.raises(ConflictError):
        env.start()


def test_a_second_pipeline_can_start_once_the_first_has_finished(env):  # noqa: ANN001, ANN201
    """Otherwise the test above would pass against a button that only ever
    worked once."""
    first = env.start()
    env.run(env.service.execute(first.id))
    second = env.start()
    assert second.id != first.id


# -- failure -----------------------------------------------------------------


def test_a_failed_step_stops_the_ones_that_depend_on_it(env):  # noqa: ANN001, ANN201
    env.recorder.fail_on = "USERS"
    run = env.start()
    finished = env.run(env.service.execute(run.id))

    statuses = {j.step: j.status for j in env.jobs(run.id)}
    assert statuses["USERS"] == "FAILED"
    assert all(statuses[s] == "SKIPPED" for s in PIPELINE_STEPS[1:])
    # Nothing downstream was even attempted.
    assert env.recorder.calls == ["USERS"]
    assert finished.status == "FAILED"
    assert finished.failure_reason and "USERS" in finished.failure_reason


def test_a_failure_part_way_through_is_partial_not_failed(env):  # noqa: ANN001, ANN201
    """"Some of it worked" and "none of it did" are different facts, and the
    difference is whether a retry is worth pressing."""
    env.recorder.fail_on = "MANAGERS"
    run = env.start()
    finished = env.run(env.service.execute(run.id))
    statuses = {j.step: j.status for j in env.jobs(run.id)}
    assert statuses["USERS"] == "COMPLETED"
    assert statuses["MANAGERS"] == "FAILED"
    assert finished.status == "PARTIAL"


# -- retry -------------------------------------------------------------------


def test_retry_does_not_re_run_completed_steps(env):  # noqa: ANN001, ANN201
    env.recorder.fail_on = "MANAGERS"
    run = env.start()
    env.run(env.service.execute(run.id))
    assert env.recorder.calls == ["USERS", "MANAGERS"]

    env.recorder.fail_on = None
    env.recorder.calls.clear()
    retried = env.run(env.service.retry(run.public_id, triggered_by_user_id=None))
    env.run(env.service.execute(retried.id))

    # USERS had already succeeded, so it is not run again.
    assert env.recorder.calls == ["MANAGERS", "ACADEMIC"]
    assert [j.status for j in env.jobs(run.id)] == ["COMPLETED"] * 6


def test_retry_is_the_same_run_not_a_new_one(env):  # noqa: ANN001, ANN201
    """History stays one row per press; a retry continues it."""
    env.recorder.fail_on = "USERS"
    run = env.start()
    env.run(env.service.execute(run.id))
    retried = env.run(env.service.retry(run.public_id, triggered_by_user_id=None))
    assert retried.id == run.id
    assert len(env.jobs(run.id)) == 6


def test_retrying_a_run_whose_every_step_succeeded_is_refused(env):  # noqa: ANN001, ANN201
    run = env.start()
    env.run(env.service.execute(run.id))
    with pytest.raises(ConflictError):
        env.run(env.service.retry(run.public_id, triggered_by_user_id=None))


def test_retry_is_refused_while_another_pipeline_is_running(env):  # noqa: ANN001, ANN201
    env.recorder.fail_on = "USERS"
    failed = env.start()
    env.run(env.service.execute(failed.id))
    env.start()  # a second pipeline, now RUNNING
    with pytest.raises(ConflictError):
        env.run(env.service.retry(failed.public_id, triggered_by_user_id=None))


# -- progress ----------------------------------------------------------------


def test_progress_is_reported_as_the_run_goes(env):  # noqa: ANN001, ANN201
    """A bar that only moved at the end would be a spinner with extra steps."""
    from backend.schemas.sync_pipeline import SyncPipelineResponse

    run = env.start()
    assert SyncPipelineResponse.model_validate(env.run(env.service.get(run.id))).progress_percent == 0

    env.run(env.service.execute(run.id))
    done = SyncPipelineResponse.model_validate(env.run(env.service.get(run.id)))
    assert done.progress_percent == 100
    assert done.processed_total == 3 + 5 + 7 * 4
    assert done.failed_total == 0


def test_a_stale_running_pipeline_is_released(env):  # noqa: ANN001, ANN201
    """A process killed mid-run must not make the button unusable for ever."""
    run = env.start()

    async def age_it() -> None:
        async with env.db.session_factory.begin() as session:
            await session.execute(
                text(
                    "UPDATE sync_pipeline_runs SET started_at = now() - interval '30 days'"
                    " WHERE id = :id"
                ),
                {"id": run.id},
            )

    env.run(age_it())
    fresh = env.start()  # would raise ConflictError if the stale row still held the lock
    assert fresh.id != run.id

    stale = env.run(env.service.get(run.id))
    assert stale.status == "FAILED"
    assert stale.failure_reason and "Abandoned" in stale.failure_reason


def test_last_successful_counts_a_run_whose_steps_all_ran(env):  # noqa: ANN001, ANN201
    """A single unimportable record must not pin "last successful" to Never.

    Upstream has one manager with no email address, so every real run is
    PARTIAL. Reporting that as "never synchronised" would answer the
    operator's actual question with a falsehood.
    """
    run = env.start()
    env.run(env.service.execute(run.id))

    async def mark_one_record_failed() -> None:
        async with env.db.session_factory.begin() as session:
            await session.execute(
                text(
                    "UPDATE sync_pipeline_jobs SET failed = 1 WHERE pipeline_run_id = :id"
                    " AND step = 'MANAGERS'"
                ),
                {"id": run.id},
            )
            await session.execute(
                text("UPDATE sync_pipeline_runs SET status = 'PARTIAL' WHERE id = :id"),
                {"id": run.id},
            )

    env.run(mark_one_record_failed())
    last = env.run(env.service.last_successful())
    assert last is not None and last.id == run.id


def test_a_run_with_a_failed_step_is_not_counted_as_successful(env):  # noqa: ANN001, ANN201
    """Otherwise the test above would pass against a query that accepts anything."""
    env.recorder.fail_on = "MANAGERS"
    run = env.start()
    env.run(env.service.execute(run.id))
    last = env.run(env.service.last_successful())
    assert last is None or last.id != run.id


# -- who may synchronise at all ----------------------------------------------


def test_importing_from_lait_is_a_super_admin_capability():  # noqa: ANN201
    """Only the Super Admin may import from LAIT, by any route.

    One press creates accounts, courses, batches, sessions and enrolments
    across the whole institution from a system nobody here controls. Both
    grants are checked, not just the pipeline's combination: leaving an
    Administrator either one would let them achieve the same import in two
    presses from the Users and Batches screens, which is a gate that looks
    closed and is not.
    """
    from backend.core.permissions import ROLE_PERMISSIONS

    for role, grants in ROLE_PERMISSIONS.items():
        held = {"user.sync", "course.sync"} & set(grants)
        if role == "SUPER_ADMIN":
            assert held == {"user.sync", "course.sync"}, "the Super Admin must still be able to sync"
        else:
            assert not held, f"{role} must not be able to import from LAIT, but holds {sorted(held)}"


def test_the_google_calendar_sync_is_not_withdrawn_by_that():  # noqa: ANN201
    """It writes to a calendar, not to the institution's records, and an
    Administrator running the timetable needs it. Pinned so a later tidy-up
    does not sweep it in with the LAIT grants."""
    from backend.core.permissions import ROLE_PERMISSIONS

    assert "google.sync" in ROLE_PERMISSIONS["ADMIN"]


def test_an_administrator_still_runs_the_academic_office():  # noqa: ANN201
    """Otherwise the test above would pass against a role stripped of
    everything, which is not the change that was made."""
    from backend.core.permissions import ROLE_PERMISSIONS

    admin = set(ROLE_PERMISSIONS["ADMIN"])
    assert {"user.create", "course.create", "batch.create", "enrollment.create"} <= admin
    assert "managed_student.create" in admin  # manager assignments are still theirs


def test_the_database_agrees_with_the_catalogue_about_who_may_sync(env):  # noqa: ANN001, ANN201
    """The grants that actually gate a request are `role_permissions` **rows**.

    `core/permissions.py` is only the source for the seeder, so editing it
    changes nothing until `bootstrap_identity` runs. That is not hypothetical:
    the catalogue assertion above passed while a real Administrator session
    still got 202 from `POST /sync/all`, because the rows were untouched.

    This fails if a deployment forgets to reseed. The fix is to run it:

        python -m backend.cli.seed      (or bootstrap_identity directly)
    """
    async def granted() -> dict[str, set[str]]:
        async with env.db.session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT r.name, p.name FROM roles r"
                        " JOIN role_permissions rp ON rp.role_id = r.id"
                        " JOIN permissions p ON p.id = rp.permission_id"
                        " WHERE p.name IN ('user.sync', 'course.sync')"
                    )
                )
            ).all()
        out: dict[str, set[str]] = {}
        for role, permission in rows:
            out.setdefault(role, set()).add(permission)
        return out

    held = env.run(granted())
    assert held.get("SUPER_ADMIN") == {"user.sync", "course.sync"}, (
        "the Super Admin must still be able to import from LAIT"
    )
    others = {role: perms for role, perms in held.items() if role != "SUPER_ADMIN"}
    assert not others, (
        f"these roles still hold sync grants in the database: {others}. "
        "Re-run the identity bootstrap after editing core/permissions.py."
    )

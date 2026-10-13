""""Sync All Data": six steps, in the only order that can work.

The platform already had two synchronisations and no way to run them as one
operation. Pressed separately and in the wrong order they produce exactly the
failures the per-record error lists are full of -- a batch whose course does
not exist yet, an enrolment whose student has not been imported. This service
is the order, made explicit and recorded.

**What runs what.** Nothing here re-implements a synchronisation; each step
drives the service that already owns it:

    USERS        LaitSyncService              (students and tutors)
    MANAGERS     ManagerLinkSyncService       (corporate managers + their delegates)
    COURSES   ┐
    BATCHES   │  LaitAcademicSyncService      one run, reported as four steps
    SESSIONS  │
    ENROLLMENTS ┘

**The four academic steps share one transaction, and that is deliberate.**
`LaitAcademicSyncService` imports courses, batches, sessions and enrolments
atomically, which is what makes "a batch without its course" impossible. The
pipeline reports them as four jobs because that is what an operator watches,
and says so plainly: retrying any one of them re-runs the academic sync, which
is idempotent. Splitting the transaction to make them independently retryable
would trade a real guarantee for a cosmetic one.

**Duplicate runs are refused by Postgres, not by this code.** Both this table
and `user_sync_runs` carry a partial unique index over `status = 'RUNNING'`.
Two presses, two API processes, or a press racing the scheduled worker all
reach the same index and exactly one wins. A service that checked first would
be correct only until the second process existed.

**A failed step stops the ones that depend on it.** Remaining steps are marked
`SKIPPED` rather than attempted: importing enrolments after the user import
failed would attach people to the wrong things, or to nothing, and then report
hundreds of per-record errors that all have one cause.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.config import Settings
from backend.core.errors import ConflictError, NotFoundError
from backend.core.logging import get_logger
from backend.models.sync_pipeline import PIPELINE_STEPS, SyncPipelineJob, SyncPipelineRun
from backend.models.user_sync import UserSyncRun
from backend.services.lait_academic_sync_service import LaitAcademicSyncService
from backend.services.lait_sync_service import LaitSyncService
from backend.services.manager_link_sync import ManagerLinkSyncService

logger = get_logger("sync.pipeline")

# The four steps one academic run covers. Named once, because the orchestrator
# and the retry logic must agree about which steps share a run.
ACADEMIC_STEPS = ("COURSES", "BATCHES", "SESSIONS", "ENROLLMENTS")

# How often the in-flight counts are flushed to the database. The steps call
# back far more often than that -- once per batch -- and writing every call
# would put a transaction between the console and the work it is watching.
_PROGRESS_FLUSH_SECONDS = 1.0

# `user_sync_runs` has its own single-RUNNING-row lock, shared with the "Sync
# now" buttons on the Users and Batches screens. A Super Admin who presses one
# of those and then "Sync All Data" would otherwise lose a step to a conflict
# that resolves itself in under a minute -- so a step waits for the lock
# rather than failing the run. Bounded, because waiting for ever is just a
# hang with extra steps.
_LOCK_WAIT_SECONDS = 180.0
_LOCK_POLL_SECONDS = 3.0


class SyncPipelineService:
    def __init__(self, factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._factory = factory
        self._settings = settings

    # ---------------------------------------------------------------- lifecycle

    async def start(
        self, *, trigger_type: str, triggered_by_user_id: int | None
    ) -> SyncPipelineRun:
        """Claim the pipeline and lay out its six jobs, or refuse with 409."""
        await self._reap_stale()
        now = datetime.now(timezone.utc)
        try:
            async with self._factory.begin() as session:
                run = SyncPipelineRun(
                    trigger_type=trigger_type,
                    triggered_by_user_id=triggered_by_user_id,
                    status="RUNNING",
                    started_at=now,
                )
                session.add(run)
                await session.flush()
                for position, step in enumerate(PIPELINE_STEPS):
                    session.add(
                        SyncPipelineJob(
                            pipeline_run_id=run.id, step=step, position=position, status="PENDING"
                        )
                    )
                await session.flush()
                run_id = run.id
        except IntegrityError as exc:
            # The partial unique index on RUNNING. This is the duplicate guard.
            raise ConflictError("A synchronisation is already running.") from exc
        return await self.get(run_id)

    async def _reap_stale(self) -> None:
        """Release a pipeline left RUNNING by a process that died.

        Without this one crash makes the button permanently unusable, since the
        index would keep refusing every later run. The window is the same
        setting the single-run sync already uses.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=self._settings.lait.stale_run_minutes)
        async with self._factory.begin() as session:
            stale = (
                await session.execute(
                    select(SyncPipelineRun).where(
                        SyncPipelineRun.status == "RUNNING", SyncPipelineRun.started_at < cutoff
                    )
                )
            ).scalars().all()
            for run in stale:
                run.status = "FAILED"
                run.finished_at = datetime.now(timezone.utc)
                run.failure_reason = "Abandoned: the process running it stopped."
                await session.execute(
                    update(SyncPipelineJob)
                    .where(
                        SyncPipelineJob.pipeline_run_id == run.id,
                        SyncPipelineJob.status.in_(("PENDING", "RUNNING")),
                    )
                    .values(status="SKIPPED", finished_at=datetime.now(timezone.utc))
                )
                logger.warning("Reaped abandoned sync pipeline", extra={"run_id": run.id})

    async def retry(self, public_id: Any, *, triggered_by_user_id: int | None) -> SyncPipelineRun:
        """Re-run only what did not succeed.

        Steps already `COMPLETED` are left exactly as they are -- that is the
        point of retrying rather than pressing the button again. Everything
        else goes back to `PENDING` and the pipeline runs from the first of
        them, so a failure at step 2 does not re-import users.
        """
        await self._reap_stale()
        async with self._factory.begin() as session:
            run = (
                await session.execute(
                    select(SyncPipelineRun).where(SyncPipelineRun.public_id == public_id)
                )
            ).scalar_one_or_none()
            if run is None:
                raise NotFoundError("Synchronisation run not found.")
            if run.status == "RUNNING":
                raise ConflictError("That synchronisation is still running.")

            jobs = (
                await session.execute(
                    select(SyncPipelineJob).where(SyncPipelineJob.pipeline_run_id == run.id)
                )
            ).scalars().all()
            if all(job.status == "COMPLETED" for job in jobs):
                raise ConflictError("Every step of that run already succeeded.")

            # Another pipeline must not be running: the index would refuse this
            # update, so check first and give the honest 409 rather than a 500.
            clash = (
                await session.execute(
                    select(SyncPipelineRun.id).where(SyncPipelineRun.status == "RUNNING").limit(1)
                )
            ).first()
            if clash:
                raise ConflictError("A synchronisation is already running.")

            for job in jobs:
                if job.status != "COMPLETED":
                    job.status = "PENDING"
                    job.started_at = None
                    job.finished_at = None
                    job.error = None
                    job.processed = job.succeeded = job.failed = 0
            run.status = "RUNNING"
            run.started_at = datetime.now(timezone.utc)
            run.finished_at = None
            run.failure_reason = None
            if triggered_by_user_id is not None:
                run.triggered_by_user_id = triggered_by_user_id
            run_id = run.id
        return await self.get(run_id)

    # ---------------------------------------------------------------- execution

    async def execute(self, run_id: int) -> SyncPipelineRun:
        """Run every step that is not already complete, in order."""
        async with self._factory() as session:
            run = (
                await session.execute(select(SyncPipelineRun).where(SyncPipelineRun.id == run_id))
            ).scalar_one()
            actor_id = run.triggered_by_user_id
            trigger = run.trigger_type
            jobs = (
                await session.execute(
                    select(SyncPipelineJob)
                    .where(SyncPipelineJob.pipeline_run_id == run_id)
                    .order_by(SyncPipelineJob.position)
                )
            ).scalars().all()
            plan = [(job.id, job.step, job.status) for job in jobs]

        failure: str | None = None
        stopped = False

        for job_id, step, status in plan:
            if status == "COMPLETED":
                continue
            if stopped:
                await self._finish_job(job_id, "SKIPPED", error="An earlier step failed.")
                continue
            if step in ACADEMIC_STEPS and await self._already_done_by_academic(run_id, step):
                continue

            try:
                await self._run_step(run_id, job_id, step, trigger, actor_id)
            except Exception as exc:  # noqa: BLE001 - a run must always be finalised
                reason = _readable(exc)
                logger.exception("Sync step failed", extra={"step": step})
                await self._finish_job(job_id, "FAILED", error=reason)
                failure = failure or f"{step}: {reason}"
                stopped = True

        return await self._finalise(run_id, failure)

    async def _already_done_by_academic(self, run_id: int, step: str) -> bool:
        """True when this academic step was completed by the run just executed.

        One academic run completes all four, so the three that follow must not
        each start another one.
        """
        async with self._factory() as session:
            row = (
                await session.execute(
                    select(SyncPipelineJob.status).where(
                        SyncPipelineJob.pipeline_run_id == run_id, SyncPipelineJob.step == step
                    )
                )
            ).first()
        return bool(row and row[0] == "COMPLETED")

    async def _run_step(
        self, run_id: int, job_id: int, step: str, trigger: str, actor_id: int | None
    ) -> None:
        await self._start_job(job_id)

        if step == "USERS":
            await self._step_users(job_id, trigger, actor_id)
        elif step == "MANAGERS":
            await self._step_managers(job_id, actor_id)
        elif step in ACADEMIC_STEPS:
            await self._step_academic(run_id, trigger, actor_id)
        else:  # pragma: no cover - PIPELINE_STEPS and this branch list are one set
            raise RuntimeError(f"No implementation for sync step {step!r}")

    async def _start_waiting(self, start: Any, what: str) -> Any:
        """Claim an inner sync's run row, waiting out a competing one.

        The conflict is somebody else holding `user_sync_runs`'s RUNNING slot
        -- almost always a single "Sync now" press that is about to finish.
        Retrying is right because the condition is temporary and the work is
        idempotent; giving up would skip every step after it.
        """
        deadline = asyncio.get_running_loop().time() + _LOCK_WAIT_SECONDS
        while True:
            try:
                return await start()
            except ConflictError:
                if asyncio.get_running_loop().time() >= deadline:
                    raise ConflictError(
                        f"Another synchronisation held the lock for longer than "
                        f"{int(_LOCK_WAIT_SECONDS / 60)} minutes, so {what} did not run."
                    ) from None
                logger.info("Waiting for another synchronisation to finish", extra={"step": what})
                await asyncio.sleep(_LOCK_POLL_SECONDS)

    async def _step_users(self, job_id: int, trigger: str, actor_id: int | None) -> None:
        service = LaitSyncService(self._factory, self._settings)
        run = await self._start_waiting(
            lambda: service.start(
                trigger_type=trigger, triggered_by_user_id=actor_id, dry_run=False
            ),
            "the user import",
        )
        finished = await service.execute(run.id)
        stats = finished.stats or {}
        counts = _sum_counts(stats, ("students", "tutors"))
        await self._finish_job(
            job_id,
            "FAILED" if finished.status == "FAILED" else "COMPLETED",
            processed=counts["fetched"],
            succeeded=counts["created"] + counts["updated"] + counts["unchanged"],
            failed=counts["skipped"],
            detail=stats,
            error=finished.failure_reason,
            sync_run_id=finished.id,
        )
        if finished.status == "FAILED":
            raise _StepFailed(finished.failure_reason or "The user synchronisation failed.")

    async def _step_managers(self, job_id: int, actor_id: int | None) -> None:
        service = ManagerLinkSyncService(self._factory, self._settings)
        loop = asyncio.get_running_loop()
        flusher = _Throttle(loop, _PROGRESS_FLUSH_SECONDS)

        def progress(report: Any) -> None:
            flusher.maybe(
                lambda: self._touch_job(
                    job_id, report.processed, report.succeeded, report.failed
                )
            )

        report = await service.run(dry_run=False, actor_id=actor_id, on_progress=progress)
        await self._finish_job(
            job_id,
            "COMPLETED",
            processed=report.processed,
            succeeded=report.succeeded,
            failed=report.failed,
            detail=report.as_detail(),
        )

    async def _step_academic(self, run_id: int, trigger: str, actor_id: int | None) -> None:
        """One academic run, reported as four jobs as it goes."""
        async with self._factory() as session:
            rows = (
                await session.execute(
                    select(SyncPipelineJob.id, SyncPipelineJob.step).where(
                        SyncPipelineJob.pipeline_run_id == run_id,
                        SyncPipelineJob.step.in_(ACADEMIC_STEPS),
                    )
                )
            ).all()
        job_ids = {step: job_id for job_id, step in rows}

        loop = asyncio.get_running_loop()
        flusher = _Throttle(loop, _PROGRESS_FLUSH_SECONDS)
        latest: dict[str, dict[str, int]] = {}

        def on_stage(step: str, status: str, counts: dict[str, int]) -> None:
            latest[step] = counts
            job_id = job_ids.get(step)
            if job_id is None:
                return
            done = counts.get("created", 0) + counts.get("updated", 0) + counts.get("unchanged", 0)
            if status == "RUNNING":
                flusher.maybe(
                    lambda: self._touch_job(
                        job_id, _processed(counts, done), done, counts.get("skipped", 0), mark_running=True
                    )
                )
            else:
                # A completion is never throttled away: it is the state the
                # console stops on.
                flusher.now(
                    lambda: self._finish_job(
                        job_id, "COMPLETED",
                        processed=_processed(counts, done),
                        succeeded=done,
                        failed=counts.get("skipped", 0),
                        detail=counts,
                    )
                )

        service = LaitAcademicSyncService(self._factory, self._settings, on_stage=on_stage)
        run = await self._start_waiting(
            lambda: service.start(
                trigger_type=trigger, triggered_by_user_id=actor_id, dry_run=False
            ),
            "the course import",
        )
        finished = await service.execute(run.id)
        await flusher.drain()

        stats = finished.stats or {}
        # Whatever the stage callbacks did or did not deliver, the stored run is
        # the authority: every academic job is settled from it.
        for step in ACADEMIC_STEPS:
            job_id = job_ids.get(step)
            if job_id is None:
                continue
            counts = stats.get(step.lower()) or latest.get(step) or {}
            done = counts.get("created", 0) + counts.get("updated", 0) + counts.get("unchanged", 0)
            await self._finish_job(
                job_id,
                "FAILED" if finished.status == "FAILED" else "COMPLETED",
                processed=_processed(counts, done),
                succeeded=done,
                failed=counts.get("skipped", 0),
                detail=counts,
                error=finished.failure_reason,
                sync_run_id=finished.id,
            )
        if finished.status == "FAILED":
            raise _StepFailed(finished.failure_reason or "The academic synchronisation failed.")

    # ---------------------------------------------------------------- job writes

    async def _start_job(self, job_id: int) -> None:
        async with self._factory.begin() as session:
            await session.execute(
                update(SyncPipelineJob)
                .where(SyncPipelineJob.id == job_id)
                .values(status="RUNNING", started_at=datetime.now(timezone.utc))
            )

    async def _touch_job(
        self, job_id: int, processed: int, succeeded: int, failed: int, *, mark_running: bool = False
    ) -> None:
        """In-flight counts. Never changes a job that has already finished."""
        values: dict[str, Any] = {"processed": processed, "succeeded": succeeded, "failed": failed}
        if mark_running:
            values["status"] = "RUNNING"
            values["started_at"] = datetime.now(timezone.utc)
        async with self._factory.begin() as session:
            await session.execute(
                update(SyncPipelineJob)
                .where(
                    SyncPipelineJob.id == job_id,
                    SyncPipelineJob.status.in_(("PENDING", "RUNNING")),
                )
                .values(**values)
            )

    async def _finish_job(
        self,
        job_id: int,
        status: str,
        *,
        processed: int | None = None,
        succeeded: int | None = None,
        failed: int | None = None,
        detail: dict[str, Any] | None = None,
        error: str | None = None,
        sync_run_id: int | None = None,
    ) -> None:
        values: dict[str, Any] = {"status": status, "finished_at": datetime.now(timezone.utc)}
        if processed is not None:
            values["processed"] = processed
        if succeeded is not None:
            values["succeeded"] = succeeded
        if failed is not None:
            values["failed"] = failed
        if detail is not None:
            values["detail"] = detail
        if error is not None:
            values["error"] = error[:500]
        if sync_run_id is not None:
            values["sync_run_id"] = sync_run_id
        async with self._factory.begin() as session:
            await session.execute(
                update(SyncPipelineJob).where(SyncPipelineJob.id == job_id).values(**values)
            )

    async def _finalise(self, run_id: int, failure: str | None) -> SyncPipelineRun:
        async with self._factory.begin() as session:
            run = (
                await session.execute(select(SyncPipelineRun).where(SyncPipelineRun.id == run_id))
            ).scalar_one()
            jobs = (
                await session.execute(
                    select(SyncPipelineJob).where(SyncPipelineJob.pipeline_run_id == run_id)
                )
            ).scalars().all()

            if any(job.status in ("FAILED", "SKIPPED") for job in jobs):
                # "Some of it worked" is a different fact from "none of it did",
                # and the difference decides whether a retry is worth pressing.
                status = "PARTIAL" if any(j.status == "COMPLETED" for j in jobs) else "FAILED"
            elif any(job.failed for job in jobs):
                status = "PARTIAL"
            else:
                status = "COMPLETED"

            run.status = status
            run.finished_at = datetime.now(timezone.utc)
            run.failure_reason = failure[:300] if failure else None
        return await self.get(run_id)

    # ---------------------------------------------------------------- reads

    async def get(self, run_id: int) -> SyncPipelineRun:
        async with self._factory() as session:
            run = (
                await session.execute(
                    select(SyncPipelineRun).where(SyncPipelineRun.id == run_id)
                )
            ).scalar_one()
            session.expunge(run)
            return run

    async def by_public_id(self, public_id: Any) -> SyncPipelineRun:
        async with self._factory() as session:
            run = (
                await session.execute(
                    select(SyncPipelineRun).where(SyncPipelineRun.public_id == public_id)
                )
            ).scalar_one_or_none()
            if run is None:
                raise NotFoundError("Synchronisation run not found.")
            session.expunge(run)
            return run

    async def current(self) -> SyncPipelineRun | None:
        """The pipeline in flight, if any."""
        async with self._factory() as session:
            run = (
                await session.execute(
                    select(SyncPipelineRun).where(SyncPipelineRun.status == "RUNNING").limit(1)
                )
            ).scalar_one_or_none()
            if run is not None:
                session.expunge(run)
            return run

    async def last_successful(self) -> SyncPipelineRun | None:
        """The last run in which every step ran to completion.

        Deliberately *not* `status = 'COMPLETED'`. A run is marked PARTIAL when
        any single record could not be imported, and upstream has one manager
        with no email address -- so that one record would have pinned this to
        "Never" for ever, which answers the operator's real question ("when did
        data last come in?") with a falsehood. A run counts here when no step
        failed or was skipped; records that could not be imported are reported
        separately, by the Failed counter.
        """
        from sqlalchemy import exists

        unfinished = exists().where(
            SyncPipelineJob.pipeline_run_id == SyncPipelineRun.id,
            SyncPipelineJob.status.in_(("FAILED", "SKIPPED", "PENDING", "RUNNING")),
        )
        async with self._factory() as session:
            run = (
                await session.execute(
                    select(SyncPipelineRun)
                    .where(
                        SyncPipelineRun.status.in_(("COMPLETED", "PARTIAL")),
                        SyncPipelineRun.finished_at.is_not(None),
                        ~unfinished,
                    )
                    .order_by(SyncPipelineRun.finished_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if run is not None:
                session.expunge(run)
            return run


class _StepFailed(RuntimeError):
    """A step reported failure through its own run row rather than by raising."""


class _Throttle:
    """Runs at most one progress write per interval, and never concurrently.

    The stage callbacks are synchronous and fire inside the sync's own
    transaction, so each write is scheduled as a task rather than awaited. The
    in-flight flag stops a slow write from queueing behind itself.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, interval: float) -> None:
        self._loop = loop
        self._interval = interval
        self._last = 0.0
        self._pending: set[asyncio.Task[None]] = set()
        self._busy = False

    def maybe(self, make: Any) -> None:
        now = self._loop.time()
        if self._busy or now - self._last < self._interval:
            return
        self._last = now
        self.now(make)

    def now(self, make: Any) -> None:
        self._busy = True

        async def go() -> None:
            try:
                await make()
            except Exception:  # noqa: BLE001 - progress must never fail the work
                logger.exception("Progress write failed; the sync is unaffected")
            finally:
                self._busy = False

        task = self._loop.create_task(go())
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def drain(self) -> None:
        if self._pending:
            await asyncio.gather(*list(self._pending), return_exceptions=True)


def _processed(counts: dict[str, int], done: int) -> int:
    """How many records a step handled.

    `fetched` is the right answer for anything pulled from the feed, and zero
    for sessions, which are *generated* from each batch's schedule rather than
    fetched. Reporting "0 processed, 46 succeeded" for them was incoherent, so
    the work done stands in when nothing was fetched.
    """
    return counts.get("fetched", 0) or done


def _sum_counts(stats: dict[str, Any], keys: tuple[str, ...]) -> dict[str, int]:
    total = {"fetched": 0, "created": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    for key in keys:
        block = stats.get(key)
        if isinstance(block, dict):
            for name in total:
                value = block.get(name)
                if isinstance(value, int):
                    total[name] += value
    return total


def _readable(exc: Exception) -> str:
    """A short, storable reason. Never a traceback: these runs carry people's
    names and addresses, and the detail belongs in the log.

    `AppError` subclasses carry a message written for the person reading it,
    so they are passed through. Reporting one as "Unexpected ConflictError"
    turned "another synchronisation is already running" -- an ordinary,
    self-resolving condition -- into something that looked like a crash, which
    is exactly what happened in practice.
    """
    from backend.core.errors import AppError
    from backend.integrations.lait_client import LaitApiError

    if isinstance(exc, _StepFailed):
        return str(exc)[:300]
    if isinstance(exc, LaitApiError):
        return f"LAIT did not answer ({exc.status or 'no response'})"
    if isinstance(exc, AppError):
        return str(exc)[:300]
    return f"Unexpected {type(exc).__name__}"


async def latest_runs(
    session: AsyncSession, *, limit: int, offset: int
) -> tuple[list[SyncPipelineRun], int]:
    """History, newest first."""
    from sqlalchemy import func

    total = (
        await session.execute(select(func.count()).select_from(SyncPipelineRun))
    ).scalar_one()
    rows = (
        await session.execute(
            select(SyncPipelineRun)
            .order_by(SyncPipelineRun.started_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return list(rows), int(total)

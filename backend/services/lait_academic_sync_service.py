"""Synchronise courses, batches, sessions and enrolments from LAIT.

Same principles as the user sync (`lait_sync_service.py`), which it builds on:

* **Additive.** The feeds list what is current; absence means nothing. Nothing is
  deleted, archived or dropped because LAIT stopped mentioning it. The one
  exception is a generated session that has since left the schedule *and* has
  never been touched (no attendance, links or notes) -- that is derived data, and
  keeping a phantom class on a student's timetable would be the worse failure.
* **LAIT owns what LAIT sends; administrators own everything else.** Enrolment
  `status`, batch `capacity`, `meeting_link`, `recording_link` and a course's
  category once set are never overwritten.
* **A collision skips, it does not merge.** A different course that already has
  the title is reported, not adopted.
* **Deletions are respected.** A course an administrator deleted stays deleted.
* **Network first, then one transaction.** Every fetch happens before the
  database transaction opens, so a slow API never holds row locks. Each record then
  runs in its own savepoint: one bad batch skips itself. A dry run does the full
  work and rolls back.
* **Course status is derived, not stored from LAIT.** A course is RUNNING while
  one of its active batches is in progress and PUBLISHED otherwise; it is
  recomputed at the end of every run -- including a failed one, in its own
  transaction -- so a fetch failure cannot leave "running" courses stuck.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Protocol

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.config import Settings
from backend.core.logging import get_logger
from backend.integrations import lait_academic as ac
from backend.integrations import lait_mapping as m
from backend.integrations.lait_client import LaitApiError, LaitClient
from backend.integrations.lait_geo import GeoResolver
from backend.integrations.lait_pages import PageFetcher
from backend.models.administration import Category, CategoryEditor
from backend.models.attendance import Attendance
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.user import User
from backend.models.organization import Organization
from backend.models.user_sync import UserSyncRun
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.lait_sync_service import LaitSyncService, RunReport, SourceStats, _Skip
from backend.utils.enums import CourseStatus, EnrollmentStatus, Levels, Platforms

logger = get_logger("lait.academic")

_ACTIVE_ENROLLMENT = (EnrollmentStatus.PENDING, EnrollmentStatus.CONFIRMED, EnrollmentStatus.COMPLETED)
_PAGE_CONCURRENCY = 4


@dataclass
class Fetched:
    courses: list[dict[str, Any]] = field(default_factory=list)
    batches: list[dict[str, Any]] = field(default_factory=list)
    students: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # batch_code -> rows
    pages: dict[str, ac.CoursePage] = field(default_factory=dict)  # course url -> parsed page
    menu: list[ac.MenuCategory] = field(default_factory=list)


class StageReporter(Protocol):
    """Told when a phase starts and finishes, with that phase's counts.

    Deliberately a callback rather than a return value: the console needs to
    see "Batches: running, 18 of 26" while the transaction is still open, and
    nothing that returns at the end can say that.
    """

    def __call__(self, step: str, status: str, counts: dict[str, int]) -> None: ...


class LaitAcademicSyncService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        *,
        client: LaitClient | None = None,
        fetcher: PageFetcher | None = None,
        on_stage: "StageReporter | None" = None,
    ) -> None:
        self._factory = session_factory
        self._settings = settings
        self._client = client
        self._fetcher = fetcher
        # Optional, and ignored by every existing caller: the pipeline uses it
        # to show Courses, Batches, Sessions and Enrollments advancing
        # separately. The work itself is unchanged -- all four still happen in
        # one transaction, which is why a half-imported batch cannot exist.
        self._on_stage = on_stage
        self._users = LaitSyncService(session_factory, settings, client=client)

    # ------------------------------------------------------------------ lifecycle

    async def start(self, *, trigger_type: str, triggered_by_user_id: int | None, dry_run: bool) -> UserSyncRun:
        return await self._users.start(
            trigger_type=trigger_type, triggered_by_user_id=triggered_by_user_id, dry_run=dry_run, kind="ACADEMIC"
        )

    async def run(self, *, trigger_type: str, triggered_by_user_id: int | None, dry_run: bool) -> UserSyncRun:
        run = await self.start(trigger_type=trigger_type, triggered_by_user_id=triggered_by_user_id, dry_run=dry_run)
        return await self.execute(run.id)

    async def execute(self, run_id: int) -> UserSyncRun:
        report = _Report()
        failure: str | None = None

        async with self._factory() as session:
            run = (await session.execute(select(UserSyncRun).where(UserSyncRun.id == run_id))).scalar_one()
            dry_run, triggered_by = run.dry_run, run.triggered_by_user_id
            actor_id = triggered_by or await self._users._scheduled_actor(session)  # noqa: SLF001

        geo = GeoResolver(self._factory, dry_run=dry_run)
        try:
            if self._client is not None:
                await self._sync(self._client, report, geo, dry_run, actor_id)
            else:
                async with LaitClient(self._settings.lait) as client:
                    await self._sync(client, report, geo, dry_run, actor_id)
        except LaitApiError as exc:
            failure = f"LAIT API: {exc}"[:300]
            logger.warning("Academic sync aborted", extra={"reason": failure})
        except Exception as exc:  # noqa: BLE001 - a run must always be finalised
            failure = f"Unexpected {type(exc).__name__}"
            logger.exception("Academic sync crashed")

        if not dry_run:
            # Status follows the calendar, not the feed: refresh even when the sync failed.
            try:
                report.statuses = await refresh_course_statuses(self._factory)
            except Exception:  # noqa: BLE001
                logger.exception("Course status refresh failed")

        status = "FAILED" if failure else ("PARTIAL" if report.report.errors else "SUCCEEDED")
        stats = report.as_stats()
        async with self._factory.begin() as session:
            run = (await session.execute(select(UserSyncRun).where(UserSyncRun.id == run_id))).scalar_one()
            run.status = status
            run.finished_at = datetime.now(timezone.utc)
            run.stats = stats
            run.errors = report.report.errors
            run.failure_reason = failure
            audit_service.record(
                session,
                action=AuditAction.ACADEMIC_SYNC,
                actor_user_id=triggered_by,
                entity_type="user_sync_run",
                entity_id=run.id,
                success=failure is None,
                details={"trigger": run.trigger_type, "dry_run": dry_run, "status": status, **{k: stats[k] for k in ("courses", "batches", "sessions", "enrollments")}},
            )
            await session.flush()
            session.expunge(run)
        return run

    # ------------------------------------------------------------------ phases

    async def _sync(self, client: LaitClient, report: "_Report", geo: GeoResolver, dry_run: bool, actor_id: int | None) -> None:
        fetched = await self._fetch(client, report)

        async with self._factory() as session:
            cache = _Cache()
            await cache.load(session)
            self._stage("COURSES", "RUNNING", report.courses.as_dict())
            await self._courses(session, fetched, report, cache, actor_id)
            self._stage("COURSES", "COMPLETED", report.courses.as_dict())

            # Sessions are generated inside `_batch`, so the two advance
            # together and are reported together rather than pretending to be
            # sequential.
            self._stage("BATCHES", "RUNNING", report.batches.as_dict())
            self._stage("SESSIONS", "RUNNING", report.sessions.as_dict())
            touched: list[int] = []
            for payload in fetched.batches:
                batch_id = await self._batch(session, client, geo, fetched, payload, report, cache, dry_run, actor_id)
                if batch_id is not None:
                    touched.append(batch_id)
                self._stage("BATCHES", "RUNNING", report.batches.as_dict())
                self._stage("SESSIONS", "RUNNING", report.sessions.as_dict())
            self._stage("BATCHES", "COMPLETED", report.batches.as_dict())
            self._stage("SESSIONS", "COMPLETED", report.sessions.as_dict())

            self._stage("ENROLLMENTS", "RUNNING", report.enrollments.as_dict())
            await self._enrollments(session, client, geo, fetched, report, cache, dry_run, actor_id)
            self._stage("ENROLLMENTS", "COMPLETED", report.enrollments.as_dict())
            await self._recount(session, touched)
            report.statuses = await refresh_course_statuses(session, commit=False)
            if dry_run:
                await session.rollback()
            else:
                await session.commit()

    def _stage(self, step: str, status: str, counts: dict[str, int]) -> None:
        """Report a phase boundary. A reporter that raises must never be able to
        fail the synchronisation -- it is a progress display, not the work."""
        if self._on_stage is None:
            return
        try:
            self._on_stage(step, status, counts)
        except Exception:  # noqa: BLE001
            logger.exception("Stage reporter failed; the sync is unaffected")

    async def _fetch(self, client: LaitClient, report: "_Report") -> Fetched:
        f = Fetched()
        f.courses = await client.courses()
        f.batches = await client.batches_upcoming()
        report.courses.fetched, report.batches.fetched = len(f.courses), len(f.batches)

        for payload in f.batches:
            code = str(payload.get("batch_id"))
            try:
                f.students[code] = await client.batch_students(int(payload["batch_id"]))
            except (KeyError, TypeError, ValueError):
                f.students[code] = []
        report.enrollments.fetched = sum(len(v) for v in f.students.values())

        # Course pages: level, duration, prerequisites, and the category menu.
        hosts = self._settings.lait.course_page_hosts
        timeout = self._settings.lait.course_page_timeout_seconds
        owns = self._fetcher is None
        fetcher = self._fetcher or PageFetcher(hosts, timeout=timeout)
        try:
            sem = asyncio.Semaphore(_PAGE_CONCURRENCY)
            html_by_url: dict[str, str] = {}

            async def one(url: str) -> None:
                async with sem:
                    html = await fetcher.fetch(url)
                if html is not None:
                    html_by_url[url] = html

            urls = [str(c["course_url"]) for c in f.courses if c.get("course_url")]
            await asyncio.gather(*(one(u) for u in urls))
        finally:
            if owns:
                await fetcher.aclose()

        for url, html in html_by_url.items():
            f.pages[url] = ac.parse_course_page(html)
            if not f.menu:
                f.menu = ac.parse_category_menu(html)  # the menu is on every page; one is enough
        report.pages_fetched, report.pages_missing = len(html_by_url), len(urls) - len(html_by_url)
        return f

    # ------------------------------------------------------------------ courses

    async def _courses(self, session: AsyncSession, f: Fetched, report: "_Report", cache: "_Cache", actor_id: int | None) -> None:
        for payload in f.courses:
            external = str(payload.get("course_id"))
            try:
                async with session.begin_nested():
                    try:
                        mapped = ac.map_course(payload)
                    except m.MappingError as exc:
                        raise _Skip(str(exc)) from None
                    report.courses.warnings += len(mapped.warnings)
                    page = f.pages.get(mapped.course_link or "")
                    if mapped.course_link and page is None:
                        report.courses.warnings += 1
                    category = ac.choose_category(mapped.course_link, f.menu) if mapped.course_link and f.menu else None
                    outcome = await self._upsert_course(session, mapped, page, category, report, cache)
                setattr(report.courses, outcome, getattr(report.courses, outcome) + 1)
            except _Skip as exc:
                report.courses.skipped += 1
                report.report.error("course", external, str(exc))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Course record failed")
                report.courses.skipped += 1
                report.report.error("course", external, f"unexpected {type(exc).__name__}")

    async def _upsert_course(
        self, session: AsyncSession, mapped: ac.MappedCourse, page: ac.CoursePage | None,
        category_name: str | None, report: "_Report", cache: "_Cache",
    ) -> str:
        course = (await session.execute(select(Course).where(Course.code == mapped.external_id))).scalar_one_or_none()
        if course is not None and getattr(course, "is_deleted", False):
            raise _Skip("this course was deleted locally and is not restored by the sync")

        clash_query = select(Course.id).where(func.lower(Course.title) == mapped.title.lower())
        if course is not None:
            clash_query = clash_query.where(Course.id != course.id)
        if (await session.execute(clash_query.limit(1))).first():
            raise _Skip("a different course already has this title")

        duration = (page.duration_hours if page and page.duration_hours else None) or mapped.api_duration_hours
        level = Levels(page.level) if page and page.level else None
        prerequisites = page.prerequisites if page else None
        price = page.price if page else None
        outline = page.outline if page else None
        overview = page.overview if page else None
        category_id = await cache.category(session, category_name, report) if category_name else None
        now = datetime.now(timezone.utc)

        if course is None:
            course = Course(
                code=mapped.external_id, title=mapped.title, description=mapped.description,
                duration_hours=duration, course_link=mapped.course_link, course_image=mapped.course_image,
                small_course_image=mapped.small_course_image, prerequisites=prerequisites, price=price,
                outline=outline, overview=overview,
                level=level or Levels.BEGINNER, category_id=category_id, status=CourseStatus.PUBLISHED,
                created_at=now, updated_at=now,
            )
            course.batches, course.resources, course.tags, course.tutors = [], [], [], []  # MissingGreenlet guard
            session.add(course)
            await session.flush()
            cache.courses[mapped.external_id] = course.id
            return "created"

        changed = False
        for name, value in (
            ("title", mapped.title), ("description", mapped.description), ("duration_hours", duration),
            ("course_link", mapped.course_link), ("course_image", mapped.course_image),
            ("small_course_image", mapped.small_course_image), ("prerequisites", prerequisites), ("level", level),
            ("price", price), ("outline", outline), ("overview", overview),
        ):
            if name in ("course_image", "small_course_image") and _is_uploaded(getattr(course, name)):
                continue  # a picture an administrator uploaded is theirs; LAIT only refreshes URLs it supplied
            if value is not None and getattr(course, name) != value:
                setattr(course, name, value)
                changed = True
        if category_id is not None and course.category_id is None:  # an administrator's re-categorisation is kept
            course.category_id = category_id
            changed = True
        cache.courses[mapped.external_id] = course.id
        if changed:
            course.updated_at = now
            await session.flush()
        return "updated" if changed else "unchanged"

    # ------------------------------------------------------------------ batches + sessions

    async def _batch(
        self, session: AsyncSession, client: LaitClient, geo: GeoResolver, f: Fetched, payload: dict[str, Any],
        report: "_Report", cache: "_Cache", dry_run: bool, actor_id: int | None,
    ) -> int | None:
        external = str(payload.get("batch_id"))
        try:
            async with session.begin_nested():
                try:
                    mapped = ac.map_batch(payload, source_timezone=self._settings.lait.source_timezone)
                except m.MappingError as exc:
                    raise _Skip(str(exc)) from None
                report.batches.warnings += len(mapped.warnings)
                for w in mapped.warnings:
                    if "not recognised" in w:
                        report.report.error("batch", external, w)

                course_id = await self._course_for(session, mapped, cache)
                # A batch does not need its tutor to exist -- only its sessions do. So an
                # unresolvable tutor costs the sessions, not the batch.
                tutor_id: int | None = None
                tutor_problem: str | None = None
                try:
                    tutor_id = await self._tutor_for(session, client, geo, mapped, cache, dry_run, actor_id)
                except _Skip as exc:
                    tutor_problem = str(exc)
                batch_pk, outcome = await self._upsert_batch(session, mapped, course_id)
                await self._sessions(session, batch_pk, mapped, tutor_id, tutor_problem, report, external)
            setattr(report.batches, outcome, getattr(report.batches, outcome) + 1)
            return batch_pk
        except _Skip as exc:
            report.batches.skipped += 1
            report.report.error("batch", external, str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Batch record failed")
            report.batches.skipped += 1
            report.report.error("batch", external, f"unexpected {type(exc).__name__}")
        return None

    async def _course_for(self, session: AsyncSession, mapped: ac.MappedBatch, cache: "_Cache") -> int:
        known = cache.courses.get(mapped.external_course_id)
        if known:
            return known
        row = (await session.execute(select(Course.id).where(Course.code == mapped.external_course_id))).first()
        if row:
            cache.courses[mapped.external_course_id] = row[0]
            return row[0]
        # Not in the live-courses feed (e.g. an unpublished course with an upcoming batch):
        # insert the minimum the batch needs, as the spec asks, rather than dropping the batch.
        clash = (await session.execute(select(Course.id).where(func.lower(Course.title) == mapped.course_title.lower()).limit(1))).first()
        if clash:
            raise _Skip("its course is not in the live feed and another course already has that title")
        now = datetime.now(timezone.utc)
        course = Course(code=mapped.external_course_id, title=mapped.course_title[:255], level=Levels.BEGINNER,
                        status=CourseStatus.PUBLISHED, created_at=now, updated_at=now)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        session.add(course)
        await session.flush()
        cache.courses[mapped.external_course_id] = course.id
        return course.id

    async def _tutor_for(
        self, session: AsyncSession, client: LaitClient, geo: GeoResolver, mapped: ac.MappedBatch,
        cache: "_Cache", dry_run: bool, actor_id: int | None,
    ) -> int | None:
        if mapped.tutor_guid is None:
            raise _Skip("the batch names no tutor")
        key = str(mapped.tutor_guid)
        if key in cache.users:
            return cache.users[key]
        conds = [User.public_id == mapped.tutor_guid]
        if mapped.tutor_external_id is not None:
            conds.append(User.external_tutor_id == mapped.tutor_external_id)
        row = (await session.execute(select(User.id).where(or_(*conds)).limit(1))).first()
        if row:
            cache.users[key] = row[0]
            return row[0]

        detail = await client.tutor_by_guid(mapped.tutor_guid)
        if detail is None:
            raise _Skip("the tutor is not known to LAIT")
        try:
            tutor = m.map_tutor(detail)
        except m.MappingError as exc:
            raise _Skip(f"the tutor record is unusable ({exc})") from None
        m.apply_tutor_detail(tutor, detail)
        _outcome, user_id = await self._users.upsert_record(tutor, None, geo, dry_run, actor_id, 0)
        if user_id is not None:
            cache.users[key] = user_id
        return user_id  # None only in a dry run, where the tutor would have been created

    @staticmethod
    def _schedule_fields(mapped: ac.MappedBatch) -> dict[str, object]:
        """How the batch is scheduled, as the source states it (never overwritten with nothing)."""
        return {
            "training_days": mapped.training_days, "training_start_day": mapped.training_start_day,
            "training_end_day": mapped.training_end_day, "training_start_time": mapped.start_time,
            "training_end_time": mapped.end_time, "class_duration_minutes": mapped.class_duration_minutes,
            "training_method": mapped.method_name, "batch_fee": mapped.batch_fee, "schedule_timezone": mapped.schedule_timezone,
        }

    async def _upsert_batch(self, session: AsyncSession, mapped: ac.MappedBatch, course_id: int) -> tuple[int, str]:
        batch = (await session.execute(select(Batch).where(Batch.batch_code == mapped.batch_code))).scalar_one_or_none()
        if batch is None:
            batch = Batch(
                batch_code=mapped.batch_code, course_id=course_id, duration_hours=mapped.duration_hours,
                number_of_sessions=mapped.number_of_sessions, capacity=self._settings.lait.default_batch_capacity,
                notes=mapped.notes, start_date=mapped.start_date, end_date=mapped.end_date,
                is_active=mapped.is_active, total_enrollments=mapped.total_admission,
                **self._schedule_fields(mapped),
            )
            batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
            session.add(batch)
            await session.flush()
            return batch.id, "created"

        changed = False
        for name, value in (
            ("course_id", course_id), ("duration_hours", mapped.duration_hours),
            ("number_of_sessions", mapped.number_of_sessions), ("start_date", mapped.start_date),
            ("end_date", mapped.end_date), ("is_active", mapped.is_active),
            *self._schedule_fields(mapped).items(),
        ):
            if value is not None and getattr(batch, name) != value:
                setattr(batch, name, value)
                changed = True
        # Notes are regenerated only while they are still the generated text; an edited note is the administrator's.
        if (batch.notes is None or batch.notes.startswith(ac.AUTO_NOTE_PREFIX)) and batch.notes != mapped.notes:
            batch.notes = mapped.notes
            changed = True
        if changed:
            await session.flush()
        return batch.id, "updated" if changed else "unchanged"

    async def _sessions(
        self, session: AsyncSession, batch_pk: int, mapped: ac.MappedBatch, tutor_id: int | None,
        tutor_problem: str | None, report: "_Report", external: str,
    ) -> None:
        stats = report.sessions
        if tutor_problem:
            stats.skipped += len(mapped.sessions)
            report.report.error("batch", external, f"sessions not generated: {tutor_problem}")
            return
        if not mapped.sessions:
            if mapped.warnings:
                report.report.error("batch", external, "; ".join(mapped.warnings)[:200])
            return
        if tutor_id is None:
            stats.skipped += len(mapped.sessions)  # a dry run whose tutor would be created
            return

        existing = {
            s.session_start_time: s
            for s in (await session.execute(select(BatchSession).where(BatchSession.batch_id == batch_pk))).scalars().all()
        }
        platform = Platforms(mapped.platform) if mapped.platform else None
        wanted = {g.start_utc: g for g in mapped.sessions}

        for start, g in wanted.items():
            row = existing.get(start)
            if row is None:
                new = BatchSession(
                    batch_id=batch_pk, tutor_id=tutor_id, session_start_time=g.start_utc,
                    session_end_time=g.end_utc, duration_minutes=g.duration_minutes, origin="LAIT",
                    **({"platform": platform} if platform else {}),
                )
                new.attendances = []
                session.add(new)
                stats.created += 1
                continue
            changed = False
            for name, value in (("session_end_time", g.end_utc), ("duration_minutes", g.duration_minutes), ("tutor_id", tutor_id), ("platform", platform)):
                if value is not None and getattr(row, name) != value:
                    setattr(row, name, value)
                    changed = True
            if changed:
                stats.updated += 1
            else:
                stats.unchanged += 1

        for start, row in existing.items():
            if start in wanted:
                continue
            # A session someone created (in the LMS or in Google) or cancelled is a decision, not derived data.
            touched = row.origin not in (None, "LAIT") or row.cancelled_at is not None or any((row.meeting_link, row.recording_link, row.tutor_notes, row.student_notes))
            if not touched:
                touched = bool((await session.execute(select(func.count()).select_from(Attendance).where(Attendance.session_id == row.id))).scalar_one())
            if touched:
                stats.warnings += 1  # kept: it has history, so it is not ours to delete
            else:
                await session.delete(row)
        await session.flush()

    # ------------------------------------------------------------------ enrolments

    async def _enrollments(
        self, session: AsyncSession, client: LaitClient, geo: GeoResolver, f: Fetched, report: "_Report",
        cache: "_Cache", dry_run: bool, actor_id: int | None,
    ) -> None:
        for code, rows in f.students.items():
            batch = (await session.execute(select(Batch.id).where(Batch.batch_code == code))).first()
            if batch is None:
                report.enrollments.skipped += len(rows)  # the batch itself was skipped; its error is already recorded
                continue
            for row in rows:
                external = f"{code}/{row.get('admission_id')}"
                try:
                    async with session.begin_nested():
                        outcome = await self._enrol(session, client, geo, batch[0], row, cache, report, dry_run, actor_id)
                    setattr(report.enrollments, outcome, getattr(report.enrollments, outcome) + 1)
                except _Skip as exc:
                    report.enrollments.skipped += 1
                    report.report.error("enrollment", external, str(exc))
                except LaitApiError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Enrolment record failed")
                    report.enrollments.skipped += 1
                    report.report.error("enrollment", external, f"unexpected {type(exc).__name__}")

    async def _enrol(
        self, session: AsyncSession, client: LaitClient, geo: GeoResolver, batch_pk: int, row: dict[str, Any],
        cache: "_Cache", report: "_Report", dry_run: bool, actor_id: int | None,
    ) -> str:
        if not isinstance(row, dict):
            raise _Skip("record is not an object")
        try:
            guid = m.parse_guid(row.get("user_id"))
        except m.MappingError:
            raise _Skip("missing or invalid user_id") from None
        student_ext = m.parse_int(row.get("student_id"))
        admission = m.parse_int(row.get("admission_id"))

        user = await self._find_student(session, guid, student_ext)
        if user is None:
            payload = await client.student_by_guid(guid)
            if payload is None:
                raise _Skip("the student is not known to LAIT")
            try:
                mapped = m.map_student(payload, source_timezone=self._settings.lait.source_timezone)
            except m.MappingError as exc:
                raise _Skip(f"the student record is unusable ({exc})") from None
            _o, user_id = await self._users.upsert_record(mapped, None, geo, dry_run, actor_id, 0)
            if user_id is None:
                return "created"  # dry run: the account and the enrolment would both be created
            user = await self._find_student(session, guid, student_ext)
            if user is None:
                raise _Skip("the student account could not be created")

        org_id = await cache.organization(session, user.company, report)
        is_manager = any(r.name == "CORPORATE_MANAGER" for r in user.roles)

        existing = (
            await session.execute(select(Enrollments).where(Enrollments.batch_id == batch_pk, Enrollments.student_id == user.id))
        ).scalars().first()
        if existing is not None:
            changed = False
            if existing.admission_id is None and admission is not None:
                existing.admission_id, changed = admission, True
            if existing.organization_id is None and org_id is not None:
                existing.organization_id, changed = org_id, True
            if changed:
                await session.flush()
            return "updated" if changed else "unchanged"  # a status the administrator set is never touched

        previous = (
            await session.execute(
                select(Enrollments.enrollment_id).where(Enrollments.student_id == user.id, Enrollments.batch_id != batch_pk)
                .order_by(Enrollments.enrollment_id.desc()).limit(1)
            )
        ).scalar_one_or_none()
        session.add(Enrollments(
            admission_id=admission, batch_id=batch_pk, student_id=user.id, enrollment_date=datetime.now(timezone.utc),
            status=EnrollmentStatus.CONFIRMED, previous_enrollment_id=previous, is_transfer=False,
            is_manager=is_manager, enrolled_by=actor_id, organization_id=org_id,
        ))
        await session.flush()
        return "created"

    @staticmethod
    async def _find_student(session: AsyncSession, guid: Any, student_ext: int | None) -> User | None:
        conds = [User.public_id == guid]
        if student_ext is not None:
            conds.append(User.external_student_id == student_ext)
        rows = (await session.execute(select(User).where(or_(*conds)))).scalars().all()
        if len(rows) > 1:
            raise _Skip("the GUID and the LAIT student id point at different accounts")
        return rows[0] if rows else None

    async def _recount(self, session: AsyncSession, batch_ids: list[int]) -> None:
        """`total_enrollments` becomes the real count, not LAIT's `total_admission`."""
        for batch_pk in batch_ids:
            n = (
                await session.execute(
                    select(func.count()).select_from(Enrollments).where(
                        Enrollments.batch_id == batch_pk, Enrollments.status.in_(_ACTIVE_ENROLLMENT))
                )
            ).scalar_one()
            await session.execute(update(Batch).where(Batch.id == batch_pk).values(total_enrollments=n))


# =============================================================================
# COURSE STATUS (also callable on its own, on a timer)
# =============================================================================


async def refresh_course_statuses(source: async_sessionmaker[AsyncSession] | AsyncSession, *, commit: bool = True) -> dict[str, int]:
    """PUBLISHED <-> RUNNING from the calendar.

    A course is RUNNING while one of its *active* batches is in progress (start
    <= today <= end, UTC dates) and PUBLISHED otherwise. DRAFT, COMPLETED and
    ARCHIVED are administrator decisions and are never touched, and soft-deleted
    courses are ignored.
    """
    if isinstance(source, AsyncSession):
        return await _refresh(source)
    async with source.begin() as session:
        return await _refresh(session)


async def _refresh(session: AsyncSession) -> dict[str, int]:
    today = datetime.now(timezone.utc).date()
    running = select(Batch.course_id).where(Batch.is_active.is_(True), Batch.start_date <= today, Batch.end_date >= today)
    started = await session.execute(
        update(Course).where(Course.status == CourseStatus.PUBLISHED, Course.is_deleted.is_(False), Course.id.in_(running))
        .values(status=CourseStatus.RUNNING)
    )
    stopped = await session.execute(
        update(Course).where(Course.status == CourseStatus.RUNNING, Course.is_deleted.is_(False), Course.id.not_in(running))
        .values(status=CourseStatus.PUBLISHED)
    )
    return {"started": started.rowcount or 0, "stopped": stopped.rowcount or 0}


# =============================================================================
# per-run caches and reporting
# =============================================================================


def _is_uploaded(value: str | None) -> bool:
    """An uploaded image is stored as a storage key; an external one is an http(s) URL."""
    return bool(value) and not str(value).lower().startswith(("http://", "https://"))


class _Cache:
    def __init__(self) -> None:
        self.courses: dict[str, int] = {}
        self.users: dict[str, int] = {}
        self.categories: dict[str, int] = {}
        self.organizations: dict[str, int] = {}

    async def load(self, session: AsyncSession) -> None:
        for cid, name in (await session.execute(select(Category.id, Category.name))).all():
            self.categories[name.lower().strip()] = cid
        for oid, name in (await session.execute(select(Organization.id, Organization.name))).all():
            self.organizations[ac.company_key(name)] = oid

    async def category(self, session: AsyncSession, name: str, report: "_Report") -> int:
        key = name.lower().strip()
        if key not in self.categories:
            category = Category(name=name[:150])
            category.children = []
            session.add(category)
            await session.flush()
            self.categories[key] = category.id
            report.categories_created += 1

            # Seed default editors if category name matches standard curriculum keywords
            name_lower = name.lower()
            if "sql" in name_lower or "database" in name_lower:
                session.add(CategoryEditor(category_id=category.id, editor="sql"))
            if "python" in name_lower or "programming" in name_lower or "data & ai" in name_lower:
                session.add(CategoryEditor(category_id=category.id, editor="python"))
        return self.categories[key]

    async def organization(self, session: AsyncSession, company: str | None, report: "_Report") -> int | None:
        if ac.company_junk_reason(company) is not None:
            return None
        assert company is not None
        key = ac.company_key(company)
        if key not in self.organizations:
            now = datetime.now(timezone.utc)
            org = Organization(name=company.strip()[:255], is_active=True, created_at=now, updated_at=now)
            org.managers, org.memberships = [], []
            session.add(org)
            await session.flush()
            self.organizations[key] = org.id
            report.organizations_created += 1
        return self.organizations[key]


@dataclass
class _Report:
    courses: SourceStats = field(default_factory=SourceStats)
    batches: SourceStats = field(default_factory=SourceStats)
    sessions: SourceStats = field(default_factory=SourceStats)
    enrollments: SourceStats = field(default_factory=SourceStats)
    report: RunReport = field(default_factory=RunReport)
    categories_created: int = 0
    organizations_created: int = 0
    pages_fetched: int = 0
    pages_missing: int = 0
    statuses: dict[str, int] = field(default_factory=dict)

    def as_stats(self) -> dict[str, Any]:
        return {
            "courses": self.courses.as_dict(), "batches": self.batches.as_dict(),
            "sessions": self.sessions.as_dict(), "enrollments": self.enrollments.as_dict(),
            "categories_created": self.categories_created, "organizations_created": self.organizations_created,
            "course_pages": {"fetched": self.pages_fetched, "unavailable": self.pages_missing},
            "course_status": self.statuses, "errors_dropped": self.report.errors_dropped,
        }

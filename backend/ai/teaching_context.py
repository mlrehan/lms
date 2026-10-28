"""Everything the LMS knows about a class a tutor is about to teach.

Built for the question a tutor actually asks -- "what should I teach?" -- which
the assistant used to answer by chaining a curriculum lookup (which crashed on
every course) and a materials search (which found nothing), and then giving up.

**One pass over every source, each labelled with how it is known.** The
schema has no lesson or module tables, so the authoritative statement of what
a course covers is its published outline (`courses.outline`, from the
institution's course page). Around it: the class itself and its place in the
batch (session n of N), the course record, evidence of earlier teaching in the
batch, course files and assessments. Every source reports `verified_lms`,
`verified_course_page` or `missing`, so the model can say which parts of an
answer are the institution's and which are its own recommendation.

**Access is the services' own.** The class is found through
`SessionService.calendar` (the caller's visible sessions), a named batch
through `BatchService.get`, the course through `CourseService.get` (a tutor's
course scope), and each file through `ResourceService.get` (the per-file
ladder, staff-only material and shares). A batch or course the caller does not
teach is a NotFoundError -- the same answer as one that does not exist.

**"Taught" is never assumed.** An earlier session counts as evidence only if
it has attendance recorded, a started register, or tutor notes; a session that
merely sat in the timetable is reported as unrecorded, because a scheduled
class is not a delivered one.

**The course page is read live only as a fallback**, when the outline has not
been synced yet, through the same fetcher the sync uses (HTTPS, allowlisted
institution hosts only, no redirects, size-capped, short timeout) and cached
for a few hours. Its text is data from a web page, not instructions; the
registry hands it to the model inside `untrusted_data` like every tool result.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import get_settings
from backend.core.errors import NotFoundError
from backend.core.logging import get_logger
from backend.models.ai_index_state import ResourceIndexState
from backend.models.assignment import Assignment
from backend.models.attendance import Attendance
from backend.models.batch import Batch, BatchSession
from backend.models.enrollment import Enrollments
from backend.models.exam import Exam
from backend.models.identity.user import User
from backend.models.quiz import Quiz
from backend.models.resource import Resource
from backend.utils.enums import EnrollmentStatus

logger = get_logger(__name__)

_LOOKAHEAD = timedelta(days=120)
_LOOKBACK = timedelta(days=365)
_MAX_FILES = 30
_MAX_NOTES = 600
_PAGE_CACHE_SECONDS = 6 * 3600
_page_cache: dict[str, tuple[float, str | None, str | None]] = {}


def _local(dt: datetime | None, tz_name: str | None) -> str | None:
    if dt is None:
        return None
    try:
        zone = ZoneInfo(tz_name or "UTC")
    except Exception:  # noqa: BLE001 -- an unknown zone name falls back to UTC
        zone = ZoneInfo("UTC")
    return dt.astimezone(zone).strftime("%A %d %B %Y, %H:%M %Z")


async def _live_course_page(url: str | None) -> tuple[str | None, str | None]:
    """(outline, overview) read from the course page, or (None, None).

    Only an allowlisted institution host is ever contacted; anything else --
    and any failure -- is simply "not available", never an error to the tutor.
    """
    from backend.integrations.lait_academic import host_allowed, parse_course_page
    from backend.integrations.lait_pages import PageFetcher

    hosts = get_settings().lait.course_page_hosts
    if not url or not host_allowed(url, hosts):
        return None, None
    cached = _page_cache.get(url)
    if cached and time.monotonic() - cached[0] < _PAGE_CACHE_SECONDS:
        return cached[1], cached[2]
    try:
        async with PageFetcher(hosts, timeout=8.0) as fetcher:
            html = await fetcher.fetch(url)
    except Exception as exc:  # noqa: BLE001 -- a page that cannot be read is missing, not fatal
        logger.warning("Course page fetch failed: %s", exc)
        html = None
    page = parse_course_page(html) if html else None
    outline, overview = (page.outline, page.overview) if page else (None, None)
    _page_cache[url] = (time.monotonic(), outline, overview)
    return outline, overview


async def _target_session(
    db: AsyncSession, user: User, *, batch_code: str | None, session_id: str | None
) -> BatchSession | None:
    from backend.services.session_service import SessionService

    sessions = SessionService(db)
    if session_id:
        return await sessions.get(uuid.UUID(str(session_id).strip()), actor=user)

    batch_public_id = None
    if batch_code:
        batch_public_id = (
            await db.execute(select(Batch.public_id).where(Batch.batch_code == str(batch_code).strip()))
        ).scalar_one_or_none()
        # The same words BatchService uses: `calendar` below authorises the
        # batch and refuses one the caller cannot see with "Batch not found.",
        # so an unknown code must not be distinguishable from a hidden one.
        if batch_public_id is None:
            raise NotFoundError("Batch not found.")

    now = datetime.now(UTC)
    upcoming = [
        s for s in await sessions.calendar(
            actor=user, start=now, end=now + _LOOKAHEAD, batch_public_id=batch_public_id, limit=200
        )
        if s.cancelled_at is None and s.session_start_time and s.session_start_time >= now
    ]
    upcoming.sort(key=lambda s: s.session_start_time)
    # The caller's own classes first: a batch shared with a colleague has
    # sessions the caller is not the one teaching.
    mine = [s for s in upcoming if s.tutor_id == user.id]
    if mine or upcoming:
        return (mine or upcoming)[0]
    if batch_public_id is None:
        return None
    # A named batch with nothing ahead: the most recent class, so the tutor can
    # still prepare a follow-up for it.
    past = [
        s for s in await sessions.calendar(
            actor=user, start=now - _LOOKBACK, end=now, batch_public_id=batch_public_id, limit=200
        )
        if s.cancelled_at is None and s.session_start_time
    ]
    past.sort(key=lambda s: s.session_start_time)
    return past[-1] if past else None


async def build_teaching_context(
    db: AsyncSession, user: User, *, batch_code: str | None = None, session_id: str | None = None
) -> dict[str, Any]:
    from backend.services.course_service import CourseService
    from backend.services.editor_service import EditorService
    from backend.services.resource_service import ResourceService

    target = await _target_session(db, user, batch_code=batch_code, session_id=session_id)
    if target is None:
        return {
            "found": False,
            "message": "No upcoming class was found in the batches you teach.",
        }

    batch = target.batch
    course = await CourseService(db).get(batch.course.public_id, actor=user)
    tz = user.timezone

    # -- the class and its place in the batch ------------------------------
    batch_sessions = (
        await db.execute(
            select(BatchSession)
            .where(BatchSession.batch_id == batch.id, BatchSession.cancelled_at.is_(None))
            .order_by(BatchSession.session_start_time)
        )
    ).scalars().all()
    ordered = [s.id for s in batch_sessions]
    position = ordered.index(target.id) + 1 if target.id in ordered else None
    end = target.session_end_time
    duration = (
        int((end - target.session_start_time).total_seconds() // 60)
        if end and target.session_start_time
        else (target.duration_minutes or batch.class_duration_minutes)
    )

    # -- evidence of earlier teaching ------------------------------------------
    earlier = [s for s in batch_sessions if s.session_start_time and target.session_start_time
               and s.session_start_time < target.session_start_time]
    attendance_counts: dict[int, int] = {}
    if earlier:
        rows = await db.execute(
            select(Attendance.session_id, func.count())
            .where(Attendance.session_id.in_([s.id for s in earlier]))
            .group_by(Attendance.session_id)
        )
        attendance_counts = {sid: n for sid, n in rows.all()}
    previous = []
    for index, s in enumerate(earlier, start=1):
        recorded = attendance_counts.get(s.id, 0)
        notes = (s.tutor_notes or "").strip()
        previous.append({
            "session_number": index,
            "date": _local(s.session_start_time, tz),
            "taught_by_you": s.tutor_id == user.id,
            "attendance_records": recorded,
            "tutor_notes": notes[:_MAX_NOTES] or None,
            "evidence": "verified_lms" if (recorded or notes) else "unrecorded",
        })

    # -- the course's published content ------------------------------------------
    outline, overview = getattr(course, "outline", None), getattr(course, "overview", None)
    outline_source = "verified_lms" if outline else "missing"
    if not outline:
        live_outline, live_overview = await _live_course_page(course.course_link)
        if live_outline:
            outline, outline_source = live_outline, "verified_course_page"
        overview = overview or live_overview

    # -- files and assessments -------------------------------------------------------
    resources = ResourceService(db)
    candidates = (
        await db.execute(
            select(Resource)
            .where(
                Resource.is_deleted.is_(False),
                (Resource.course_id == course.id) | (Resource.batch_id == batch.id),
            )
            .order_by(Resource.created_at.desc())
            .limit(_MAX_FILES)
        )
    ).scalars().all()
    states = {}
    if candidates:
        states = {
            s.resource_id: s.status
            for s in (
                await db.execute(
                    select(ResourceIndexState).where(ResourceIndexState.resource_id.in_([r.id for r in candidates]))
                )
            ).scalars()
        }
    files = []
    for row in candidates:
        try:
            await resources.get(row.public_id, actor=user)
        except NotFoundError:
            continue
        files.append({
            "name": row.name,
            "type": row.mime_type,
            "searchable": states.get(row.id) == "INDEXED",
        })

    assessments = []
    for model, kind in ((Assignment, "assignment"), (Quiz, "quiz"), (Exam, "exam")):
        for title in (await db.execute(select(model.title).where(model.course_id == course.id).limit(20))).scalars():
            assessments.append({"type": kind, "title": title})

    enrolled = (
        await db.execute(
            select(func.count()).select_from(Enrollments).where(
                Enrollments.batch_id == batch.id, Enrollments.status == EnrollmentStatus.CONFIRMED
            )
        )
    ).scalar_one()
    editors = [{"name": e.label, "url": e.url} for e in await EditorService(db).for_user(actor=user)]

    if outline:
        basis = "official_outline"
    elif course.description:
        basis = "course_description"
    else:
        basis = "none"
    total = len(ordered)
    if total <= 1:
        scope_note = "This batch has a single class: the whole published outline is this class's content."
    else:
        scope_note = (
            f"This is class {position} of {total}. The outline covers the whole course, so allocate it "
            "across the classes; an earlier class counts as covered only where its evidence is verified_lms."
        )

    return {
        "found": True,
        "class": {
            "session_id": str(target.public_id),
            "course": course.title,
            "batch_code": batch.batch_code,
            "when": _local(target.session_start_time, tz),
            "starts_at_utc": target.session_start_time.isoformat() if target.session_start_time else None,
            "duration_minutes": duration,
            "session_number": position,
            "sessions_in_batch": total,
            "students_enrolled": enrolled,
            "you_teach_it": target.tutor_id == user.id,
        },
        "course": {
            "title": course.title,
            "code": course.code,
            "level": course.level.value if course.level else None,
            "duration_hours": course.duration_hours,
            "description": course.description,
            "prerequisites": course.prerequisites,
            "overview": overview,
            "course_page": course.course_link,
        },
        "official_outline": outline,
        "previous_classes_in_batch": previous,
        "course_files": files,
        "assessments": assessments,
        "practice_editors": editors,
        "sources": {
            "official_outline": outline_source,
            "course_description": "verified_lms" if course.description else "missing",
            "previous_teaching": "verified_lms" if any(p["evidence"] == "verified_lms" for p in previous) else (
                "none_recorded" if previous else "first_class"
            ),
            "course_files": "verified_lms" if files else "none",
            "assessments": "verified_lms" if assessments else "none",
        },
        "lesson_basis": basis,
        "scope_note": scope_note,
    }

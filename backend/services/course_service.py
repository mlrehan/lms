"""Course management (spec §5)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Sequence

import asyncio
import re

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import get_settings
from backend.core.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from backend.models.administration import Category, CourseTag, Department, Tag
from backend.models.course import Course, TutorCourse
from backend.models.identity.user import User
from backend.repositories.course import CourseRepository
from backend.repositories.user import UserRepository
from backend.schemas.base import PageParams
from backend.schemas.course import CourseCreateRequest, CourseUpdateRequest
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.integrations import lait_academic as academic
from backend.integrations.lait_pages import PageFetcher
from backend.services.images import CONTENT_TYPE as IMAGE_CONTENT_TYPE, process_course_image
from backend.services.scope import ScopeResolver
from backend.storage import get_storage
from backend.storage.base import build_key
from backend.utils.enums import CourseStatus, Roles

# Spec §5: Draft -> Published -> Running -> Completed -> Archived.
#
# Written as an explicit map rather than checked ad hoc, because the
# interesting property is what is *absent*: a course cannot jump from DRAFT
# straight to COMPLETED, and nothing leaves ARCHIVED. Un-publishing back to
# DRAFT is allowed (a course published by mistake must be retractable);
# un-completing is not, because grades and certificates hang off a completed
# course and reopening it would leave them describing a state that no longer
# exists.
_ALLOWED_TRANSITIONS: dict[CourseStatus, frozenset[CourseStatus]] = {
    CourseStatus.DRAFT: frozenset({CourseStatus.PUBLISHED, CourseStatus.ARCHIVED}),
    CourseStatus.PUBLISHED: frozenset(
        {CourseStatus.RUNNING, CourseStatus.DRAFT, CourseStatus.ARCHIVED}
    ),
    CourseStatus.RUNNING: frozenset({CourseStatus.COMPLETED, CourseStatus.ARCHIVED}),
    CourseStatus.COMPLETED: frozenset({CourseStatus.ARCHIVED}),
    CourseStatus.ARCHIVED: frozenset(),
}


class CourseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.courses = CourseRepository(session)
        self.users = UserRepository(session)
        self.scopes = ScopeResolver(session)

    # -- reads ---------------------------------------------------------------

    async def list_courses(
        self,
        params: PageParams,
        *,
        actor: User,
        query: str | None = None,
        status: CourseStatus | None = None,
        level: str | None = None,
        category_id: uuid.UUID | None = None,
        department_id: uuid.UUID | None = None,
        tag_id: uuid.UUID | None = None,
        tutor_id: uuid.UUID | None = None,
        student_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[Course], int]:
        tutor_user_id = student_user_id = None
        if tutor_id is not None or student_id is not None:
            # Filtering the catalogue by a *person* reveals who teaches and who studies what, so
            # it is limited to callers who may already see the whole institution.
            if not ScopeResolver.is_unrestricted(actor):
                raise AuthorizationError("Filtering courses by tutor or student needs institution-wide access.")
            tutor_user_id = await self._user_id(tutor_id, "Tutor") if tutor_id else None
            student_user_id = await self._user_id(student_id, "Student") if student_id else None
        return await self.courses.search(
            params,
            unrestricted=ScopeResolver.is_unrestricted(actor),
            tutor_course_ids=await self.scopes.tutor_course_ids(actor),
            query=query,
            status=status,
            level=level,
            category_id=await self._resolve(Category, category_id, "Category"),
            department_id=await self._resolve(Department, department_id, "Department"),
            tag_id=await self._resolve(Tag, tag_id, "Tag"),
            tutor_user_id=tutor_user_id,
            student_user_id=student_user_id,
        )

    async def _user_id(self, public_id: uuid.UUID, label: str) -> int:
        row = (await self.session.execute(select(User.id).where(User.public_id == public_id))).first()
        if row is None:
            raise NotFoundError(f"{label} not found.")
        return int(row[0])

    async def get(self, public_id: uuid.UUID, *, actor: User) -> Course:
        course = await self.courses.get_by_public_id_full(public_id)
        if course is None:
            raise NotFoundError("Course not found.")

        if not ScopeResolver.is_unrestricted(actor):
            from backend.repositories.course import PUBLIC_STATUSES

            taught = await self.scopes.tutor_course_ids(actor)
            if course.status not in PUBLIC_STATUSES and course.id not in taught:
                # A draft course is not merely unreadable, it is not yet
                # something the institution admits to having -- 404, not 403.
                raise NotFoundError("Course not found.")
        return course

    # -- writes --------------------------------------------------------------

    async def create(self, payload: CourseCreateRequest, *, actor: User) -> Course:
        await self._assert_title_free(payload.title)
        code = payload.code or await self.suggest_code(payload.title)
        await self._assert_code_free(code)

        course = Course(
            title=payload.title,
            code=code,
            description=payload.description,
            level=payload.level,
            duration_hours=payload.duration_hours,
            prerequisites=payload.prerequisites,
            price=payload.price,
            course_link=payload.course_link,
            course_image=payload.course_image,
            small_course_image=payload.small_course_image,
            category_id=await self._resolve(Category, payload.category_id, "Category"),
            department_id=await self._resolve(Department, payload.department_id, "Department"),
            # Always DRAFT. A course that could be created already PUBLISHED
            # would let its content go live before anyone had reviewed it.
            status=CourseStatus.DRAFT,
        )
        # Initialise the collection in memory before the object becomes
        # persistent. A new course has no tutors, but reading `.tutors` on a
        # flushed-but-never-queried instance triggers a lazy SELECT, which
        # under asyncio raises MissingGreenlet instead of quietly querying.
        # (Same trap as the role seeder; see bootstrap/seeders/identity.py.)
        course.tutors = []
        # `tags` is `lazy="raise"` on the Tag side and an ordinary collection
        # here; a new instance leaves it unloaded, and the flush cascade
        # touching it raises `MissingGreenlet` under asyncio.
        course.tags = []
        await self.courses.add_and_flush(course)

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="course",
            entity_id=course.id,
            details={"title": course.title},
        )
        # Re-read: `category`/`department` were set by foreign key and are
        # unloaded on a newly-constructed instance, so the response mapper's
        # first `course.category` would be a lazy load inside the event loop
        # -- `MissingGreenlet`, not a helpful error.
        return await self.courses.get_by_public_id_full(course.public_id)  # type: ignore[return-value]

    async def update(
        self, public_id: uuid.UUID, payload: CourseUpdateRequest, *, actor: User
    ) -> Course:
        course = await self.get(public_id, actor=actor)
        changes = payload.model_dump(exclude_unset=True)

        # Reference-data links are resolved out of `changes` before the blind
        # `setattr` loop below: those fields carry a public UUID and the
        # column holds an integer primary key, so assigning them straight
        # through would write a UUID into an integer FK.
        clear_category = changes.pop("clear_category", False)
        clear_department = changes.pop("clear_department", False)
        category_public = changes.pop("category_id", None)
        department_public = changes.pop("department_id", None)

        if clear_category:
            course.category_id = None
        elif category_public is not None:
            course.category_id = await self._resolve(Category, category_public, "Category")

        if clear_department:
            course.department_id = None
        elif department_public is not None:
            course.department_id = await self._resolve(Department, department_public, "Department")

        if changes.get("title") and changes["title"].lower() != (course.title or "").lower():
            await self._assert_title_free(changes["title"])
        if changes.get("code") and (changes["code"] or "").lower() != (course.code or "").lower():
            await self._assert_code_free(changes["code"])

        for field, value in changes.items():
            setattr(course, field, value)

        # Setting the foreign key does not invalidate the already-loaded
        # `category`/`department` objects, so the response would echo the
        # previous ones. Same stale-relationship trap as `set_tutors` below.
        self.session.expire(course, ["category", "department"])
        refreshed = await self.courses.get_by_public_id_full(course.public_id)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="course",
            entity_id=course.id,
            details={"fields": sorted(changes)},
        )
        return refreshed  # type: ignore[return-value]

    async def set_status(
        self, public_id: uuid.UUID, new_status: CourseStatus, *, actor: User
    ) -> Course:
        course = await self.get(public_id, actor=actor)
        current = course.status

        if new_status == current:
            return course

        allowed = _ALLOWED_TRANSITIONS.get(current, frozenset())
        if new_status not in allowed:
            raise ConflictError(
                f"A {current.value} course cannot become {new_status.value}.",
                details={
                    "current_status": current.value,
                    "allowed_transitions": sorted(s.value for s in allowed),
                },
            )

        course.status = new_status
        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="course",
            entity_id=course.id,
            details={"status": f"{current.value} -> {new_status.value}"},
        )
        return course

    async def set_tags(
        self, public_id: uuid.UUID, tag_public_ids: Sequence[uuid.UUID], *, actor: User
    ) -> Course:
        """Replace the course's tags with exactly this set.

        Unlike `set_tutors`, this is pure metadata -- `course_tags` grants
        nobody anything, it only makes the course findable. The two are
        written the same way regardless, because the difference that matters
        is the stale-collection trap below, not the stakes.
        """
        course = await self.get(public_id, actor=actor)

        tags = await self._resolve_tags(tag_public_ids)
        existing = {
            row.tag_id
            for row in (
                await self.session.execute(
                    select(CourseTag).where(CourseTag.course_id == course.id)
                )
            )
            .scalars()
            .all()
        }
        desired = {t.id for t in tags}

        for tag_id in existing - desired:
            row = await self.session.get(CourseTag, (course.id, tag_id))
            if row is not None:
                await self.session.delete(row)

        for tag_id in desired - existing:
            self.session.add(CourseTag(course_id=course.id, tag_id=tag_id))

        await self.session.flush()

        # The association rows changed underneath `course.tags`, which was
        # loaded before this call and now describes the previous state. The
        # identity map hands back the same instance on a re-query, so the
        # response would report the old tags while the write had succeeded --
        # exactly the bug `set_tutors` was fixed for.
        self.session.expire(course, ["tags"])
        refreshed = await self.courses.get_by_public_id_full(course.public_id)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="course",
            entity_id=course.id,
            details={"tags": sorted(t.name for t in tags)},
        )
        return refreshed  # type: ignore[return-value]

    # -- code suggestion ---------------------------------------------------------

    _STOPWORDS = frozenset({"a", "an", "the", "for", "and", "of", "to", "in", "with", "on", "at", "by", "or"})

    @classmethod
    def _abbreviation(cls, title: str) -> str:
        words = [w for w in re.findall(r"[A-Za-z0-9]+", title) if w.lower() not in cls._STOPWORDS]
        if not words:
            return "CRS"
        initials = "".join(w[0] for w in words[:4]).upper()
        if len(initials) < 3:
            # "SQL for Beginners" -> "SB" is meaningless; keep the first word's own letters.
            initials = (words[0][:3] + "".join(w[0] for w in words[1:3])).upper()
        return initials[:6]

    async def suggest_code(self, title: str) -> str:
        """`Python Programming for Beginners` -> `PPB-001`: initials, then the next free number.

        A suggestion, not a reservation: the caller may change it, and the unique
        constraint remains the arbiter if two people are handed the same one.
        """
        prefix = self._abbreviation(title)
        rows = (
            await self.session.execute(select(Course.code).where(Course.code.like(f"{prefix}-%")))
        ).scalars().all()
        highest = 0
        for code in rows:
            m = re.fullmatch(rf"{re.escape(prefix)}-(\d+)", code or "")
            if m:
                highest = max(highest, int(m.group(1)))
        return f"{prefix}-{highest + 1:03d}"

    # -- images ------------------------------------------------------------------

    async def set_image(self, public_id: uuid.UUID, kind: str, upload: UploadFile, *, actor: User) -> Course:
        course = await self.get(public_id, actor=actor)
        raw = await upload.read(5 * 1024 * 1024 + 1)  # bounded: never buffer an unbounded body
        data = await asyncio.to_thread(process_course_image, raw, kind)

        key = build_key(prefix=f"courses/{course.public_id}/{kind}", filename="image.webp")
        await get_storage().save(key, data, content_type=IMAGE_CONTENT_TYPE)

        column = "small_course_image" if kind == "small" else "course_image"
        previous = getattr(course, column)
        setattr(course, column, key)
        await self._after_image_change(course, actor, kind)
        await self._discard(previous)
        return await self.courses.get_by_public_id_full(course.public_id)  # type: ignore[return-value]

    async def remove_image(self, public_id: uuid.UUID, kind: str, *, actor: User) -> Course:
        if kind not in ("small", "full"):
            raise ValidationError("Unknown image kind.")
        course = await self.get(public_id, actor=actor)
        column = "small_course_image" if kind == "small" else "course_image"
        previous = getattr(course, column)
        setattr(course, column, None)
        await self._after_image_change(course, actor, kind)
        await self._discard(previous)
        return await self.courses.get_by_public_id_full(course.public_id)  # type: ignore[return-value]

    async def _after_image_change(self, course: Course, actor: User, kind: str) -> None:
        course.updated_at = datetime.now(UTC)
        audit_service.record(
            self.session, action=AuditAction.UPDATE, actor_user_id=actor.id, actor_email=actor.email,
            entity_type="course", entity_id=course.id, details={"fields": [f"{kind}_image"]},
        )
        await self.session.flush()

    @staticmethod
    async def _discard(key: str | None) -> None:
        """Only an *uploaded* object (a storage key) is deleted; an external URL was never ours."""
        if not key or key.lower().startswith(("http://", "https://")):
            return
        try:
            await get_storage().delete(key)
        except Exception:  # noqa: BLE001 - an orphaned file is dead weight; failing the request is worse
            pass

    async def image_key(self, public_id: uuid.UUID, kind: str, *, actor: User) -> str:
        if kind not in ("small", "full"):
            raise NotFoundError("No such image.")
        course = await self.get(public_id, actor=actor)
        value = course.small_course_image if kind == "small" else course.course_image
        if not value or value.lower().startswith(("http://", "https://")):
            raise NotFoundError("No uploaded image.")  # an external URL is served by its own host
        return value

    # -- link preview ---------------------------------------------------------------

    async def link_preview(self, url: str) -> academic.CoursePage:
        """Read a course page and report what it says. Nothing is saved.

        Restricted to the LAIT site (https, allowed hosts): the URL comes from a
        request body, so anything else would make the server fetch an address of the
        caller's choosing.
        """
        settings = get_settings().lait
        if not academic.host_allowed(url, settings.course_page_hosts):
            raise ValidationError("Only course pages on the London Academy of IT website can be read.")
        async with PageFetcher(settings.course_page_hosts, timeout=settings.course_page_timeout_seconds) as fetcher:
            html = await fetcher.fetch(url)
        if html is None:
            raise ValidationError("That page could not be read. Check the link and try again.")
        return academic.parse_course_page(html)

    async def _resolve_tags(self, public_ids: Sequence[uuid.UUID]) -> list[Tag]:
        wanted = list(dict.fromkeys(public_ids))
        if not wanted:
            return []
        rows = list(
            (await self.session.execute(select(Tag).where(Tag.public_id.in_(wanted))))
            .scalars()
            .unique()
            .all()
        )
        if len(rows) != len(wanted):
            found = {t.public_id for t in rows}
            missing = [str(p) for p in wanted if p not in found]
            raise NotFoundError("One or more tags do not exist.", details={"missing": missing})
        return rows

    async def _resolve(self, model, public_id, label: str):  # type: ignore[no-untyped-def]
        """Public UUID -> internal integer primary key, or 404.

        Returning `None` for an unknown id would silently drop the caller's
        filter and answer with the unfiltered catalogue, which reads as
        "there is nothing in that category" only by coincidence.
        """
        if public_id is None:
            return None
        row_id = (
            await self.session.execute(
                select(model.id).where(model.public_id == public_id)
            )
        ).scalar_one_or_none()
        if row_id is None:
            raise NotFoundError(f"{label} not found.")
        return int(row_id)

    async def set_tutors(
        self, public_id: uuid.UUID, tutor_public_ids: Sequence[uuid.UUID], *, actor: User
    ) -> Course:
        """Replace the course's tutor assignments.

        This is an authorization-relevant write, not just a bit of metadata:
        `tutor_courses` is what grants a tutor visibility of the course's
        batches and the students enrolled in them (see `services/scope.py`).
        Assigning someone here hands them access to student records.
        """
        course = await self.get(public_id, actor=actor)
        tutors = await self._resolve_tutors(tutor_public_ids)

        existing = {
            row.tutor_id
            for row in (
                await self.session.execute(
                    select(TutorCourse).where(TutorCourse.course_id == course.id)
                )
            )
            .scalars()
            .all()
        }
        desired = {t.id for t in tutors}

        for tutor_id in existing - desired:
            row = await self.session.get(TutorCourse, (tutor_id, course.id))
            if row is not None:
                await self.session.delete(row)

        for tutor_id in desired - existing:
            self.session.add(TutorCourse(tutor_id=tutor_id, course_id=course.id))

        await self.session.flush()

        # The association rows changed underneath `course.tutors`, but that
        # collection was already loaded and now describes the state *before*
        # this call. Re-querying alone does not help: the identity map hands
        # back the same instance with the same stale collection, so the
        # response reported no tutors while the assignment had in fact
        # succeeded. Expiring it forces the re-read below to repopulate.
        self.session.expire(course, ["tutors"])

        audit_service.record(
            self.session,
            action=AuditAction.PERMISSION_CHANGE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="course",
            entity_id=course.id,
            details={"tutors": sorted(t.username for t in tutors)},
        )
        return await self.courses.get_by_public_id_full(public_id)  # type: ignore[return-value]

    async def soft_delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        course = await self.get(public_id, actor=actor)

        batches = await self.courses.count_batches(course.id)
        if batches:
            # Deleting a course out from under its batches would orphan every
            # enrollment, attendance record and grade hanging off them.
            # Archiving is the way to retire a course that has run.
            raise ConflictError(
                "This course still has batches. Archive it instead.",
                details={"batch_count": batches},
            )

        course.is_deleted = True
        course.deleted_at = datetime.now(UTC)
        course.deleted_by = actor.id

        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="course",
            entity_id=course.id,
        )

    # -- guards --------------------------------------------------------------

    async def _assert_title_free(self, title: str) -> None:
        if await self.courses.get_by_title(title):
            raise ConflictError("A course with that title already exists.")

    async def _assert_code_free(self, code: str) -> None:
        if await self.courses.get_by_code(code):
            raise ConflictError("A course with that code already exists.")

    async def _resolve_tutors(self, public_ids: Sequence[uuid.UUID]) -> list[User]:
        if not public_ids:
            return []

        stmt = select(User).where(User.public_id.in_(list(public_ids)))
        found = list((await self.session.execute(stmt)).scalars().unique().all())

        missing = set(public_ids) - {u.public_id for u in found}
        if missing:
            raise ValidationError(
                "Unknown user(s).", details={"unknown_users": sorted(str(m) for m in missing)}
            )

        # Assigning a non-tutor would grant course access to someone whose
        # role says they should not be teaching -- refused rather than
        # silently creating an inconsistent assignment.
        not_tutors = [
            u.username
            for u in found
            if not any((r.name or "").upper() == Roles.TUTOR.value for r in (u.roles or []))
        ]
        if not_tutors:
            raise ValidationError(
                "These users do not hold the TUTOR role.",
                details={"not_tutors": sorted(not_tutors)},
            )
        return found

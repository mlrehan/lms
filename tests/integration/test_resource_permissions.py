"""A file's access level decides what you may do with it.

`ResourcePermissionLevel` shipped with the resource module and was read by
nothing: access was a single "can you reach it" boolean, so a student granted
VIEW could call `/download` and receive the bytes, and a tutor holding
`resource.delete` globally could delete a file that had been shared with them
read-only.

Driven against real Postgres with real roles, because the defect lived in the
interaction between a *global* permission and a *per-file* grant -- a fake actor
with a hand-set permission set would assert nothing about that.
"""

from __future__ import annotations

import asyncio
import selectors
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.core.errors import AuthorizationError
from backend.db.manager import DatabaseManager
from backend.models.course import Course, TutorCourse
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.resource import Resource, SharedResource
from backend.services.resource_service import ResourceService
from backend.utils.enums import CourseStatus, ResourcePermissionLevel as L, ResourceType, UserStatus


@pytest.fixture()
def env():
    tag = "rp" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="resource-permission-tests")

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s, *, share_level: L | None = L.VIEW):  # noqa: ANN001, ANN202
        roles = {
            n: (await s.execute(select(Role).where(Role.name == n))).scalar_one()
            for n in ("TUTOR", "STUDENT")
        }

        def user(kind: str, role: str) -> User:
            return User(
                username=f"{tag}.{kind}", slug=f"{tag}-{kind}", email=f"{tag}.{kind}@t.test",
                first_name=kind.title(), last_name="Person", hashed_password="x",
                status=UserStatus.ACTIVE, roles=[roles[role]],
            )

        tutor, student = user("tutor", "TUTOR"), user("student", "STUDENT")
        course = Course(title=f"{tag} course", code=f"{tag}-C", status=CourseStatus.PUBLISHED)
        s.add_all([tutor, student, course])
        await s.flush()
        s.add(TutorCourse(tutor_id=tutor.id, course_id=course.id))

        # A real row rather than an upload: the storage round trip is not what is
        # under test, and the permission check happens long before the bytes.
        resource = Resource(
            name=f"{tag} handout.pdf", resource_type=ResourceType.lecture_sheet,
            course_id=course.id, path=f"{tag}/handout.pdf", mime_type="application/pdf",
            size=1024, uploaded_by=tutor.id, modified_by=tutor.id,
            is_deleted=False, created_at=datetime.now(UTC),
        )
        s.add(resource)
        await s.flush()

        if share_level is not None:
            s.add(SharedResource(
                resource_id=resource.id, shared_with_user_id=student.id,
                shared_by_user_id=tutor.id, level=share_level, created_at=datetime.now(UTC),
            ))
        await s.flush()
        return dict(tutor=tutor, student=student, course=course, resource=resource)

    ns = type("Env", (), dict(tag=tag, run=staticmethod(run), build=staticmethod(build)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"u": f"{tag}.%", "c": f"{tag}-%", "n": f"{tag}%"}
                users = "(SELECT id FROM users WHERE username LIKE :u)"
                await s.execute(text(f"DELETE FROM shared_resources WHERE shared_with_user_id IN {users} OR shared_by_user_id IN {users}"), p)
                await s.execute(text("DELETE FROM resource_permissions WHERE resource_id IN (SELECT id FROM resources WHERE name LIKE :n)"), p)
                await s.execute(text("DELETE FROM resource_versions WHERE resource_id IN (SELECT id FROM resources WHERE name LIKE :n)"), p)
                await s.execute(text("DELETE FROM resources WHERE name LIKE :n"), p)
                await s.execute(text("DELETE FROM tutor_courses WHERE course_id IN (SELECT id FROM courses WHERE code LIKE :c)"), p)
                await s.execute(text("DELETE FROM courses WHERE code LIKE :c"), p)
                await s.execute(text("DELETE FROM users WHERE username LIKE :u"), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _levels(env, share_level):  # noqa: ANN001, ANN202
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s, share_level=share_level)
            svc = ResourceService(s)
            return made, {
                "student": await svc.effective_level(made["resource"], made["student"]),
                "tutor": await svc.effective_level(made["resource"], made["tutor"]),
            }
        return go()
    return env.run(f)


# ------------------------------------------------------------- the ladder ---


def test_a_view_only_share_resolves_to_view(env) -> None:
    _, levels = _levels(env, L.VIEW)
    assert levels["student"] is L.VIEW


def test_the_owning_tutor_gets_manage_without_a_grant(env) -> None:
    """A tutor administers their own course's files; writing a grant per file
    would be busywork, and the absence of one is not the absence of authority."""
    _, levels = _levels(env, L.VIEW)
    assert levels["tutor"] is L.MANAGE


def test_someone_with_no_route_to_the_file_has_no_level(env) -> None:
    _, levels = _levels(env, None)
    assert levels["student"] is None


# --------------------------------------------------------- what it refuses ---


def test_a_viewer_may_preview_but_not_download(env) -> None:
    """The exact hole: VIEW used to be enough to receive the bytes."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s, share_level=L.VIEW)
            svc = ResourceService(s)
            pid, student = made["resource"].public_id, made["student"]

            resource, key = await svc.resolve_preview(pid, actor=student)
            assert key  # preview is allowed at VIEW

            with pytest.raises(AuthorizationError):
                await svc.resolve_download(pid, actor=student)
            return True
        return go()

    assert env.run(f)


def test_raising_the_share_to_download_lets_the_bytes_through(env) -> None:
    """The positive half, so the refusal above cannot be passing vacuously."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s, share_level=L.DOWNLOAD)
            svc = ResourceService(s)
            _, key, _ = await svc.resolve_download(made["resource"].public_id, actor=made["student"])
            return key
        return go()

    assert env.run(f)


def test_a_viewer_cannot_rename_move_or_delete(env) -> None:
    """The read-only default for Students, Guardians and Corporate Managers."""
    from backend.schemas.resource import ResourceUpdateRequest

    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s, share_level=L.VIEW)
            svc = ResourceService(s)
            pid, student = made["resource"].public_id, made["student"]

            with pytest.raises(AuthorizationError):
                await svc.update(pid, ResourceUpdateRequest(name="renamed"), actor=student)
            with pytest.raises(AuthorizationError):
                await svc.soft_delete(pid, actor=student)
            with pytest.raises(AuthorizationError):
                await svc.set_share_link(pid, enabled=True, actor=student)
            return True
        return go()

    assert env.run(f)


def test_a_non_previewable_type_is_refused_rather_than_rendered(env) -> None:
    """An uploaded SVG or HTML page rendered inline at this origin is stored XSS,
    so the type allowlist refuses it here rather than relying on headers alone."""
    from backend.core.errors import ValidationError

    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s, share_level=L.VIEW)
            made["resource"].mime_type = "image/svg+xml"
            await s.flush()
            with pytest.raises(ValidationError):
                await ResourceService(s).resolve_preview(
                    made["resource"].public_id, actor=made["student"]
                )
            return True
        return go()

    assert env.run(f)

"""Browsing the library root lists the files that are *in* the root.

`folder_id=None` has always meant "don't filter by folder", which is right for a
search and wrong for browsing -- and browsing was the only caller. So the root of
the library listed every file in every folder: filing a document away left a copy
of it sitting at the top level, and a library with folders looked exactly like one
without.

`ResourceFolderRepository` has always drawn this distinction for folders
(`parent_folder_id.is_(None)`). The resource side simply never did, which is why
the two halves of the same screen disagreed about what "here" meant.

The pair of tests below is the point: `root_only` must *exclude* a filed file and
must still *include* an unfiled one. Either alone passes for an empty library.
"""

from __future__ import annotations

import asyncio
import selectors
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.db.manager import DatabaseManager
from backend.models.course import Course, TutorCourse
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.resource import Resource, ResourceFolder
from backend.schemas.base import PageParams
from backend.services.resource_service import ResourceService
from backend.utils.enums import CourseStatus, ResourceType, UserStatus


@pytest.fixture()
def env():
    tag = "rr" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="resource-root-tests")

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        tutor_role = (
            await s.execute(select(Role).where(Role.name == "TUTOR"))
        ).scalar_one()
        def tutor_user(kind: str) -> User:
            return User(
                username=f"{tag}.{kind}", slug=f"{tag}-{kind}", email=f"{tag}.{kind}@t.test",
                first_name=kind.title(), last_name="Person", hashed_password="x",
                status=UserStatus.ACTIVE, roles=[tutor_role],
            )

        tutor = tutor_user("tutor")
        # Teaches a different course entirely, so this folder is none of their
        # business -- the case the listing used to disclose anyway.
        outsider = tutor_user("outsider")
        course = Course(title=f"{tag} course", code=f"{tag}-C", status=CourseStatus.PUBLISHED)
        other = Course(title=f"{tag} other", code=f"{tag}-O", status=CourseStatus.PUBLISHED)
        s.add_all([tutor, outsider, course, other])
        await s.flush()
        s.add(TutorCourse(tutor_id=tutor.id, course_id=course.id))
        s.add(TutorCourse(tutor_id=outsider.id, course_id=other.id))

        folder = ResourceFolder(
            name=f"{tag} folder", course_id=course.id, created_by=tutor.id,
            created_at=datetime.now(UTC),
        )
        s.add(folder)
        await s.flush()

        def file(name: str, folder_id: int | None) -> Resource:
            return Resource(
                name=f"{tag} {name}", resource_type=ResourceType.lecture_sheet,
                course_id=course.id, folder_id=folder_id, path=f"{tag}/{name}",
                mime_type="application/pdf", size=10, uploaded_by=tutor.id,
                modified_by=tutor.id, is_deleted=False, created_at=datetime.now(UTC),
            )

        s.add_all([file("loose.pdf", None), file("filed.pdf", folder.id)])
        await s.flush()
        return dict(tutor=tutor, outsider=outsider, course=course, folder=folder)

    ns = type("Env", (), dict(tag=tag, run=staticmethod(run), build=staticmethod(build)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"u": f"{tag}.%", "c": f"{tag}-%", "n": f"{tag}%", "o": f"{tag}-O"}
                await s.execute(text("DELETE FROM resources WHERE name LIKE :n"), p)
                await s.execute(text("DELETE FROM resource_folders WHERE name LIKE :n"), p)
                await s.execute(text("DELETE FROM tutor_courses WHERE course_id IN (SELECT id FROM courses WHERE code LIKE :c)"), p)
                await s.execute(text("DELETE FROM courses WHERE code LIKE :c OR code LIKE :o"), p)
                await s.execute(text("DELETE FROM users WHERE username LIKE :u"), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _names(env, **kwargs):  # noqa: ANN001, ANN202
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            rows, _total = await ResourceService(s).list_resources(
                PageParams(limit=50, offset=0), actor=made["tutor"], **kwargs
            )
            return sorted((r.name or "").replace(f"{env.tag} ", "") for r in rows)
        return go()
    return env.run(f)


def test_the_root_excludes_a_file_that_lives_in_a_folder(env) -> None:
    """The defect. Filing a document must take it out of the root listing."""
    assert _names(env, root_only=True) == ["loose.pdf"]


def test_the_root_still_includes_a_file_that_is_in_no_folder(env) -> None:
    """Without this the test above could be passing because `root_only` returns
    nothing at all."""
    assert "loose.pdf" in _names(env, root_only=True)


def test_without_root_only_every_file_is_listed(env) -> None:
    """The old behaviour, kept and pinned rather than removed: it is what a
    search across the whole library needs."""
    assert _names(env) == ["filed.pdf", "loose.pdf"]


def test_a_search_is_not_confined_to_the_root(env) -> None:
    """Browsing is scoped to where you are; searching spans the library, the way
    every file manager behaves. So `root_only` is dropped when a query is given
    -- otherwise searching from the root could never find a filed file, which is
    the only place most files are."""
    assert _names(env, root_only=True, query="filed") == ["filed.pdf"]


def test_naming_a_folder_still_wins_over_root_only(env) -> None:
    """A caller that sends both is asking for a folder's contents. Letting
    `root_only` override would make the folder unopenable."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            rows, _ = await ResourceService(s).list_resources(
                PageParams(limit=50, offset=0),
                actor=made["tutor"],
                folder_public_id=made["folder"].public_id,
                root_only=True,
            )
            return sorted((r.name or "").replace(f"{env.tag} ", "") for r in rows)
        return go()
    assert env.run(f) == ["filed.pdf"]


# ------------------------------------------------- the listing discloses ---
#
# Seeing a folder and being able to open it were decided by two different
# rules: `list_folders` returned whatever was at that level, while `get_folder`
# checked reachability. Found by sharing files with a tutor from another course
# and watching the console show them a folder that then answered "Folder not
# found" -- which is the harmless half. The harmful half is that the *names* of
# other people's course folders were readable by anyone who could call the
# endpoint.


def test_a_tutor_does_not_see_a_folder_from_a_course_they_do_not_teach(env) -> None:
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            rows = await ResourceService(s).list_folders(
                actor=made["outsider"], parent_public_id=None,
                course_public_id=None, batch_public_id=None,
            )
            return [r.name for r in rows]
        return go()

    assert env.run(f) == [], "The folder listing disclosed another course's folder."


def test_the_tutor_who_teaches_it_still_sees_it(env) -> None:
    """Without this the test above could be passing because the listing returns
    nothing to anybody."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            rows = await ResourceService(s).list_folders(
                actor=made["tutor"], parent_public_id=None,
                course_public_id=None, batch_public_id=None,
            )
            return [r.name.replace(f"{env.tag} ", "") for r in rows]
        return go()

    assert env.run(f) == ["folder"]


def test_what_the_listing_shows_is_what_can_be_opened(env) -> None:
    """The property that was broken, stated directly: every folder the listing
    returns must survive `get_folder`, because the console links one to the
    other and a link that 404s is a promise the API did not keep."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            svc = ResourceService(s)
            opened = []
            for actor_key in ("tutor", "outsider"):
                actor = made[actor_key]
                for row in await svc.list_folders(
                    actor=actor, parent_public_id=None,
                    course_public_id=None, batch_public_id=None,
                ):
                    # Raises NotFoundError if the two rules disagree.
                    await svc.get_folder(row.public_id, actor=actor)
                    opened.append((actor_key, row.name))
            return opened
        return go()

    # One entry: the teaching tutor's own folder, opened successfully.
    assert len(env.run(f)) == 1

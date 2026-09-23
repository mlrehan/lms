"""Staff-only material, and the four doors it must not leak through.

The brief asks for video and audio that colleagues can share without it
reaching students, guardians or corporate managers. That is an *audience* rule,
and the thing that makes it hard is that this module already has three separate
ways to reach a file -- a course or batch you belong to, an explicit permission
grant, and a direct person-to-person share -- plus a fourth, the public share
link, which bypasses authentication entirely.

A guard on `get()` alone would leave the list, the "shared with me" screen and
the public link open. So each is tested separately, and each with a positive
counterpart, because a refusal that is really "there was nothing there anyway"
proves nothing.

Driven against real Postgres with the real seeded roles: the whole rule is the
interaction between a permission held by three roles and withheld from three
others, which a hand-built actor with a made-up permission set cannot exercise.
"""

from __future__ import annotations

import asyncio
import selectors
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.core.errors import NotFoundError, ValidationError
from backend.db.manager import DatabaseManager
from backend.models.course import Course, TutorCourse
from backend.models.enrollment import Enrollments
from backend.models.batch import Batch
from backend.models.guardian import StudentGuardian
from backend.models.identity.role import Role
from backend.models.organization import (
    Organization,
    OrganizationManager,
    OrganizationMembership,
)
from backend.models.identity.user import User
from backend.models.resource import Resource, SharedResource
from backend.schemas.base import PageParams
from backend.schemas.resource import ResourceUpdateRequest
from backend.services.resource_service import ResourceService
from backend.utils.enums import (
    CourseStatus,
    EnrollmentStatus,
    OrganizationMembershipStatus,
    ResourcePermissionLevel as L,
    ResourceType,
    UserStatus,
)


@pytest.fixture()
def env():
    tag = "rm" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="restricted-media-tests")

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

        def user(kind: str, role: str) -> User:
            return User(
                username=f"{tag}.{kind}", slug=f"{tag}-{kind}", email=f"{tag}.{kind}@t.test",
                first_name=kind.title(), last_name="Person", hashed_password="x",
                status=UserStatus.ACTIVE, roles=[roles[role]],
            )

        people = {
            "tutor": user("tutor", "TUTOR"),
            "other_tutor": user("tutor2", "TUTOR"),
            "student": user("student", "STUDENT"),
            "guardian": user("guardian", "GUARDIAN"),
            "manager": user("manager", "CORPORATE_MANAGER"),
        }
        course = Course(title=f"{tag} course", code=f"{tag}-C", status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([*people.values(), course])
        await s.flush()

        s.add(TutorCourse(tutor_id=people["tutor"].id, course_id=course.id))
        s.add(TutorCourse(tutor_id=people["other_tutor"].id, course_id=course.id))

        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, is_active=True, capacity=10)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        s.add(batch)
        await s.flush()
        # Enrolled on the course, so every refusal below is about the audience
        # rule rather than about the student simply not being connected to it.
        org = Organization(name=f"{tag} Ltd", code=f"{tag}-O", is_active=True,
                           created_at=datetime.now(UTC))
        s.add(org)
        await s.flush()

        # The guardian and the manager reach this course only through the
        # student. Without these two rows their refusals below would pass for
        # the wrong reason -- they would be unable to see *any* file here, and
        # the audience rule would never be exercised at all.
        s.add(StudentGuardian(guardian_id=people["guardian"].id, student_id=people["student"].id,
                              relationship_type="Parent", is_primary=True,
                              created_at=datetime.now(UTC)))
        s.add(OrganizationManager(organization_id=org.id, user_id=people["manager"].id,
                                  is_active=True, invited_at=datetime.now(UTC)))
        s.add(OrganizationMembership(organization_id=org.id, user_id=people["student"].id,
                                     status=OrganizationMembershipStatus.ACTIVE,
                                     joined_at=datetime.now(UTC)))

        s.add(Enrollments(batch_id=batch.id, student_id=people["student"].id,
                          enrollment_date=datetime.now(UTC), status=EnrollmentStatus.CONFIRMED,
                          organization_id=org.id))

        def media(name: str, *, restricted: bool) -> Resource:
            row = Resource(
                name=f"{tag} {name}.mp4", resource_type=ResourceType.video,
                course_id=course.id, batch_id=batch.id, path=f"{tag}/{name}.mp4",
                mime_type="video/mp4", size=2048, uploaded_by=people["tutor"].id,
                modified_by=people["tutor"].id, is_deleted=False,
                is_restricted=restricted, created_at=datetime.now(UTC),
            )
            row.versions, row.shared_resources = [], []
            return row

        open_file, staff_only = media("open", restricted=False), media("staff", restricted=True)
        s.add_all([open_file, staff_only])
        await s.flush()
        return {"course": course, "open": open_file, "staff": staff_only, **people}

    ns = type("Env", (), dict(tag=tag, run=staticmethod(run), build=staticmethod(build)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"u": f"{tag}.%", "c": f"{tag}-%", "n": f"{tag}%"}
                res = "(SELECT id FROM resources WHERE name LIKE :n)"
                await s.execute(text(f"DELETE FROM shared_resources WHERE resource_id IN {res}"), p)
                await s.execute(text(f"DELETE FROM resource_permissions WHERE resource_id IN {res}"), p)
                await s.execute(text(f"DELETE FROM resource_versions WHERE resource_id IN {res}"), p)
                await s.execute(text("DELETE FROM resources WHERE name LIKE :n"), p)
                await s.execute(text("DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
                await s.execute(text("DELETE FROM batches WHERE batch_code LIKE :c"), p)
                await s.execute(text("DELETE FROM tutor_courses WHERE course_id IN (SELECT id FROM courses WHERE code LIKE :c)"), p)
                await s.execute(text("DELETE FROM courses WHERE code LIKE :c"), p)
                await s.execute(text("DELETE FROM student_guardians WHERE guardian_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM organization_managers WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM organization_memberships WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM organizations WHERE code LIKE :c"), p)
                await s.execute(text("DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM users WHERE username LIKE :u"), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


EXCLUDED = ["student", "guardian", "manager"]
STAFF = ["tutor", "other_tutor"]


def _open_as(env, who: str, which: str):  # noqa: ANN001, ANN202
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            return await ResourceService(s).get(made[which].public_id, actor=made[who])
        return go()
    return env.run(f)


# --------------------------------------------------------- door 1: opening ---


@pytest.mark.parametrize("who", EXCLUDED)
def test_the_excluded_roles_cannot_open_staff_material(env, who: str) -> None:
    """404, not 403: a file this person should never have been offered must not
    be provable to exist by the shape of the refusal."""
    with pytest.raises(NotFoundError):
        _open_as(env, who, "staff")


@pytest.mark.parametrize("who", EXCLUDED)
def test_but_they_can_still_open_ordinary_material(env, who: str) -> None:
    """The counterpart. Without it, every refusal above would also pass if the
    students simply could not reach the course at all."""
    assert _open_as(env, who, "open") is not None


@pytest.mark.parametrize("who", STAFF)
def test_staff_can_open_it(env, who: str) -> None:
    assert _open_as(env, who, "staff") is not None


# ------------------------------------------------------- door 2: the listing ---


def _listed(env, who: str) -> set[str]:
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            rows, _ = await ResourceService(s).list_resources(
                PageParams(limit=50, offset=0), actor=made[who],
                folder_public_id=None, course_public_id=None, resource_type=None,
                query=env.tag, include_deleted=False,
            )
            return {r.name or "" for r in rows}
        return go()
    return env.run(f)


def test_staff_material_is_absent_from_a_students_listing(env) -> None:
    """Filtered in the query rather than after it, so the paging total cannot
    reveal that there are files here they are not allowed to name."""
    names = _listed(env, "student")
    assert f"{env.tag} open.mp4" in names
    assert f"{env.tag} staff.mp4" not in names


def test_and_present_in_a_tutors(env) -> None:
    assert _listed(env, "tutor") == {f"{env.tag} open.mp4", f"{env.tag} staff.mp4"}


# --------------------------------------------------------- door 3: a share ---


def test_sharing_staff_material_with_a_student_is_refused(env) -> None:
    """Sharing is how this material travels between colleagues, so it is
    allowed -- but a share row the opener then refuses would read to the
    recipient as the system losing a file."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            with pytest.raises(ValidationError):
                await ResourceService(s).share(
                    made["staff"].public_id, [made["student"].public_id], actor=made["tutor"]
                )
            return True
        return go()

    assert env.run(f)


def test_sharing_it_with_another_tutor_works(env) -> None:
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            rows = await ResourceService(s).share(
                made["staff"].public_id, [made["other_tutor"].public_id], actor=made["tutor"]
            )
            return [r.level for r in rows]
        return go()

    assert env.run(f) == [L.VIEW]


def test_a_share_that_predates_the_restriction_stops_working(env) -> None:
    """The order that matters: a file can be shared first and restricted after,
    and restricting has to withdraw what was already handed out."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            s.add(SharedResource(
                resource_id=made["open"].id, shared_with_user_id=made["student"].id,
                shared_by_user_id=made["tutor"].id, level=L.VIEW, created_at=datetime.now(UTC),
            ))
            await s.flush()
            service = ResourceService(s)
            before = await service.get(made["open"].public_id, actor=made["student"])

            made["open"].is_restricted = True
            await s.flush()
            with pytest.raises(NotFoundError):
                await service.get(made["open"].public_id, actor=made["student"])
            return before is not None
        return go()

    assert env.run(f)


def test_a_share_grants_only_what_it_says(env) -> None:
    """`shared_resources.level` existed and was read by `effective_level`, but
    nothing ever *set* it, so every share took the server default and
    "watch it, don't keep it" could not be expressed at all."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            service = ResourceService(s)
            await service.share(
                made["open"].public_id, [made["student"].public_id],
                actor=made["tutor"], level=L.VIEW,
            )
            await s.flush()
            viewer = await service.effective_level(made["open"], made["student"])

            await service.share(
                made["open"].public_id, [made["student"].public_id],
                actor=made["tutor"], level=L.DOWNLOAD,
            )
            await s.flush()
            s.expire(made["open"], ["shared_resources"])
            raised = await service.effective_level(made["open"], made["student"])
            return viewer, raised
        return go()

    # Re-sharing changes the level; skipping an existing row would make
    # "share this read-only" silently do nothing to someone who already had it.
    assert env.run(f) == (L.VIEW, L.DOWNLOAD)


# ---------------------------------------------- door 4: the public link ---


def test_staff_material_cannot_be_given_a_public_link(env) -> None:
    """A link that needs no sign-in cannot respect an audience rule -- anyone
    holding the string is outside every check this platform makes."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            with pytest.raises(ValidationError):
                await ResourceService(s).set_share_link(
                    made["staff"].public_id, enabled=True, actor=made["tutor"]
                )
            return True
        return go()

    assert env.run(f)


def test_an_ordinary_file_still_can(env) -> None:
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            row = await ResourceService(s).set_share_link(
                made["open"].public_id, enabled=True, actor=made["tutor"]
            )
            return bool(row.share_token)
        return go()

    assert env.run(f)


def test_restricting_a_file_revokes_the_link_it_already_had(env) -> None:
    """The sequence an administrator would actually perform, and the one that
    leaves an unauthenticated door open if only the issue path is guarded."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            service = ResourceService(s)
            row = await service.set_share_link(
                made["open"].public_id, enabled=True, actor=made["tutor"]
            )
            await s.flush()
            token = row.share_token
            assert token
            # Reachable by anyone on the internet, right now.
            assert (await service.resolve_share_link(token))[0].id == made["open"].id

            await service.update(
                made["open"].public_id,
                ResourceUpdateRequest(is_restricted=True),
                actor=made["tutor"],
            )
            await s.flush()
            with pytest.raises(NotFoundError):
                await service.resolve_share_link(token)
            return True
        return go()

    assert env.run(f)


def test_a_student_cannot_mark_a_file_staff_only(env) -> None:
    """Otherwise anyone who could edit a file could hide it from the staff who
    own it -- a denial-of-access rather than a leak, but still theirs to lose."""
    from backend.core.errors import AuthorizationError

    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            service = ResourceService(s)
            s.add(SharedResource(
                resource_id=made["open"].id, shared_with_user_id=made["student"].id,
                shared_by_user_id=made["tutor"].id, level=L.EDIT, created_at=datetime.now(UTC),
            ))
            await s.flush()
            with pytest.raises(AuthorizationError):
                await service.update(
                    made["open"].public_id,
                    ResourceUpdateRequest(is_restricted=True),
                    actor=made["student"],
                )
            return True
        return go()

    assert env.run(f)

def test_a_token_that_outlived_the_restriction_still_opens_nothing(env) -> None:
    """The second line of defence, isolated.

    `update()` clears the token when a file is restricted, so the test above
    passes whether or not `resolve_share_link` checks anything -- a mutation
    that deleted its guard killed no test at all. Here the flag is set on the
    row directly, the way a migration, a backfill or a future code path that
    forgets could set it, leaving a live token behind. The token lookup then
    succeeds and the audience check is the only thing left to refuse it.
    """
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            service = ResourceService(s)
            row = await service.set_share_link(
                made["open"].public_id, enabled=True, actor=made["tutor"]
            )
            await s.flush()
            token = row.share_token
            assert token

            # Deliberately not through `update()`: the token survives.
            made["open"].is_restricted = True
            await s.flush()
            assert made["open"].share_token == token

            with pytest.raises(NotFoundError):
                await service.resolve_share_link(token)
            return True
        return go()

    assert env.run(f)

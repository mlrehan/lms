"""Who may watch a class back, and by which of the two routes.

A recording reaches a viewer one of two ways, and the difference is the point
of these tests. One **stored in the LMS** is streamed by us, so we decide
everything about it. One that lives on the **provider** can only be framed,
because the signed media URL behind a provider's player is bound to that
provider's own session and refuses our server -- so the most that can be
offered is a path of ours that re-checks permission and then redirects.

What must hold either way: the audience is everyone the session itself admits
-- the enrolled, their guardians, their corporate manager, the tutor, admins
-- and the provider's URL in the clear stays with the staff who set it.

Driven through `SessionService` against a real database, because the audience
is computed by `ScopeResolver` and a fake would only re-state the answer this
is meant to check.
"""

from __future__ import annotations

import asyncio
import random
import selectors
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.core.errors import NotFoundError
from backend.db.manager import DatabaseManager
from backend.main import app
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.guardian import StudentGuardian
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.organization import ManagedStudent
from backend.models.resource import Resource
from backend.security.password import hash_password
from backend.services.session_service import SessionService
from backend.utils.enums import (
    CourseStatus,
    EnrollmentStatus,
    Platforms,
    ResourceType,
    UserStatus,
)

LINK = "https://example.zoom.us/rec/share/abc123.def456"
PASSWORD = "Recording!2026"


@pytest.fixture()
def env():
    tag = f"rec{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="recording-tests")
    world: dict = {}
    start = datetime.now(timezone.utc) - timedelta(days=1)

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

        def user(name: str, role: str) -> User:
            return User(
                username=f"{tag}.{name}", slug=f"{tag}-{name}",
                email=f"{tag}.{name}@t.test",
                hashed_password=hash_password(PASSWORD),
                status=UserStatus.ACTIVE, can_login=True, roles=[roles[role]],
            )

        tutor = user("tutor", "TUTOR")
        student = user("student", "STUDENT")
        guardian = user("guardian", "GUARDIAN")
        manager = user("manager", "CORPORATE_MANAGER")
        # An outsider of each kind, so a pass cannot come from "this role is
        # simply allowed": a student in no batch of ours, and a manager who
        # looks after nobody here.
        outsider = user("outsider", "STUDENT")
        stranger = user("stranger", "CORPORATE_MANAGER")

        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([tutor, student, guardian, manager, outsider, stranger, course])
        await s.flush()

        now = datetime.now(timezone.utc)
        s.add(StudentGuardian(guardian_id=guardian.id, student_id=student.id,
                              relationship_type="Parent", is_primary=True, created_at=now))
        s.add(ManagedStudent(manager_id=manager.id, student_id=student.id, created_at=now))

        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=30), is_active=True, capacity=10)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        s.add(batch)
        await s.flush()

        def session_row(link, nth):  # noqa: ANN001, ANN202
            # Distinct start times: `ux_batch_sessions_batch_start` is one
            # class per batch per moment, which is correct and not what this
            # file is about.
            begins = start + timedelta(hours=3 * nth)
            row = BatchSession(batch_id=batch.id, tutor_id=tutor.id,
                               session_start_time=begins,
                               session_end_time=begins + timedelta(hours=2),
                               duration_minutes=120, platform=Platforms.Zoom,
                               recording_link=link)
            row.attendances = []
            return row

        linked, bare = session_row(LINK, 0), session_row(None, 1)
        stored = session_row(LINK, 2)  # a link *and* a stored file, so precedence is checkable

        file = Resource(resource_type=ResourceType.video, name=f"{tag} class.mp4",
                        path=f"recordings/{tag}.mp4", mime_type="video/mp4", size=1024,
                        uploaded_by=tutor.id, created_at=now)
        s.add_all([linked, bare, stored, file])
        await s.flush()
        stored.recording_resource_id = file.id

        s.add(Enrollments(batch_id=batch.id, student_id=student.id,
                          enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
        await s.flush()
        world.update(linked=linked.public_id, bare=bare.public_id, stored=stored.public_id)

    run(build)

    lifespan = app.router.lifespan_context(app)
    loop.run_until_complete(lifespan.__aenter__())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")
    tokens: dict[str, str] = {}

    def call(who: str, method: str, path: str, **kwargs):  # noqa: ANN202
        async def go():  # noqa: ANN202
            if who not in tokens:
                signed_in = await client.post(
                    "/api/v1/auth/login",
                    json={"identifier": f"{tag}.{who}@t.test", "password": PASSWORD},
                )
                assert signed_in.status_code == 200, signed_in.text[:200]
                tokens[who] = signed_in.json()["access_token"]
            return await client.request(
                method, f"/api/v1{path}",
                headers={"Authorization": f"Bearer {tokens[who]}"}, **kwargs,
            )
        return loop.run_until_complete(go())

    ns = type("Env", (), dict(tag=tag, world=world, run=staticmethod(run),
                              call=staticmethod(call)))
    try:
        yield ns
    finally:
        loop.run_until_complete(client.aclose())
        loop.run_until_complete(lifespan.__aexit__(None, None, None))
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                await s.execute(text("UPDATE batch_sessions SET recording_resource_id = NULL WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
                await s.execute(text("DELETE FROM resources WHERE name LIKE :t"), p)
                await s.execute(text("DELETE FROM student_guardians WHERE guardian_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM manager_students WHERE manager_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
                await s.execute(text("DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
                await s.execute(text("DELETE FROM batches WHERE batch_code LIKE :c"), p)
                await s.execute(text("DELETE FROM courses WHERE title LIKE :t"), p)
                await s.execute(text("DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM users WHERE username LIKE :u"), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _view(env, username, which="linked"):  # noqa: ANN001, ANN202
    async def go(s):  # noqa: ANN001, ANN202
        actor = (await s.execute(select(User).where(User.username == username))).scalar_one()
        view = await SessionService(s).recording(env.world[which], actor=actor)
        # Read what is needed before the session closes and the rows detach.
        return {
            "playback_url": view.playback_url,
            "embed_url": view.embed_url,
            "external_url": view.external_url,
        }
    return env.run(go)


@pytest.mark.parametrize("who", ["student", "guardian", "manager", "tutor"])
def test_everyone_the_class_admits_can_watch_a_provider_recording(env, who) -> None:
    """The reported bug, as a test: a tutor pastes a provider link, and the
    people entitled to the class get nothing to play.

    All four are here rather than only the student, because each reaches the
    session by a different rule -- enrolment, guardianship, a manager link,
    teaching it -- and the recording must not be the one thing that forgets
    three of them.
    """
    view = _view(env, f"{env.tag}.{who}")
    assert view["embed_url"] == f"/sessions/{env.world['linked']}/recording/embed"


def test_the_providers_own_url_stays_with_the_staff_who_set_it(env) -> None:
    """`embed_url` is a path that checks on every request; the provider link
    works for anyone holding it, signed out, for as long as it lives. So the
    viewer gets the first and only staff get the second."""
    assert _view(env, f"{env.tag}.student")["external_url"] is None
    assert _view(env, f"{env.tag}.guardian")["external_url"] is None
    assert _view(env, f"{env.tag}.manager")["external_url"] is None
    assert _view(env, f"{env.tag}.tutor")["external_url"] == LINK


@pytest.mark.parametrize("who", ["outsider", "stranger"])
def test_the_class_is_not_provable_to_exist_to_someone_outside_it(env, who) -> None:
    """404, not an empty recording: a refusal that confirms the session is
    there is the thing `visible_session_ids` exists to avoid."""
    with pytest.raises(NotFoundError):
        _view(env, f"{env.tag}.{who}")


def test_a_stored_recording_wins_over_the_providers_player(env) -> None:
    """We serve those bytes ourselves -- ranged, re-checked, no download
    control but our own. Offering the frame as well would hand the viewer a
    worse route to the same class."""
    view = _view(env, f"{env.tag}.student", which="stored")
    assert view["playback_url"] == f"/sessions/{env.world['stored']}/recording/stream"
    assert view["embed_url"] is None


def test_a_class_with_no_recording_offers_nothing(env) -> None:
    view = _view(env, f"{env.tag}.student", which="bare")
    assert view == {"playback_url": None, "embed_url": None, "external_url": None}


def test_the_redirect_is_authorised_in_its_own_right(env) -> None:
    """The browser asks for this separately, when it frames the player, so it
    carries its own check rather than trusting the page that led here."""
    def embed(username, which):  # noqa: ANN001, ANN202
        async def go(s):  # noqa: ANN001, ANN202
            actor = (await s.execute(select(User).where(User.username == username))).scalar_one()
            return await SessionService(s).resolve_recording_embed(env.world[which], actor=actor)
        return env.run(go)

    assert embed(f"{env.tag}.student", "linked") == LINK

    with pytest.raises(NotFoundError):
        embed(f"{env.tag}.outsider", "linked")

    # Nothing published: there is no link to be redirected to, and saying so
    # must not depend on the caller guessing the URL shape.
    with pytest.raises(NotFoundError):
        embed(f"{env.tag}.student", "bare")


def test_watching_is_recorded_whichever_route_it_took(env) -> None:
    """The audit trail used to be written only for a stored file, so a class
    watched through the provider left no trace that anyone had watched it."""
    async def go(s):  # noqa: ANN001, ANN202
        actor = (await s.execute(
            select(User).where(User.username == f"{env.tag}.student")
        )).scalar_one()
        await SessionService(s).recording(env.world["linked"], actor=actor, audit=True)
        await s.flush()
        return (await s.execute(text(
            "SELECT details FROM audit_logs"
            " WHERE actor_email = :e AND action = 'RECORDING_VIEW'"
        ), {"e": f"{env.tag}.student@t.test"})).scalars().all()
    assert len(env.run(go)) == 1


# -- over HTTP, because the redirect is a response and not a return value -----


def test_a_student_is_redirected_to_the_player_on_request(env) -> None:
    """The browser frames this path; what it gets back must be a redirect it
    will follow, carrying the provider's URL and nothing cacheable.

    Driven over HTTP rather than through the service because a 307 is made of
    a status and a header, and a function returning the right string proves
    neither.
    """
    response = env.call("student", "GET", f"/sessions/{env.world['linked']}/recording/embed")
    assert response.status_code == 307
    assert response.headers["location"] == LINK
    # One admission, to this caller, now: a cache between us and them must not
    # be able to repeat it.
    assert "no-store" in response.headers["cache-control"]
    # The provider is not told which page of ours the viewer came from.
    assert response.headers["referrer-policy"] == "no-referrer"


def test_the_embed_path_refuses_someone_outside_the_class(env) -> None:
    assert env.call("outsider", "GET", f"/sessions/{env.world['linked']}/recording/embed").status_code == 404


def test_the_session_payload_tells_a_student_there_is_something_to_watch(env) -> None:
    """`has_recording` drove a badge that was only ever true for staff, so the
    timetable told a student their recorded class had no recording."""
    body = env.call("student", "GET", f"/sessions/{env.world['linked']}").json()
    assert body["has_recording"] is True
    assert body["recording_link"] is None  # still not handed the URL itself

    bare = env.call("student", "GET", f"/sessions/{env.world['bare']}").json()
    assert bare["has_recording"] is False

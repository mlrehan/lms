"""Who may enter a class, and when.

The link is withheld by the API rather than hidden by the page, so these tests
ask the service the question the endpoint asks: is this caller admitted, right
now, and does the answer carry a link. Driven against real Postgres with real
seeded roles, because the whole point is the interaction between row scope
(which batch is mine) and a permission (`session.override`) -- neither of which
a hand-built actor would exercise.
"""

from __future__ import annotations

import asyncio
import random
import selectors
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.core.errors import ConflictError, NotFoundError
from backend.db.manager import DatabaseManager
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.resource import Resource
from backend.services.session_service import SessionService
from backend.utils.enums import (
    CourseStatus,
    EnrollmentStatus,
    Platforms,
    ResourceType,
    UserStatus,
)

LINK = "https://zoom.example.test/j/1234567890"

# Three sessions, chosen so that every boundary of the rule is exercised by a
# real row rather than by arithmetic on one: one running now, one too far off
# to join, one that finished long ago.
NOW = datetime.now(timezone.utc)
SLOTS = {
    "live": NOW - timedelta(minutes=5),
    "soon": NOW + timedelta(hours=6),
    "over": NOW - timedelta(days=3),
}


@pytest.fixture()
def env():
    tag = f"join{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="join-tests")
    world: dict = {}

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

        def user(name: str, role: str) -> User:
            return User(username=f"{tag}.{name}", slug=f"{tag}-{name}", email=f"{tag}.{name}@t.test",
                        hashed_password="x", status=UserStatus.ACTIVE, roles=[roles[role]])

        tutor, student, outsider = user("tutor", "TUTOR"), user("stu", "STUDENT"), user("out", "STUDENT")
        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([tutor, student, outsider, course])
        await s.flush()

        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=30), is_active=True, capacity=10)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        s.add(batch)
        await s.flush()

        for name, start in SLOTS.items():
            row = BatchSession(
                batch_id=batch.id, tutor_id=tutor.id, session_start_time=start,
                session_end_time=start + timedelta(hours=1), duration_minutes=60,
                platform=Platforms.Zoom,
                # The "over" session deliberately has no link, so "the class is
                # shut" and "there is no link" are never proved by the same row.
                meeting_link=LINK if name != "over" else None,
            )
            row.attendances = []
            s.add(row)
            await s.flush()
            world[name] = row.public_id

        # A recording stored *in* the LMS, published to the class that has
        # already happened. `recording_link` on the same row is the provider's
        # own URL, so one session exercises both halves of the rule.
        recording = Resource(
            name=f"{tag} class recording.mp4", resource_type=ResourceType.video,
            course_id=course.id, batch_id=batch.id, path=f"{tag}/recording.mp4",
            mime_type="video/mp4", size=4096, uploaded_by=tutor.id, modified_by=tutor.id,
            is_deleted=False, created_at=datetime.now(timezone.utc),
        )
        recording.versions, recording.shared_resources = [], []
        s.add(recording)
        await s.flush()
        over = (await s.execute(select(BatchSession).where(BatchSession.public_id == world["over"]))).scalar_one()
        over.recording_resource_id = recording.id
        over.recording_link = "https://zoom.example.test/rec/abc123"

        s.add(Enrollments(batch_id=batch.id, student_id=student.id,
                          enrollment_date=datetime.now(timezone.utc), status=EnrollmentStatus.CONFIRMED))
        await s.flush()
        world["recording"] = recording.public_id
        world.update(tutor=tutor.username, student=student.username, outsider=outsider.username)

    run(build)
    ns = type("Env", (), dict(tag=tag, world=world, run=staticmethod(run)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                # `audit_logs` is deliberately not cleaned: a database trigger
                # refuses DELETE on it, which is the property Phase 8 of this
                # codebase exists to guarantee. The rows carry the run's tag and
                # no FK to `users`, so they survive this teardown by design.
                await s.execute(text("UPDATE batch_sessions SET recording_resource_id = NULL WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
                await s.execute(text("DELETE FROM resource_versions WHERE resource_id IN (SELECT id FROM resources WHERE name LIKE :t)"), p)
                await s.execute(text("DELETE FROM resources WHERE name LIKE :t"), p)
                await s.execute(text("DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
                await s.execute(text("DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
                await s.execute(text("DELETE FROM batches WHERE batch_code LIKE :c"), p)
                await s.execute(text("DELETE FROM courses WHERE title LIKE :t"), p)
                await s.execute(text("DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM users WHERE username LIKE :u"), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _join(env, username: str, which: str):  # noqa: ANN001, ANN202
    async def g(s):  # noqa: ANN001, ANN202
        actor = (await s.execute(select(User).where(User.username == username))).scalar_one()
        ticket = await SessionService(s).join(env.world[which], actor=actor)
        return {"link": ticket.meeting_link, "overridden": ticket.overridden}
    return env.run(g)


def _state(env, username: str, which: str):  # noqa: ANN001, ANN202
    async def g(s):  # noqa: ANN001, ANN202
        actor = (await s.execute(select(User).where(User.username == username))).scalar_one()
        service = SessionService(s)
        row = await service.get(env.world[which], actor=actor)
        state = service.join_state(row, actor=actor)
        return {"can_join_now": state.can_join_now, "manage": service.can_manage(actor)}
    return env.run(g)


# ---------------------------------------------------------- inside the window ---


def test_a_student_in_the_batch_is_admitted_to_a_running_class(env) -> None:
    assert _join(env, env.world["student"], "live")["link"] == LINK


def test_the_tutor_is_admitted_to_their_own_class(env) -> None:
    assert _join(env, env.world["tutor"], "live")["link"] == LINK


# --------------------------------------------------------- outside the window ---


def test_a_class_six_hours_away_is_refused_and_says_when(env) -> None:
    """The refusal carries both times, so the client can render a countdown
    without ever having been given the link to count down to."""
    with pytest.raises(ConflictError) as raised:
        _join(env, env.world["student"], "soon")
    details = raised.value.details or {}
    assert "opens_at" in details and "closes_at" in details


def test_an_administrator_may_override_a_shut_door_and_it_is_marked(env) -> None:
    """`session.override` is the authorised exception the brief asks for. The
    ticket says it was used, so "they were let in early" is never inferred from
    silence."""
    result = _join(env, "superadmin", "soon")
    assert result["link"] == LINK
    assert result["overridden"] is True


def test_an_ordinary_join_is_not_marked_as_an_override(env) -> None:
    """Otherwise the flag above could be true for every join and prove nothing."""
    assert _join(env, "superadmin", "live")["overridden"] is False


# ------------------------------------------------------------ other refusals ---


def test_someone_not_in_the_batch_cannot_even_see_the_class(env) -> None:
    """404, not 403: a class an outsider has no route to must not be provable
    to exist by the shape of the refusal."""
    with pytest.raises(NotFoundError):
        _join(env, env.world["outsider"], "live")


def test_a_class_with_no_link_says_so_rather_than_denying_access(env) -> None:
    """The caller is entitled to join; the tutor has not recorded a link. A
    student reporting "access denied" for a scheduling omission sends everyone
    to the wrong place."""
    with pytest.raises(ConflictError) as raised:
        _join(env, "superadmin", "over")
    assert "link" in str(raised.value).lower()


# ------------------------------------------------------- what a listing says ---


def test_a_student_is_told_they_may_join_without_being_given_the_link(env) -> None:
    state = _state(env, env.world["student"], "live")
    assert state["can_join_now"] is True
    assert state["manage"] is False      # so the response withholds meeting_link


def test_a_student_is_told_they_may_not_join_a_class_six_hours_away(env) -> None:
    assert _state(env, env.world["student"], "soon")["can_join_now"] is False


def test_the_override_holder_is_told_the_button_is_live_even_when_shut(env) -> None:
    """`join_state` and `join` must agree, or the console offers a button that
    refuses, or hides one that would have worked."""
    assert _state(env, "superadmin", "soon")["can_join_now"] is True


# ------------------------------------------------------------- recordings ---


def _recording(env, username: str, which: str = "over"):  # noqa: ANN001, ANN202
    async def g(s):  # noqa: ANN001, ANN202
        actor = (await s.execute(select(User).where(User.username == username))).scalar_one()
        view = await SessionService(s).recording(env.world[which], actor=actor)
        return {
            "playback_url": view.playback_url,
            "external_url": view.external_url,
            "name": view.resource.name if view.resource else None,
        }
    return env.run(g)


def test_a_student_gets_a_playback_path_on_this_api(env) -> None:
    view = _recording(env, env.world["student"])
    assert view["playback_url"] == f"/sessions/{env.world['over']}/recording/stream"
    assert view["name"] is not None


def test_a_student_is_never_handed_the_providers_own_link(env) -> None:
    """The brief's requirement, and the reason playback is a stream rather than
    a redirect: the provider's URL works for anyone holding the string."""
    assert _recording(env, env.world["student"])["external_url"] is None


def test_staff_do_get_the_providers_link_because_they_set_it(env) -> None:
    """The positive half: withholding it from everyone would make the field
    unreadable by the people who maintain it, and this test is what stops the
    refusal above passing for that reason."""
    assert _recording(env, env.world["tutor"])["external_url"] == "https://zoom.example.test/rec/abc123"


def test_a_class_with_no_stored_recording_offers_no_playback(env) -> None:
    assert _recording(env, env.world["student"], "live")["playback_url"] is None


def test_an_outsider_cannot_reach_the_recording_at_all(env) -> None:
    with pytest.raises(NotFoundError):
        _recording(env, env.world["outsider"])


def test_withdrawing_the_file_stops_playback_immediately(env) -> None:
    """Soft-delete must not be cosmetic for anyone who still has the page open;
    the stream re-reads this on every request, including every seek."""
    def g(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            resource = (await s.execute(select(Resource).where(Resource.public_id == env.world["recording"]))).scalar_one()
            resource.is_deleted = True
            await s.flush()
            actor = (await s.execute(select(User).where(User.username == env.world["student"]))).scalar_one()
            service = SessionService(s)
            view = await service.recording(env.world["over"], actor=actor)
            with pytest.raises(NotFoundError):
                await service.resolve_recording_stream(env.world["over"], actor=actor)
            return view.playback_url
        return go()

    assert env.run(g) is None


def test_a_student_cannot_publish_a_recording_to_the_class(env) -> None:
    """Publishing needs EDIT on the file, not merely the ability to see it --
    otherwise anyone shown a document could play it to a whole batch."""
    from backend.core.errors import AuthorizationError

    def g(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            actor = (await s.execute(select(User).where(User.username == env.world["student"]))).scalar_one()
            with pytest.raises(AuthorizationError):
                await SessionService(s).attach_recording(
                    env.world["live"], resource_public_id=env.world["recording"], actor=actor
                )
            return True
        return go()

    assert env.run(g)

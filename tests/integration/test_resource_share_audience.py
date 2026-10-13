"""Who a tutor may hand a file to, and what the picker is allowed to say.

Before this, `resource.update` meant a tutor could share any file they managed
with **any user id in the system** -- the request body named the recipients and
nothing read it back against a rule. The picker only ever showed sensible
people, which is exactly why it went unnoticed: the control was in the UI, and
the UI is not where controls live.

Two things are therefore pinned here:

* the **audience**, for both directions -- what the picker offers, and what the
  write accepts, which must be the same set or the picker is lying;
* that **no email address or login name is in any of it**. In this deployment
  the login name *is* the address, so a list of "who has this file" would
  otherwise be a way to harvest them, read dozens of times a day.
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
from backend.core.errors import AuthorizationError
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
from backend.services.resource_audience import ResourceShareAudience
from backend.services.resource_service import ResourceService
from backend.utils.enums import (
    CourseStatus,
    EnrollmentStatus,
    Platforms,
    ResourcePermissionLevel,
    ResourceType,
    UserStatus,
)

PASSWORD = "ShareAudience!2026"


@pytest.fixture()
def env():
    tag = f"shr{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="share-audience-tests")
    ids: dict[str, int] = {}
    pub: dict[str, object] = {}

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

        def user(name: str, role: str, first: str, last: str) -> User:
            return User(
                username=f"{tag}.{name}@t.test", slug=f"{tag}-{name}",
                email=f"{tag}.{name}@t.test", first_name=first, last_name=last,
                hashed_password=hash_password(PASSWORD), can_login=True,
                status=UserStatus.ACTIVE, roles=[roles[role]],
            )

        people = {
            "admin": user("admin", "ADMIN", "Avery", f"Admin{tag}"),
            # Two tutors, so "mine" and "a colleague's" are different sets.
            "tutor": user("tutor", "TUTOR", "Tamsin", f"Tutor{tag}"),
            "other_tutor": user("othertutor", "TUTOR", "Oscar", f"Other{tag}"),
            # Two students with the *same first name*: the case the batch and
            # course columns exist for.
            "mine": user("mine", "STUDENT", "Sarah", f"Mine{tag}"),
            "theirs": user("theirs", "STUDENT", "Sarah", f"Theirs{tag}"),
            "guardian_mine": user("gmine", "GUARDIAN", "Gina", f"GMine{tag}"),
            "guardian_theirs": user("gtheirs", "GUARDIAN", "Gus", f"GTheirs{tag}"),
            "manager": user("mgr", "CORPORATE_MANAGER", "Mel", f"Mgr{tag}"),
            # An account with no name recorded, which is ordinary in real
            # data. Every directory in this codebase falls back to the login
            # name for these -- and here the login name is an email address,
            # so this one account is the difference between "no addresses in
            # the response" and "an address for everybody who never filled in
            # their profile".
            "nameless": user("nameless", "STUDENT", None, None),
        }
        course_mine = Course(title=f"{tag} Biology", code=f"{tag}b", status=CourseStatus.PUBLISHED)
        course_other = Course(title=f"{tag} Chemistry", code=f"{tag}c", status=CourseStatus.PUBLISHED)
        for c in (course_mine, course_other):
            c.batches, c.resources, c.tags, c.tutors = [], [], [], []
        s.add_all([*people.values(), course_mine, course_other])
        await s.flush()

        now = datetime.now(timezone.utc)
        s.add(StudentGuardian(guardian_id=people["guardian_mine"].id, student_id=people["mine"].id,
                              relationship_type="Parent", is_primary=True, created_at=now))
        s.add(StudentGuardian(guardian_id=people["guardian_theirs"].id, student_id=people["theirs"].id,
                              relationship_type="Parent", is_primary=True, created_at=now))
        # A manager who looks after a student this tutor teaches: still not an
        # audience for the tutor's class material.
        s.add(ManagedStudent(manager_id=people["manager"].id, student_id=people["mine"].id,
                             created_at=now))

        batches = {}
        for key, course in (("mine", course_mine), ("theirs", course_other)):
            b = Batch(batch_code=f"{tag}-{key}", course_id=course.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=30), is_active=True, capacity=10)
            b.sessions, b.enrollments, b.student_reviews = [], [], []
            s.add(b)
            batches[key] = b
        await s.flush()

        start = datetime.now(timezone.utc) + timedelta(days=1)
        for key, teacher in (("mine", "tutor"), ("theirs", "other_tutor")):
            row = BatchSession(batch_id=batches[key].id, tutor_id=people[teacher].id,
                               session_start_time=start, session_end_time=start + timedelta(hours=1),
                               duration_minutes=60, platform=Platforms.Zoom)
            row.attendances = []
            s.add(row)

        for student, key in (("mine", "mine"), ("theirs", "theirs"), ("nameless", "mine")):
            s.add(Enrollments(batch_id=batches[key].id, student_id=people[student].id,
                              enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
        # `mine` is also in the colleague's batch. A tutor must see the cohort
        # *they* teach beside the name, not every cohort the student is in.
        s.add(Enrollments(batch_id=batches["theirs"].id, student_id=people["mine"].id,
                          enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
        await s.flush()

        files = []
        for n in (1, 2):
            f = Resource(resource_type=ResourceType.lecture_sheet, name=f"{tag} sheet {n}.pdf",
                         path=f"resources/{tag}-{n}.pdf", mime_type="application/pdf", size=10,
                         batch_id=batches["mine"].id, uploaded_by=people["tutor"].id,
                         created_at=now)
            s.add(f)
            files.append(f)
        await s.flush()

        for key, person in people.items():
            ids[key] = person.id
            pub[key] = person.public_id
        pub["file1"], pub["file2"] = files[0].public_id, files[1].public_id
        pub["batch_mine"] = f"{tag}-mine"
        pub["batch_theirs"] = f"{tag}-theirs"

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

    ns = type("Env", (), dict(tag=tag, ids=ids, pub=pub, run=staticmethod(run),
                              call=staticmethod(call)))
    try:
        yield ns
    finally:
        loop.run_until_complete(client.aclose())
        loop.run_until_complete(lifespan.__aexit__(None, None, None))

        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                users = "(SELECT id FROM users WHERE username LIKE :u)"
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                for stmt in (
                    "DELETE FROM shared_resources WHERE resource_id IN "
                    "(SELECT id FROM resources WHERE name LIKE :t)",
                    "DELETE FROM resources WHERE name LIKE :t",
                    f"DELETE FROM student_guardians WHERE guardian_id IN {users}",
                    f"DELETE FROM manager_students WHERE manager_id IN {users}",
                    "DELETE FROM batch_sessions WHERE batch_id IN "
                    "(SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM enrollments WHERE batch_id IN "
                    "(SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM batches WHERE batch_code LIKE :c",
                    "DELETE FROM courses WHERE title LIKE :t",
                    f"DELETE FROM user_roles WHERE user_id IN {users}",
                    "DELETE FROM users WHERE username LIKE :u",
                ):
                    await s.execute(text(stmt), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _audience(env, who: str, **query):  # noqa: ANN202
    response = env.call(who, "GET", "/resources/share-audience", params={"limit": 100, **query})
    assert response.status_code == 200, response.text[:300]
    return response


def _names(payload) -> set[str]:  # noqa: ANN001
    return {row["name"] for row in payload}


def test_a_tutor_reaches_their_own_class_and_stops_there(env) -> None:
    """A colleague's *student* and that student's guardian are outside it,
    and so is a manager who employs one of this tutor's own students.

    The manager is the interesting one: they may read that student's grades,
    so "can see them" and "may be sent their class material" are different
    questions, and this is where they part.

    A colleague is out too: material travels upwards to an administrator, not
    sideways between peers, because who sees a class's material is a decision
    for the people running the institution.
    """
    rows = _audience(env, "tutor").json()
    names = _names(rows)

    assert f"Sarah Mine{env.tag}" in names          # a student they teach
    assert f"Gina GMine{env.tag}" in names          # that student's guardian
    assert f"Avery Admin{env.tag}" in names         # the administrators

    assert f"Oscar Other{env.tag}" not in names     # another tutor
    assert f"Sarah Theirs{env.tag}" not in names    # a colleague's student
    assert f"Gus GTheirs{env.tag}" not in names     # that student's guardian
    assert f"Mel Mgr{env.tag}" not in names         # an employer of their student


def test_the_batch_and_course_shown_are_the_sharers_own(env) -> None:
    """Two students called Sarah is the ordinary case, not a contrived one --
    which is why the cohort has to be on the row. And the cohort shown is the
    tutor's: `Sarah Mine` is also in the colleague's batch, and surfacing that
    would both leak a class the tutor has nothing to do with and bury the line
    that identifies her here.
    """
    row = next(r for r in _audience(env, "tutor").json() if r["name"] == f"Sarah Mine{env.tag}")
    codes = {p["batch_code"] for p in row["placements"]}
    titles = {p["course_title"] for p in row["placements"]}

    assert codes == {env.pub["batch_mine"]}
    assert titles == {f"{env.tag} Biology"}
    assert row["role"] == "Student"


def test_a_guardian_is_identified_by_the_student_not_by_themselves(env) -> None:
    """"Gina GMine" means nothing to a tutor; "Guardian of Sarah Mine, batch
    X" is the whole reason they can pick the right one."""
    row = next(r for r in _audience(env, "tutor").json() if r["name"] == f"Gina GMine{env.tag}")
    assert row["relation"] == f"Guardian of Sarah Mine{env.tag}"
    assert {p["batch_code"] for p in row["placements"]} == {env.pub["batch_mine"]}


def test_an_administrator_reaches_everybody(env) -> None:
    names = _names(_audience(env, "admin", query=env.tag).json())
    assert f"Sarah Theirs{env.tag}" in names
    assert f"Mel Mgr{env.tag}" in names
    assert f"Oscar Other{env.tag}" in names


def test_no_address_and_no_login_name_is_anywhere_in_it(env) -> None:
    """The strongest form of this assertion available: not "the email field is
    absent" but "the response contains no address at all", which also catches
    one arriving through a name, a relation or a course title."""
    for who in ("tutor", "admin"):
        body = _audience(env, who, query=env.tag).text
        assert "@" not in body, body[:300]
        assert env.tag + "." not in body  # the login-name shape, e.g. `shr123.mine`


def test_an_account_with_no_name_is_not_named_by_its_address(env) -> None:
    """The fallback every other directory uses would print the login name
    here, and the login name is the address. A placeholder is the right answer:
    it is visibly a data problem an administrator can fix, rather than a
    disclosure nobody notices."""
    rows = _audience(env, "tutor", query=None).json()
    nameless = [r for r in rows if r["name"] == "Unnamed account"]
    assert len(nameless) == 1
    assert "@" not in nameless[0]["name"]


def test_the_share_list_names_people_without_naming_their_address(env) -> None:
    """Read as an administrator on purpose: they hold `user.view_contact`, so
    the privacy helper every other screen uses would hand *them* the login
    name. "Who has this file" is not a contact directory."""
    shared = env.call("admin", "POST", "/resources/share", json={
        "resource_ids": [str(env.pub["file1"])],
        "user_ids": [str(env.pub["nameless"])],
        "level": "VIEW",
    })
    assert shared.status_code == 200, shared.text[:300]
    assert "@" not in shared.text, shared.text[:300]
    assert shared.json()[0]["shared_with_name"] == "Unnamed account"


def test_the_directory_cannot_be_used_to_confirm_an_address(env) -> None:
    """Searching by name works; searching by the address does not, so the box
    cannot be used to check whether a given address is on the platform."""
    assert _names(_audience(env, "tutor", query="Sarah").json()) == {f"Sarah Mine{env.tag}"}
    assert _audience(env, "tutor", query=f"{env.tag}.mine@t.test").json() == []


# -- the gate, which is the half that actually protects anything -------------


def test_the_write_refuses_a_recipient_the_picker_would_not_offer(env) -> None:
    """A hand-made request, which is the only way this ever happens: the
    picker offers the right people and the body is still the client's."""
    async def go(s):  # noqa: ANN001, ANN202
        tutor = await s.get(User, env.ids["tutor"])
        with pytest.raises(AuthorizationError):
            await ResourceService(s).share(
                env.pub["file1"], [env.pub["theirs"]], actor=tutor,
                level=ResourcePermissionLevel.VIEW,
            )
    env.run(go)


def test_one_bad_recipient_writes_nothing_at_all(env) -> None:
    """All or nothing. A partial share is the worst outcome: the sharer is
    told it failed and half the class has the file anyway."""
    async def go(s):  # noqa: ANN001, ANN202
        tutor = await s.get(User, env.ids["tutor"])
        service = ResourceService(s)
        with pytest.raises(AuthorizationError):
            await service.share_many(
                [env.pub["file1"], env.pub["file2"]],
                [env.pub["mine"], env.pub["theirs"]],
                actor=tutor, level=ResourcePermissionLevel.VIEW,
            )
        rows = (await s.execute(text(
            "SELECT count(*) FROM shared_resources WHERE resource_id IN "
            "(SELECT id FROM resources WHERE name LIKE :t)"
        ), {"t": f"{env.tag}%"})).scalar_one()
        return rows
    assert env.run(go) == 0


def test_several_files_reach_several_people_in_one_act(env) -> None:
    response = env.call("tutor", "POST", "/resources/share", json={
        "resource_ids": [str(env.pub["file1"]), str(env.pub["file2"])],
        "user_ids": [str(env.pub["mine"]), str(env.pub["guardian_mine"])],
        "level": "VIEW",
    })
    assert response.status_code == 200, response.text[:300]
    rows = response.json()
    assert len(rows) == 4
    assert {r["shared_with_name"] for r in rows} == {
        f"Sarah Mine{env.tag}", f"Gina GMine{env.tag}",
    }
    # The share list is read constantly; it must not become an address book.
    assert "@" not in response.text


def test_a_student_cannot_share_at_all(env) -> None:
    assert env.call("mine", "GET", "/resources/share-audience").status_code == 403
    assert env.call("mine", "POST", "/resources/share", json={
        "resource_ids": [str(env.pub["file1"])],
        "user_ids": [str(env.pub["theirs"])],
    }).status_code == 403

"""Folder sharing, duplicate shares, course grouping and the twelve-file timeout.

Driven against real Postgres, because every property here is about rows: a
folder share is one row whose reach is computed from the tree, a duplicate is
refused by a unique constraint, and the timeout was thousands of queries.

The fixture is deliberately not kind:

* the student is in **two courses**, so grouping by course can be wrong;
* the shared folder has a **sibling** and a **parent**, so "the share stays
  inside its folder" has something to escape into;
* there is a **staff-only file inside the shared folder**, so inheritance has
  to respect the restriction rather than override it;
* the same file is shared **directly and through the folder**, so revoking
  the folder share has something to wrongly take away.
"""

from __future__ import annotations

import asyncio
import random
import selectors
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import event, select, text

from backend.core.config import get_settings
from backend.core.errors import AuthorizationError, NotFoundError, ValidationError
from backend.db.manager import DatabaseManager
from backend.main import app
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.guardian import StudentGuardian
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.resource import Resource, ResourceFolder, SharedFolder, SharedResource
from backend.security.password import hash_password
from backend.services.resource_service import ResourceService
from backend.utils.enums import (
    CourseStatus,
    EnrollmentStatus,
    Platforms,
    ResourcePermissionLevel as L,
    ResourceType,
    UserStatus,
)

PASSWORD = "FolderShare!2026x"


@pytest.fixture()
def env():
    tag = f"fsh{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="folder-share-tests")
    ids: dict[str, int] = {}
    pub: dict[str, object] = {}

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

        def user(name: str, role: str) -> User:
            return User(
                username=f"{tag}.{name}@t.test", slug=f"{tag}-{name}",
                email=f"{tag}.{name}@t.test", first_name=name.title(), last_name=tag,
                hashed_password=hash_password(PASSWORD), can_login=True,
                status=UserStatus.ACTIVE, roles=[roles[role]],
            )

        people = {
            "tutor": user("tutor", "TUTOR"),
            "colleague": user("colleague", "TUTOR"),
            "student": user("student", "STUDENT"),
            "outsider": user("outsider", "STUDENT"),
            "guardian": user("guardian", "GUARDIAN"),
        }
        courses = {}
        for key, title in (("a", "Data Analysis"), ("b", "Machine Learning")):
            c = Course(title=f"{tag} {title}", code=f"{tag}{key}", status=CourseStatus.PUBLISHED)
            c.batches, c.resources, c.tags, c.tutors = [], [], [], []
            courses[key] = c
        s.add_all([*people.values(), *courses.values()])
        await s.flush()

        now = datetime.now(UTC)
        batches = {}
        for key, teacher in (("a", "tutor"), ("b", "colleague")):
            b = Batch(batch_code=f"{tag}-{key}", course_id=courses[key].id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=30), is_active=True, capacity=10)
            b.sessions, b.enrollments, b.student_reviews = [], [], []
            s.add(b)
            batches[key] = b
        await s.flush()
        start = now + timedelta(days=1)
        for key, teacher in (("a", "tutor"), ("b", "colleague")):
            row = BatchSession(batch_id=batches[key].id, tutor_id=people[teacher].id,
                               session_start_time=start, session_end_time=start + timedelta(hours=1),
                               duration_minutes=60, platform=Platforms.Zoom)
            row.attendances = []
            s.add(row)
            s.add(Enrollments(batch_id=batches[key].id, student_id=people["student"].id,
                              enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
        s.add(StudentGuardian(guardian_id=people["guardian"].id, student_id=people["student"].id,
                              relationship_type="Parent", is_primary=True, created_at=now))
        await s.flush()

        def folder(name: str, parent: ResourceFolder | None, course_key: str | None) -> ResourceFolder:
            f = ResourceFolder(name=f"{tag} {name}", parent_folder_id=parent.id if parent else None,
                               course_id=courses[course_key].id if course_key else None,
                               created_by=people["tutor"].id, created_at=now)
            f.children, f.resources = [], []
            return f

        top = folder("Course Materials", None, "a")
        s.add(top)
        await s.flush()
        lectures = folder("Lecture Notes", top, "a")
        sibling = folder("Answers", top, "a")
        s.add_all([lectures, sibling])
        await s.flush()
        week1 = folder("Week 1", lectures, "a")
        empty = folder("Empty", lectures, "a")
        loose = folder("General", None, None)
        s.add_all([week1, empty, loose])
        await s.flush()

        def file(name: str, where: ResourceFolder | None, course_key: str | None, *,
                 restricted: bool = False) -> Resource:
            r = Resource(resource_type=ResourceType.lecture_sheet, name=f"{tag} {name}",
                         path=f"resources/{tag}/{name}", mime_type="application/pdf", size=10,
                         folder_id=where.id if where else None,
                         course_id=courses[course_key].id if course_key else None,
                         uploaded_by=people["tutor"].id, modified_by=people["tutor"].id,
                         is_deleted=False, is_restricted=restricted, created_at=now)
            r.versions, r.shared_resources = [], []
            return r

        files = {
            "lecture": file("Lecture 01.pdf", lectures, "a"),
            "nested": file("Exercise.pdf", week1, "a"),
            "secret": file("Marking guide.pdf", lectures, "a", restricted=True),
            "answers": file("Answer key.pdf", sibling, "a"),
            "at_top": file("Syllabus.pdf", top, "a"),
            # Same file name as `lecture`, a different file: duplicates are
            # identified by id, never by name.
            "same_name": file("Lecture 01.pdf", sibling, "a"),
            "ml": file("Intro to ML.pdf", None, "b"),
            "general": file("Timetable.pdf", loose, None),
        }
        for n in range(12):
            files[f"bulk{n}"] = file(f"Bulk {n:02}.pdf", lectures, "a")
        s.add_all(files.values())
        await s.flush()

        for key, person in people.items():
            ids[key], pub[key] = person.id, person.public_id
        for key, row in {**files, "top": top, "lectures": lectures, "sibling": sibling,
                         "week1": week1, "empty": empty, "loose": loose}.items():
            ids[key], pub[key] = row.id, row.public_id
        pub["course_a"], pub["course_b"] = courses["a"].public_id, courses["b"].public_id

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

    async def actor(s, who: str) -> User:  # noqa: ANN001
        if who == "admin":
            # The outsider is in nobody's class, so only an administrator --
            # whose share audience is everybody -- may hand them anything.
            # That is the point of the outsider: no course route can mask a
            # folder route that does not work.
            return (await s.execute(
                select(User).join(User.roles).where(Role.name == "SUPER_ADMIN")
            )).scalars().first()
        return (await s.execute(select(User).where(User.id == ids[who]))).scalar_one()

    ns = type("Env", (), dict(tag=tag, ids=ids, pub=pub, run=staticmethod(run),
                              call=staticmethod(call), actor=staticmethod(actor), db=db, loop=loop))
    try:
        yield ns
    finally:
        loop.run_until_complete(client.aclose())
        loop.run_until_complete(lifespan.__aexit__(None, None, None))

        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%", "code": f"{tag}%"}
                users = "(SELECT id FROM users WHERE username LIKE :u)"
                for stmt in (
                    "DELETE FROM shared_resources WHERE resource_id IN "
                    "(SELECT id FROM resources WHERE name LIKE :t)",
                    "DELETE FROM shared_folders WHERE folder_id IN "
                    "(SELECT id FROM resource_folders WHERE name LIKE :t)",
                    "DELETE FROM resources WHERE name LIKE :t",
                    # Children first: the cycle test can leave parents pointing
                    # at each other, so detach before deleting.
                    "UPDATE resource_folders SET parent_folder_id = NULL WHERE name LIKE :t",
                    "DELETE FROM resource_folders WHERE name LIKE :t",
                    f"DELETE FROM student_guardians WHERE guardian_id IN {users}",
                    "DELETE FROM enrollments WHERE batch_id IN "
                    "(SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM batch_sessions WHERE batch_id IN "
                    "(SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM batches WHERE batch_code LIKE :c",
                    "DELETE FROM courses WHERE code LIKE :code",
                    f"DELETE FROM notifications WHERE user_id IN {users}",
                    f"DELETE FROM tokens WHERE user_id IN {users}",
                    f"DELETE FROM user_roles WHERE user_id IN {users}",
                    "DELETE FROM users WHERE username LIKE :u",
                ):
                    await s.execute(text(stmt), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _share(env, files=(), folders=(), people=("student",), level=L.VIEW, who="tutor"):  # noqa: ANN001, ANN202
    async def go(s):  # noqa: ANN001, ANN202
        return await ResourceService(s).share_many(
            [env.pub[f] for f in files], [env.pub[p] for p in people],
            folder_public_ids=[env.pub[f] for f in folders],
            actor=await env.actor(s, who), level=level,
        )
    return env.run(go)


def _open(env, who: str, key: str):  # noqa: ANN001, ANN202
    async def go(s):  # noqa: ANN001, ANN202
        return await ResourceService(s).get(env.pub[key], actor=await env.actor(s, who))
    return env.run(go)


def _level(env, who: str, key: str):  # noqa: ANN001, ANN202
    async def go(s):  # noqa: ANN001, ANN202
        service = ResourceService(s)
        actor = await env.actor(s, who)
        return await service.effective_level(await service.get(env.pub[key], actor=actor), actor)
    return env.run(go)


# -- inheritance, and its boundary ------------------------------------------------


def test_a_shared_folder_opens_everything_beneath_it_at_the_shared_level(env) -> None:
    # The outsider is on no course and has no share: this is the control.
    with pytest.raises(NotFoundError):
        _open(env, "outsider", "lecture")

    _share(env, folders=["lectures"], people=["outsider"], who="admin")
    assert _level(env, "outsider", "lecture") == L.VIEW
    assert _level(env, "outsider", "nested") == L.VIEW  # two levels down


def test_the_share_does_not_leak_sideways_or_upwards(env) -> None:
    _share(env, folders=["lectures"], people=["outsider"], who="admin")
    for key in ("answers", "at_top", "same_name", "ml"):
        with pytest.raises(NotFoundError):
            _open(env, "outsider", key)
    # The folder above the share is not browsable through it, and its name is
    # not part of what was handed over.
    assert env.call("outsider", "GET", f"/shared-with-me/folders/{env.pub['top']}").status_code == 404
    inside = env.call("outsider", "GET", f"/shared-with-me/folders/{env.pub['week1']}")
    assert inside.status_code == 200, inside.text[:300]
    assert [p["name"] for p in inside.json()["path"]] == [
        f"{env.tag} Lecture Notes", f"{env.tag} Week 1",
    ]


def test_a_view_share_does_not_hand_over_the_file(env) -> None:
    _share(env, folders=["lectures"], people=["outsider"], who="admin", level=L.VIEW)
    assert env.call("outsider", "GET", f"/resources/{env.pub['lecture']}/download").status_code == 403


def test_staff_only_files_inside_a_shared_folder_stay_hidden(env) -> None:
    _share(env, folders=["lectures"], people=["outsider"], who="admin", level=L.DOWNLOAD)
    with pytest.raises(NotFoundError):
        _open(env, "outsider", "secret")
    listed = env.call("outsider", "GET", f"/shared-with-me/folders/{env.pub['lectures']}").json()
    names = {f["resource_name"] for f in listed["files"]}
    assert f"{env.tag} Lecture 01.pdf" in names
    assert f"{env.tag} Marking guide.pdf" not in names


def test_a_file_added_later_is_covered_and_one_moved_out_is_not(env) -> None:
    _share(env, folders=["lectures"], people=["outsider"], who="admin")

    async def move(s, key: str, folder_key: str) -> None:  # noqa: ANN001
        await s.execute(text("UPDATE resources SET folder_id = :f WHERE id = :r"),
                        {"f": env.ids[folder_key], "r": env.ids[key]})

    env.run(lambda s: move(s, "answers", "week1"))  # moved in: now covered
    assert _level(env, "outsider", "answers") == L.VIEW
    env.run(lambda s: move(s, "lecture", "sibling"))  # moved out: no longer
    with pytest.raises(NotFoundError):
        _open(env, "outsider", "lecture")


def test_an_empty_folder_shares_and_opens_cleanly(env) -> None:
    _share(env, folders=["empty"], people=["outsider"], who="admin")
    body = env.call("outsider", "GET", f"/shared-with-me/folders/{env.pub['empty']}").json()
    assert body["files"] == [] and body["folders"] == []


# -- revocation ---------------------------------------------------------------------


def test_revoking_a_folder_share_removes_only_what_it_granted(env) -> None:
    _share(env, folders=["lectures"], people=["outsider"], who="admin")
    _share(env, files=["nested"], people=["outsider"], who="admin")  # independently granted

    revoked = env.call("tutor", "DELETE", f"/folders/{env.pub['lectures']}/share/{env.pub['outsider']}")
    assert revoked.status_code == 204, revoked.text[:300]

    with pytest.raises(NotFoundError):
        _open(env, "outsider", "lecture")
    assert _level(env, "outsider", "nested") == L.VIEW  # the direct share survives


# -- duplicates, levels and retries ---------------------------------------------------


def test_sharing_again_changes_nothing_and_says_so_quietly(env) -> None:
    first = _share(env, files=["lecture", "nested"], folders=["week1"])
    assert (first.created, first.updated, first.unchanged) == (3, 0, 0)
    again = _share(env, files=["lecture", "nested"], folders=["week1"])
    assert (again.created, again.updated, again.unchanged) == (0, 0, 3)

    async def count(s):  # noqa: ANN001, ANN202
        files = await s.execute(text(
            "SELECT count(*) FROM shared_resources WHERE shared_with_user_id = :u"), {"u": env.ids["student"]})
        folders = await s.execute(text(
            "SELECT count(*) FROM shared_folders WHERE shared_with_user_id = :u"), {"u": env.ids["student"]})
        return files.scalar_one(), folders.scalar_one()
    assert env.run(count) == (2, 1)


def test_a_different_level_is_a_permission_change_not_a_duplicate(env) -> None:
    _share(env, files=["lecture"], people=["outsider"], who="admin", level=L.VIEW)
    changed = _share(env, files=["lecture"], people=["outsider"], who="admin", level=L.DOWNLOAD)
    assert (changed.created, changed.updated, changed.unchanged) == (0, 1, 0)
    assert _level(env, "outsider", "lecture") == L.DOWNLOAD


def test_two_files_with_the_same_name_are_two_files(env) -> None:
    outcome = _share(env, files=["lecture", "same_name"], people=["outsider"], who="admin")
    assert outcome.created == 2


def test_a_retried_request_over_http_is_harmless(env) -> None:
    body = {"resource_ids": [str(env.pub["lecture"])], "folder_ids": [str(env.pub["week1"])],
            "user_ids": [str(env.pub["student"])], "level": "VIEW"}
    first = env.call("tutor", "POST", "/resources/share", json=body)
    second = env.call("tutor", "POST", "/resources/share", json=body)
    assert first.status_code == second.status_code == 200
    assert first.json()["created"] == 2
    assert second.json() == {**first.json(), "created": 0, "unchanged": 2}


def test_simultaneous_identical_shares_write_one_row_each(env) -> None:
    """The race a check-then-insert loses: two sessions both see "not shared
    yet" and both insert. The unique constraint plus ON CONFLICT is the guard,
    so this must leave exactly one row per (file, person) and neither request
    may fail."""
    async def one():  # noqa: ANN202
        async with env.db.session_factory.begin() as s:
            return await ResourceService(s).share_many(
                [env.pub["lecture"], env.pub["nested"]], [env.pub["student"]],
                folder_public_ids=[env.pub["week1"]],
                actor=await env.actor(s, "tutor"), level=L.VIEW,
            )

    async def both():  # noqa: ANN202
        return await asyncio.gather(one(), one(), one())

    outcomes = env.loop.run_until_complete(both())
    assert sum(o.created for o in outcomes) == 3  # 2 files + 1 folder, once

    async def count(s):  # noqa: ANN001, ANN202
        rows = await s.execute(text(
            "SELECT count(*) FROM shared_resources WHERE shared_with_user_id = :u"), {"u": env.ids["student"]})
        return rows.scalar_one()
    assert env.run(count) == 2


def test_overlapping_shares_in_opposite_orders_do_not_deadlock(env) -> None:
    """Found by the load test, not by the test above: identical requests take
    their row locks in the same order and never deadlock. Two tutors sharing
    *overlapping* sets in *different* orders do -- each holds a row the other
    is waiting for, and Postgres kills one of them with a 500. Rows are now
    written in one global order, so locks are always taken in that order."""
    files = [f"bulk{n}" for n in range(12)]
    people = ["student", "outsider", "guardian", "colleague", "tutor"]
    rng = random.Random(7)

    async def one():  # noqa: ANN202
        # A different recipient order and level per request: overlapping rows,
        # reached in different orders, and changed rather than left alone, so
        # every request has to take row locks the others also want.
        order = rng.sample(people, k=len(people))
        level = rng.choice([L.VIEW, L.DOWNLOAD])
        async with env.db.session_factory.begin() as s:
            return await ResourceService(s).share_many(
                [env.pub[f] for f in files], [env.pub[p] for p in order],
                actor=await env.actor(s, "admin"), level=level,
            )

    async def race():  # noqa: ANN202
        rounds = []
        for _ in range(10):
            rounds.append(await asyncio.gather(*(one() for _ in range(6)), return_exceptions=True))
        return rounds

    rounds = env.loop.run_until_complete(race())
    failures = [r for batch in rounds for r in batch if isinstance(r, BaseException)]
    assert not failures, failures[:1]


# -- who may share what ------------------------------------------------------------


def test_a_tutor_cannot_share_a_colleagues_folder_or_hand_out_more_than_download(env) -> None:
    async def go(s):  # noqa: ANN001, ANN202
        service = ResourceService(s)
        colleague = await env.actor(s, "colleague")
        with pytest.raises(NotFoundError):
            await service.share_many([], [env.pub["student"]], folder_public_ids=[env.pub["lectures"]],
                                     actor=colleague)
        tutor = await env.actor(s, "tutor")
        with pytest.raises(ValidationError):
            await service.share_many([env.pub["lecture"]], [env.pub["student"]], actor=tutor,
                                     level=L.MANAGE)
    env.run(go)


def test_one_unreachable_folder_refuses_the_whole_request(env) -> None:
    async def go(s):  # noqa: ANN001, ANN202
        with pytest.raises(NotFoundError):
            await ResourceService(s).share_many(
                [env.pub["lecture"]], [env.pub["student"]],
                folder_public_ids=[env.pub["loose"]],  # no course: not the tutor's
                actor=await env.actor(s, "tutor"),
            )
    env.run(go)

    async def count(s):  # noqa: ANN001, ANN202
        rows = await s.execute(text(
            "SELECT count(*) FROM shared_resources WHERE shared_with_user_id = :u"), {"u": env.ids["student"]})
        return rows.scalar_one()
    assert env.run(count) == 0


# -- the people the audience includes and the permissions forgot -------------------


def test_a_guardian_can_open_what_was_shared_and_nothing_else(env) -> None:
    """Guardians are in the share audience and hold no `resource.*` permission,
    so before this every file shared with one was refused on the way in."""
    _share(env, files=["lecture"], people=["guardian"], level=L.DOWNLOAD)

    mine = env.call("guardian", "GET", "/shared-with-me")
    assert mine.status_code == 200, mine.text[:300]
    assert [r["resource_name"] for r in mine.json()] == [f"{env.tag} Lecture 01.pdf"]
    assert env.call("guardian", "GET", f"/resources/{env.pub['lecture']}").status_code == 200
    # Their ward's course is visible to them; its files are not, unless shared.
    assert env.call("guardian", "GET", f"/resources/{env.pub['at_top']}").status_code == 404
    # And the library itself stays closed to them.
    assert env.call("guardian", "GET", "/resources").status_code == 403


# -- grouping by course ---------------------------------------------------------------


def test_the_library_groups_by_the_files_own_course(env) -> None:
    _share(env, folders=["lectures"], people=["outsider"], who="admin")

    async def by_admin(s):  # noqa: ANN001, ANN202
        admin = (await s.execute(
            select(User).join(User.roles).where(Role.name == "SUPER_ADMIN")
        )).scalars().first()
        await ResourceService(s).share_many(
            [env.pub["ml"], env.pub["general"]], [env.pub["outsider"]], actor=admin
        )
    env.run(by_admin)

    body = env.call("outsider", "GET", "/shared-with-me/library").json()
    groups = {g["course_title"]: g for g in body["groups"]}
    assert set(groups) == {f"{env.tag} Data Analysis", f"{env.tag} Machine Learning", None}
    assert [f["folder_name"] for f in groups[f"{env.tag} Data Analysis"]["folders"]] == [
        f"{env.tag} Lecture Notes"
    ]
    assert [f["resource_name"] for f in groups[f"{env.tag} Machine Learning"]["files"]] == [
        f"{env.tag} Intro to ML.pdf"
    ]
    assert [f["resource_name"] for f in groups[None]["files"]] == [f"{env.tag} Timetable.pdf"]
    assert body["groups"][-1]["course_id"] is None  # "General" is last
    assert body["total_files"] == 2 and body["total_folders"] == 1


# -- cost --------------------------------------------------------------------------------


def test_twelve_files_cost_a_bounded_number_of_queries(env) -> None:
    """The regression guard for the timeout. Measured before the fix at 3,256
    queries for this request against a real course; the bound is generous on
    purpose -- it fails on per-file work, not on one extra lookup."""
    counted = {"n": 0}

    def count(*_a, **_k):  # noqa: ANN002, ANN003
        counted["n"] += 1

    async def go(s):  # noqa: ANN001, ANN202
        tutor = await env.actor(s, "tutor")
        sync_engine = s.bind.sync_engine if hasattr(s.bind, "sync_engine") else s.get_bind()
        event.listen(sync_engine, "before_cursor_execute", count)
        try:
            outcome = await ResourceService(s).share_many(
                [env.pub[f"bulk{n}"] for n in range(12)], [env.pub["student"]], actor=tutor,
            )
        finally:
            event.remove(sync_engine, "before_cursor_execute", count)
        return outcome
    outcome = env.run(go)
    assert outcome.created == 12
    assert counted["n"] < 40, counted["n"]


def test_a_cycle_in_the_tree_cannot_hang_a_lookup(env) -> None:
    """`move_folder` refuses a cycle, but a migration or a direct edit would
    not; the depth cap is what keeps a lookup from looping."""
    _share(env, folders=["lectures"], people=["outsider"], who="admin")

    async def make_cycle(s):  # noqa: ANN001
        await s.execute(text("UPDATE resource_folders SET parent_folder_id = :b WHERE id = :a"),
                        {"a": env.ids["top"], "b": env.ids["week1"]})
    env.run(make_cycle)
    # Week 1 -> Lecture Notes -> Course Materials -> Week 1 -> ... The walk has
    # to terminate *and* still find the share part-way round the loop.
    assert _level(env, "outsider", "nested") == L.VIEW

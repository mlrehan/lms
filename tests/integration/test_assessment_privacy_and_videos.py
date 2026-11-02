"""Tutor isolation, publishing your own, withdrawal, and the video library.

Driven over HTTP as real seeded roles, because each rule is a promise about
what a route answers -- a service-level test would prove the rule exists, not
that every door asks it.

The fixture is built so each rule can fail visibly:

* **Two tutors teach the same batch.** With only one tutor, "sees their own"
  and "sees every assessment in the course" are the same answer, and the
  isolation could be deleted without a test noticing.
* **An administrator-written assessment sits in that batch too**, so the
  tutors must still see (and mark) work that is not another tutor's.
* **An outsider student is enrolled elsewhere**, so the video audience rule
  has somebody to refuse.
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
from backend.db.manager import DatabaseManager
from backend.main import app
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.security.password import hash_password
from backend.utils.enums import CourseStatus, EnrollmentStatus, Platforms, UserStatus

PASSWORD = "PrivacyVideos!2026"
YOUTUBE = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture()
def env():
    tag = f"pv{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="privacy-video-tests")
    ids: dict[str, object] = {}
    now = datetime.now(timezone.utc)

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

        def person(key: str, role: str) -> User:
            email = f"{tag}.{key}@t.test"
            return User(
                username=email, slug=f"{tag}-{key}", email=email,
                first_name=key.title(), last_name=tag,
                hashed_password=hash_password(PASSWORD), can_login=True,
                status=UserStatus.ACTIVE, roles=[roles[role]],
            )

        people = {k: person(k, r) for k, r in (
            ("admin", "SUPER_ADMIN"), ("tutora", "TUTOR"), ("tutorb", "TUTOR"),
            ("student", "STUDENT"), ("outsider", "STUDENT"),
        )}
        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        other = Course(title=f"{tag} Other", code=f"{tag}O", status=CourseStatus.PUBLISHED)
        other.batches, other.resources, other.tags, other.tutors = [], [], [], []
        s.add_all([*people.values(), course, other])
        await s.flush()

        def batch(code: str, course_id: int) -> Batch:
            b = Batch(batch_code=f"{tag}-{code}", course_id=course_id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=60), is_active=True, capacity=10)
            b.sessions, b.enrollments, b.student_reviews = [], [], []
            return b

        shared, elsewhere = batch("X", course.id), batch("Y", other.id)
        s.add_all([shared, elsewhere])
        await s.flush()
        for offset, key in ((1, "tutora"), (2, "tutorb")):
            row = BatchSession(
                batch_id=shared.id, tutor_id=people[key].id,
                session_start_time=now + timedelta(days=offset),
                session_end_time=now + timedelta(days=offset, hours=1),
                duration_minutes=60, platform=Platforms.Zoom,
            )
            row.attendances = []
            s.add(row)
        s.add(Enrollments(batch_id=shared.id, student_id=people["student"].id,
                          enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
        s.add(Enrollments(batch_id=elsewhere.id, student_id=people["outsider"].id,
                          enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
        ids.update(
            course=course.public_id, batch=shared.public_id, other_batch=elsewhere.public_id,
            **{f"{k}_id": p.public_id for k, p in people.items()},
            **{f"{k}_pk": p.id for k, p in people.items()},
        )

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

    def sql(statement: str, **params):  # noqa: ANN202
        async def go(s):  # noqa: ANN001, ANN202
            return (await s.execute(text(statement), params)).all()
        return run(go)

    ns = type("Env", (), dict(tag=tag, ids=ids, call=staticmethod(call), sql=staticmethod(sql),
                              run=staticmethod(run)))
    try:
        yield ns
    finally:
        loop.run_until_complete(client.aclose())
        loop.run_until_complete(lifespan.__aexit__(None, None, None))

        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                users = "(SELECT id FROM users WHERE username LIKE :u)"
                courses = "(SELECT id FROM courses WHERE title LIKE :t)"
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                for stmt in (
                    f"DELETE FROM notifications WHERE user_id IN {users}",
                    f"DELETE FROM videos WHERE owner_id IN {users}",
                    f"DELETE FROM gradebook_entries WHERE student_id IN {users}",
                    f"DELETE FROM assignment_submissions WHERE student_id IN {users}",
                    f"DELETE FROM assignments WHERE course_id IN {courses}",
                    f"DELETE FROM question_options WHERE question_id IN (SELECT id FROM questions WHERE quiz_id IN (SELECT id FROM quizzes WHERE course_id IN {courses}))",
                    f"DELETE FROM quiz_attempts WHERE quiz_id IN (SELECT id FROM quizzes WHERE course_id IN {courses})",
                    f"DELETE FROM questions WHERE quiz_id IN (SELECT id FROM quizzes WHERE course_id IN {courses})",
                    f"DELETE FROM quizzes WHERE course_id IN {courses}",
                    f"DELETE FROM exams WHERE course_id IN {courses}",
                    "DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM batches WHERE batch_code LIKE :c",
                    "DELETE FROM courses WHERE title LIKE :t",
                    f"DELETE FROM user_roles WHERE user_id IN {users}",
                    "DELETE FROM users WHERE username LIKE :u",
                ):
                    await s.execute(text(stmt), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _assignment(env, who: str, title: str, **extra) -> httpx.Response:
    return env.call(who, "POST", f"/courses/{env.ids['course']}/assignments", json={
        "title": f"{env.tag} {title}", "description": "Work.", "max_score": 20,
        "due_date": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "submission_type": "TEXT", "scope": "BATCH", "batch_id": str(env.ids["batch"]), **extra,
    })


def _ok(response: httpx.Response, code: int = 200) -> dict:
    assert response.status_code == code, response.text[:300]
    return response.json() if response.content else {}


def _listed(env, who: str, path: str) -> set[str]:
    return {row["title"] for row in _ok(env.call(who, "GET", path))["items"]}


# -- 1, 2: tutor isolation ------------------------------------------------------


def test_a_tutor_cannot_see_another_tutors_assessments_but_the_super_admin_sees_all(env) -> None:
    a = _ok(_assignment(env, "tutora", "A essay"), 201)
    b = _ok(_assignment(env, "tutorb", "B essay"), 201)
    quiz = _ok(env.call("tutora", "POST", f"/courses/{env.ids['course']}/quizzes", json={
        "title": f"{env.tag} A quiz", "passing_score": 50,
    }), 201)

    # Direct links: a colleague's work is a 404, exactly like a missing row.
    assert env.call("tutorb", "GET", f"/assignments/{a['public_id']}").status_code == 404
    assert env.call("tutorb", "GET", f"/quizzes/{quiz['public_id']}").status_code == 404
    assert env.call("tutora", "GET", f"/assignments/{b['public_id']}").status_code == 404
    # Listings and search.
    assert _listed(env, "tutora", "/assignments") >= {f"{env.tag} A essay"}
    assert f"{env.tag} B essay" not in _listed(env, "tutora", "/assignments")
    assert f"{env.tag} A quiz" not in _listed(env, "tutorb", "/quizzes")
    found = env.call("tutorb", "GET", "/search", params={"q": f"{env.tag} A"}).json()
    assert f"{env.tag} A essay" not in str(found)
    # The Super Admin sees both.
    assert {f"{env.tag} A essay", f"{env.tag} B essay"} <= _listed(env, "admin", "/assignments")
    assert env.call("admin", "GET", f"/assignments/{a['public_id']}").status_code == 200


def test_an_administrators_assessment_stays_visible_to_the_tutors_who_mark_it(env) -> None:
    """Isolation is between tutors. Work the office sets for a batch is the
    batch tutors' to see and mark -- but not theirs to edit or delete."""
    row = _ok(_assignment(env, "admin", "Office test", state="PUBLISHED"), 201)
    assert env.call("tutora", "GET", f"/assignments/{row['public_id']}").status_code == 200
    assert env.call("tutorb", "GET", f"/assignments/{row['public_id']}").status_code == 200
    assert env.call("tutora", "DELETE", f"/assignments/{row['public_id']}").status_code == 403
    assert env.call("tutora", "PATCH", f"/assignments/{row['public_id']}",
                    json={"title": "renamed"}).status_code == 403


def test_a_colleagues_submissions_and_grade_book_entries_are_withheld(env) -> None:
    a = _ok(_assignment(env, "tutora", "Marked"), 201)
    _ok(env.call("admin", "PATCH", f"/assignments/{a['public_id']}", json={"state": "PUBLISHED"}))
    sub = _ok(env.call("student", "PUT", f"/assignments/{a['public_id']}/submission",
                       json={"content": "answer"}))
    _ok(env.call("tutora", "PUT", f"/submissions/{sub['public_id']}/grade", json={"grade": 15}))

    mine = env.call("tutora", "GET", "/submissions", params={"limit": 200}).json()["items"]
    theirs = env.call("tutorb", "GET", "/submissions", params={"limit": 200}).json()["items"]
    assert sub["public_id"] in {s["public_id"] for s in mine}
    assert sub["public_id"] not in {s["public_id"] for s in theirs}
    assert env.call("tutorb", "GET", f"/submissions/{sub['public_id']}").status_code == 404

    def assignment_entries(who: str) -> int:
        rows = env.call(who, "GET", "/gradebook",
                        params={"batch_id": str(env.ids["batch"]), "limit": 200}).json()["items"]
        return sum(1 for r in rows if r["component_type"] == "ASSIGNMENT")

    assert assignment_entries("tutora") == 1
    assert assignment_entries("tutorb") == 0
    assert assignment_entries("admin") == 1


# -- 3: publishing ---------------------------------------------------------------
#
# Tutors publish and unpublish their *own* assessments directly. The console
# could not publish an assignment at all -- its page had no control for it --
# while the assistant's `publish_assessment` could, through the same edit route.
# Both now arrive at the same ownership check in the service.


def _quiz_with_question(env, who: str, title: str) -> dict:
    quiz = _ok(env.call(who, "POST", f"/courses/{env.ids['course']}/quizzes",
                        json={"title": f"{env.tag} {title}", "passing_score": 50}), 201)
    _ok(env.call(who, "POST", f"/quizzes/{quiz['public_id']}/questions", json={
        "question_text": "2 + 2?", "question_type": "MCQ_SINGLE", "points": 1,
        "options": [{"option_text": "4", "is_correct": True, "order": 0},
                    {"option_text": "5", "is_correct": False, "order": 1}],
    }), 201)
    return quiz


def _exam(env, who: str) -> dict:
    return _ok(env.call(who, "POST", "/exams", json={
        "title": f"{env.tag} Exam", "exam_type": "FINAL", "course_id": str(env.ids["course"]),
        "batch_id": str(env.ids["batch"]), "scope": "BATCH",
        "scheduled_at": (datetime.now(timezone.utc) + timedelta(days=9)).isoformat(),
        "total_marks": 100, "passing_marks": 40,
    }), 201)


def test_a_tutor_publishes_and_unpublishes_their_own_directly(env) -> None:
    draft = _ok(_assignment(env, "tutora", "Mine", state="DRAFT"), 201)
    assert draft["can_manage"] is True
    assert f"{env.tag} Mine" not in _listed(env, "student", "/assignments")

    published = _ok(env.call("tutora", "PATCH", f"/assignments/{draft['public_id']}",
                             json={"state": "PUBLISHED"}))
    assert published["state"] == "PUBLISHED"
    assert f"{env.tag} Mine" in _listed(env, "student", "/assignments")
    _ok(env.call("tutora", "PATCH", f"/assignments/{draft['public_id']}", json={"state": "DRAFT"}))
    assert env.call("student", "GET", f"/assignments/{draft['public_id']}").status_code == 404

    quiz = _quiz_with_question(env, "tutora", "Mine Q")
    assert _ok(env.call("tutora", "PUT", f"/quizzes/{quiz['public_id']}/publish",
                        json={"is_published": True}))["is_published"] is True
    assert _ok(env.call("tutora", "PUT", f"/quizzes/{quiz['public_id']}/publish",
                        json={"is_published": False}))["is_published"] is False

    exam = _exam(env, "tutora")
    assert _ok(env.call("tutora", "PUT", f"/exams/{exam['public_id']}/publish",
                        json={"is_published": True}))["is_published"] is True


def test_a_tutor_cannot_publish_or_unpublish_another_tutors(env) -> None:
    a = _ok(_assignment(env, "tutora", "As", state="DRAFT"), 201)
    quiz = _quiz_with_question(env, "tutora", "As Q")
    exam = _exam(env, "tutora")
    assert env.call("tutorb", "PATCH", f"/assignments/{a['public_id']}",
                    json={"state": "PUBLISHED"}).status_code == 404
    assert env.call("tutorb", "PUT", f"/quizzes/{quiz['public_id']}/publish",
                    json={"is_published": True}).status_code == 404
    assert env.call("tutorb", "PUT", f"/exams/{exam['public_id']}/publish",
                    json={"is_published": True}).status_code == 404
    # The Super Admin controls everybody's.
    assert _ok(env.call("admin", "PATCH", f"/assignments/{a['public_id']}",
                        json={"state": "PUBLISHED"}))["state"] == "PUBLISHED"
    assert _ok(env.call("admin", "PUT", f"/quizzes/{quiz['public_id']}/publish",
                        json={"is_published": True}))["is_published"] is True


def test_the_assistant_publishes_under_the_same_rule(env) -> None:
    """`publish_assessment` goes through the service, so a colleague is refused
    there exactly as on the console, and the author is allowed."""
    from backend.ai.tools.academic_tools import handle_publish_assessment
    from backend.ai.tools.registry import BOUND_PREFIX, ToolExecutionContext
    from backend.core.errors import NotFoundError

    a = _ok(_assignment(env, "tutora", "Via AI", state="DRAFT"), 201)
    args = {"assessment_type": "assignment", "assessment_id": a["public_id"],
            f"{BOUND_PREFIX}assessment_public_id": a["public_id"]}

    async def as_user(s, key):  # noqa: ANN001, ANN202
        user = (await s.execute(select(User).where(User.username == f"{env.tag}.{key}@t.test"))).scalar_one()
        return await handle_publish_assessment(args, ToolExecutionContext(user=user, session=s))

    with pytest.raises(NotFoundError):
        env.run(lambda s: as_user(s, "tutorb"))
    assert env.run(lambda s: as_user(s, "tutora"))["is_published"] is True


# -- 4, 5, 6: deletion -----------------------------------------------------------


def test_a_tutor_deletes_their_own_and_the_work_is_kept(env) -> None:
    a = _ok(_assignment(env, "tutora", "Withdrawn"), 201)
    _ok(env.call("admin", "PATCH", f"/assignments/{a['public_id']}", json={"state": "PUBLISHED"}))
    _ok(env.call("student", "PUT", f"/assignments/{a['public_id']}/submission", json={"content": "x"}))

    assert env.call("tutora", "DELETE", f"/assignments/{a['public_id']}").status_code == 204
    # Gone from every door, for everybody, including the Super Admin.
    for who in ("tutora", "admin", "student"):
        assert env.call(who, "GET", f"/assignments/{a['public_id']}").status_code == 404
    assert f"{env.tag} Withdrawn" not in _listed(env, "admin", "/assignments")
    assert env.call("student", "PUT", f"/assignments/{a['public_id']}/submission",
                    json={"content": "again"}).status_code == 404
    # Kept in the database: the row, and the student's submission.
    kept = env.sql("SELECT a.deleted_at IS NOT NULL, count(s.id) FROM assignments a "
                   "LEFT JOIN assignment_submissions s ON s.assignment_id = a.id "
                   "WHERE a.public_id = :p GROUP BY a.id", p=a["public_id"])
    assert kept == [(True, 1)]


def test_a_tutor_cannot_delete_another_tutors_and_the_super_admin_can(env) -> None:
    b = _ok(_assignment(env, "tutorb", "Bs"), 201)
    quiz = _ok(env.call("tutorb", "POST", f"/courses/{env.ids['course']}/quizzes",
                        json={"title": f"{env.tag} Bq", "passing_score": 50}), 201)
    assert env.call("tutora", "DELETE", f"/assignments/{b['public_id']}").status_code == 404
    assert env.call("tutora", "DELETE", f"/quizzes/{quiz['public_id']}").status_code == 404
    assert env.call("admin", "DELETE", f"/assignments/{b['public_id']}").status_code == 204
    assert env.call("admin", "DELETE", f"/quizzes/{quiz['public_id']}").status_code == 204
    assert env.call("tutorb", "GET", f"/quizzes/{quiz['public_id']}").status_code == 404


# -- 7, 8, 9: videos -------------------------------------------------------------


def _video(env, who: str, **extra) -> dict:
    return _ok(env.call(who, "POST", "/videos", json={
        "title": f"{env.tag} Lecture", "url": YOUTUBE, "batch_id": str(env.ids["batch"]), **extra,
    }), 201)


def test_a_tutor_shares_only_within_their_classes(env) -> None:
    video = _video(env, "tutora")
    vid = video["public_id"]
    assert video["provider"] == "youtube" and video["source_url"]
    # Their own student and their own batch: allowed.
    assert _ok(env.call("tutora", "POST", f"/videos/{vid}/shares",
                        json={"user_ids": [str(env.ids["student_id"])]}))["people_added"] == 1
    assert _ok(env.call("tutora", "POST", f"/videos/{vid}/shares",
                        json={"batch_ids": [str(env.ids["batch"])]}))["batches_added"] == 1
    # A student they do not teach, or a batch they do not teach: refused, whole request.
    assert env.call("tutora", "POST", f"/videos/{vid}/shares",
                    json={"user_ids": [str(env.ids["outsider_id"])]}).status_code == 403
    assert env.call("tutora", "POST", f"/videos/{vid}/shares",
                    json={"batch_ids": [str(env.ids["other_batch"])]}).status_code == 403
    assert env.call("tutora", "POST", f"/videos/{vid}/shares", json={
        "user_ids": [str(env.ids["student_id"]), str(env.ids["outsider_id"])],
    }).status_code == 403
    # The outsider still cannot reach it.
    assert env.call("outsider", "GET", f"/videos/{vid}").status_code == 404


def test_the_super_admin_shares_with_anybody_and_access_follows_the_share(env) -> None:
    vid = _video(env, "tutora")["public_id"]
    for path in (f"/videos/{vid}", f"/videos/{vid}/player", f"/videos/{vid}/open"):
        assert env.call("outsider", "GET", path).status_code == 404, path
    assert vid not in {v["public_id"] for v in env.call("outsider", "GET", "/videos").json()["items"]}

    _ok(env.call("admin", "POST", f"/videos/{vid}/shares", json={"user_ids": [str(env.ids["outsider_id"])]}))
    seen = _ok(env.call("outsider", "GET", f"/videos/{vid}"))
    # A viewer gets our paths, never the provider's address.
    assert seen["source_url"] is None and "youtube" not in str(seen.get("player_url"))
    player = env.call("outsider", "GET", f"/videos/{vid}/player", follow_redirects=False)
    assert player.status_code == 307
    assert player.headers["location"].startswith("https://www.youtube-nocookie.com/embed/")
    assert player.headers["cache-control"] == "private, no-store"
    views = env.sql("SELECT count(*) FROM audit_logs WHERE action = 'VIDEO_VIEW' AND actor_user_id = :u",
                    u=env.ids["outsider_pk"])[0][0]
    assert views == 1


def test_unshared_and_withdrawn_videos_close_their_links(env) -> None:
    vid = _video(env, "tutora")["public_id"]
    _ok(env.call("tutora", "POST", f"/videos/{vid}/shares", json={"user_ids": [str(env.ids["student_id"])]}))
    assert env.call("student", "GET", f"/videos/{vid}/player", follow_redirects=False).status_code == 307
    # A colleague who was not shared it, and cannot manage it.
    assert env.call("tutorb", "GET", f"/videos/{vid}").status_code == 404
    assert env.call("tutorb", "DELETE", f"/videos/{vid}").status_code == 404
    assert env.call("student", "DELETE", f"/videos/{vid}").status_code == 403

    shares = _ok(env.call("tutora", "GET", f"/videos/{vid}"))["shares"]
    assert env.call("tutora", "DELETE", f"/videos/{vid}/shares/{shares[0]['id']}").status_code == 204
    assert env.call("student", "GET", f"/videos/{vid}/player").status_code == 404

    assert env.call("tutora", "DELETE", f"/videos/{vid}").status_code == 204
    assert env.call("admin", "GET", f"/videos/{vid}").status_code == 404


def test_a_provider_that_cannot_be_framed_is_offered_as_a_link(env) -> None:
    row = _video(env, "tutora", url="https://streamyard.com/watch/abcdef")
    assert row["plays_in_lms"] is False and row["player_url"] is None
    assert row["notes"]["plays_in_lms"] is False and "YouTube" in row["notes"]["download"]
    assert env.call("tutora", "GET", f"/videos/{row['public_id']}/player").status_code == 422
    assert env.call("tutora", "GET", f"/videos/{row['public_id']}/open",
                    follow_redirects=False).status_code == 307


# -- the assistant follows the same rules -------------------------------------------


def _tool(env, key: str, handler, args: dict):  # noqa: ANN001, ANN202
    from backend.ai.tools.registry import ToolExecutionContext

    async def go(s):  # noqa: ANN001, ANN202
        user = (await s.execute(select(User).where(User.username == f"{env.tag}.{key}@t.test"))).scalar_one()
        return await handler(args, ToolExecutionContext(user=user, session=s))
    return env.run(go)


def _confirmed(env, key: str, preview, handler, args: dict):  # noqa: ANN001, ANN202
    """Preview, then run with the bound parameters -- what the confirm endpoint does."""
    from backend.ai.tools.registry import BOUND_PREFIX

    staged = _tool(env, key, preview, args)
    bound = {f"{BOUND_PREFIX}{k}": v for k, v in staged.bound_parameters.items()}
    return staged, _tool(env, key, handler, {**args, **bound})


def test_the_assistant_lists_only_your_own_and_never_a_colleagues(env) -> None:
    from backend.ai.tools.library_tools import handle_list_my_assessments

    _ok(_assignment(env, "tutora", "Listed A", state="DRAFT"), 201)
    _ok(_assignment(env, "tutorb", "Listed B", state="DRAFT"), 201)
    mine = _tool(env, "tutora", handle_list_my_assessments, {"mine_only": False})
    titles = {a["title"] for a in mine["assessments"]}
    assert f"{env.tag} Listed A" in titles and f"{env.tag} Listed B" not in titles
    drafts = _tool(env, "tutora", handle_list_my_assessments, {"status": "DRAFT"})
    assert all(not a["published"] and a["can_manage"] for a in drafts["assessments"])


def test_the_assistant_unpublishes_and_deletes_your_own_only(env) -> None:
    from backend.ai.tools.academic_tools import handle_publish_assessment, preview_publish_assessment
    from backend.ai.tools.library_tools import handle_delete_assessment, preview_delete_assessment
    from backend.core.errors import NotFoundError

    a = _ok(_assignment(env, "tutora", "Tool target"), 201)
    args = {"assessment_type": "assignment", "assessment_id": a["public_id"]}
    staged, done = _confirmed(env, "tutora", preview_publish_assessment, handle_publish_assessment,
                              {**args, "publish": False})
    assert "Unpublish" in staged.summary and done["is_published"] is False

    with pytest.raises(NotFoundError):
        _tool(env, "tutorb", preview_delete_assessment, args)
    staged, done = _confirmed(env, "tutora", preview_delete_assessment, handle_delete_assessment, args)
    assert "kept" in staged.summary and done["success"] is True
    assert env.call("admin", "GET", f"/assignments/{a['public_id']}").status_code == 404


def test_the_assistant_shares_videos_only_within_the_audience(env) -> None:
    from backend.ai.tools.library_tools import handle_find_videos, handle_share_video, preview_share_video
    from backend.core.errors import ValidationError

    vid = _video(env, "tutora")
    outsider = {"video": vid["public_id"], "people": [f"Outsider {env.tag}"]}
    with pytest.raises(ValidationError):
        _tool(env, "tutora", preview_share_video, outsider)

    staged, done = _confirmed(env, "tutora", preview_share_video, handle_share_video,
                              {"video": vid["public_id"], "people": [f"Student {env.tag}"]})
    assert f"Student {env.tag}" in staged.summary and done["people_added"] == 1
    found = _tool(env, "student", handle_find_videos, {})
    assert vid["public_id"] in {v["id"] for v in found["videos"]}
    assert "youtube.com" not in str(found)
    assert _tool(env, "outsider", handle_find_videos, {})["count"] == 0


def test_only_the_super_admin_assigns_a_grading_scheme_through_the_assistant(env) -> None:
    from backend.ai.tools.library_tools import preview_assign_grading_scheme
    from backend.core.errors import AuthorizationError

    args = {"batch_code": f"{env.tag}-X", "scheme": "inherit"}
    with pytest.raises(AuthorizationError):
        _tool(env, "tutora", preview_assign_grading_scheme, args)
    staged = _tool(env, "admin", preview_assign_grading_scheme, args)
    assert "course's scheme" in staged.summary


def test_an_administrators_quiz_is_visible_to_the_tutor_but_not_theirs_to_publish(env) -> None:
    """The case the ownership check exists for: a colleague cannot even see the
    quiz, so only work the office set for the tutor's batch tests it."""
    quiz = _quiz_with_question(env, "admin", "Office quiz")
    assert env.call("tutora", "GET", f"/quizzes/{quiz['public_id']}").status_code == 200
    assert env.call("tutora", "PUT", f"/quizzes/{quiz['public_id']}/publish",
                    json={"is_published": True}).status_code == 403


def test_mine_only_leaves_out_what_the_office_set(env) -> None:
    from backend.ai.tools.library_tools import handle_list_my_assessments

    _ok(_assignment(env, "admin", "Office draft", state="DRAFT"), 201)
    _ok(_assignment(env, "tutora", "My draft", state="DRAFT"), 201)
    titles = {a["title"] for a in _tool(env, "tutora", handle_list_my_assessments, {})["assessments"]}
    assert f"{env.tag} My draft" in titles and f"{env.tag} Office draft" not in titles
    everything = _tool(env, "tutora", handle_list_my_assessments, {"mine_only": False})["assessments"]
    office = [a for a in everything if a["title"] == f"{env.tag} Office draft"]
    assert office and office[0]["can_manage"] is False


def test_a_withdrawn_assessment_is_gone_from_direct_queries_too(env) -> None:
    """The session hook, not the repositories: reports, the calendar feed and the
    assistant's own queries select assessments directly."""
    from backend.models.assignment import Assignment

    a = _ok(_assignment(env, "tutora", "Hooked"), 201)
    assert env.call("tutora", "DELETE", f"/assignments/{a['public_id']}").status_code == 204

    async def direct(s):  # noqa: ANN001, ANN202
        hidden = (await s.execute(select(Assignment).where(Assignment.public_id == a["public_id"]))).first()
        kept = (await s.execute(select(Assignment.id).where(Assignment.public_id == a["public_id"])
                                .execution_options(include_withdrawn=True))).first()
        return hidden, kept

    hidden, kept = env.run(direct)
    assert hidden is None and kept is not None

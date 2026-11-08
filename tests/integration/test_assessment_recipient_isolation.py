"""Who may see an assessment: the batch or students it was set for, nobody else.

Driven over HTTP as real seeded roles. The fixture is built so each rule can
fail visibly:

* **Two batches of one course.** Course-level visibility -- the rule this
  replaced -- gives both batches' students the same answer, so with only one
  batch the isolation could be deleted without any test noticing.
* **A classmate of the named student.** Work set for named students must
  reach the names and not the rest of their batch.
* **A guardian of each side**, because a guardian reads through their ward's
  enrolment and must inherit exactly that ward's view.
* **A second tutor teaching only batch B**, so naming a student the tutor
  does not teach has someone to refuse.
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
from backend.models.guardian import StudentGuardian
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.security.password import hash_password
from backend.utils.enums import CourseStatus, EnrollmentStatus, Platforms, UserStatus

PASSWORD = "RecipientIsolation!2026"


@pytest.fixture()
def env():
    tag = f"ri{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="recipient-isolation-tests")
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
            ("admin", "SUPER_ADMIN"), ("tutora", "TUTOR"), ("tutorb", "TUTOR"), ("tutorc", "TUTOR"),
            ("sa", "STUDENT"), ("sa2", "STUDENT"), ("sb", "STUDENT"),
            ("ga", "GUARDIAN"), ("gb", "GUARDIAN"),
        )}
        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([*people.values(), course])
        await s.flush()

        def batch(code: str) -> Batch:
            b = Batch(batch_code=f"{tag}-{code}", course_id=course.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=60), is_active=True, capacity=10)
            b.sessions, b.enrollments, b.student_reviews = [], [], []
            return b

        ba, bb = batch("A"), batch("B")
        s.add_all([ba, bb])
        await s.flush()
        # tutorc co-teaches batch A: the colleague who must *not* hear about
        # tutora's own work, and who must hear about the office's.
        for offset, b, key in ((1, ba, "tutora"), (2, bb, "tutorb"), (3, ba, "tutorc")):
            row = BatchSession(
                batch_id=b.id, tutor_id=people[key].id,
                session_start_time=now + timedelta(days=offset),
                session_end_time=now + timedelta(days=offset, hours=1),
                duration_minutes=60, platform=Platforms.Zoom,
            )
            row.attendances = []
            s.add(row)
        for b, key in ((ba, "sa"), (ba, "sa2"), (bb, "sb")):
            s.add(Enrollments(batch_id=b.id, student_id=people[key].id,
                              enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
        s.add(StudentGuardian(guardian_id=people["ga"].id, student_id=people["sa"].id))
        s.add(StudentGuardian(guardian_id=people["gb"].id, student_id=people["sb"].id))
        ids.update(
            course=course.public_id, batch_a=ba.public_id, batch_b=bb.public_id,
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
            result = await s.execute(text(statement), params)
            return result.all() if result.returns_rows else []
        return run(go)

    def as_tool(who: str, fn):  # noqa: ANN001, ANN202
        """Run an AI tool step as `who`, committing what it wrote."""
        from backend.ai.tools.registry import ToolExecutionContext

        async def go():  # noqa: ANN202
            async with db.session_factory() as s:
                user = await s.get(User, ids[f"{who}_pk"])
                result = await fn(ToolExecutionContext(user=user, session=s))
                await s.commit()
                return result
        return loop.run_until_complete(go())

    ns = type("Env", (), dict(tag=tag, ids=ids, call=staticmethod(call), sql=staticmethod(sql),
                              as_tool=staticmethod(as_tool)))
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
                    f"DELETE FROM gradebook_entries WHERE student_id IN {users}",
                    f"DELETE FROM assignment_submissions WHERE student_id IN {users}",
                    f"DELETE FROM assessment_revisions WHERE assignment_id IN (SELECT id FROM assignments WHERE course_id IN {courses}) OR quiz_id IN (SELECT id FROM quizzes WHERE course_id IN {courses}) OR exam_id IN (SELECT id FROM exams WHERE course_id IN {courses})",
                    f"DELETE FROM assessment_recipients WHERE student_id IN {users}",
                    f"DELETE FROM assignments WHERE course_id IN {courses}",
                    f"DELETE FROM question_options WHERE question_id IN (SELECT id FROM questions WHERE quiz_id IN (SELECT id FROM quizzes WHERE course_id IN {courses}))",
                    f"DELETE FROM quiz_attempts WHERE quiz_id IN (SELECT id FROM quizzes WHERE course_id IN {courses})",
                    f"DELETE FROM questions WHERE quiz_id IN (SELECT id FROM quizzes WHERE course_id IN {courses})",
                    f"DELETE FROM quizzes WHERE course_id IN {courses}",
                    f"DELETE FROM exams WHERE course_id IN {courses}",
                    f"DELETE FROM student_guardians WHERE guardian_id IN {users}",
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


def _ok(response: httpx.Response, code: int = 200) -> dict:
    assert response.status_code == code, response.text[:400]
    return response.json() if response.content else {}


def _due() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()


def _assignment(env, who: str, title: str, **target) -> httpx.Response:
    return env.call(who, "POST", f"/courses/{env.ids['course']}/assignments", json={
        "title": f"{env.tag} {title}", "description": "Work.", "max_score": 20,
        "due_date": _due(), "submission_type": "TEXT", "state": "PUBLISHED", **target,
    })


def _quiz(env, who: str, title: str, **target) -> dict:
    row = _ok(env.call(who, "POST", f"/courses/{env.ids['course']}/quizzes", json={
        "title": f"{env.tag} {title}", "passing_score": 50, **target,
    }), 201)
    # Publishing needs questions; visibility is what is under test, so the
    # flag is set directly rather than authoring a paper.
    env.sql("UPDATE quizzes SET is_published = true WHERE public_id = :p", p=row["public_id"])
    return row


def _exam(env, who: str, title: str, **target) -> dict:
    row = _ok(env.call(who, "POST", "/exams", json={
        "title": f"{env.tag} {title}", "exam_type": "MIDTERM", "scheduled_at": _due(),
        "total_marks": 100, "passing_marks": 40, "course_id": str(env.ids["course"]), **target,
    }), 201)
    _ok(env.call(who, "PUT", f"/exams/{row['public_id']}/publish", json={"is_published": True}))
    return row


def _titles(env, who: str, path: str) -> set[str]:
    return {r["title"] for r in _ok(env.call(who, "GET", path, params={"limit": 200}))["items"]}


BATCH_A = lambda env: {"scope": "BATCH", "batch_id": str(env.ids["batch_a"])}  # noqa: E731


# -- batch isolation ------------------------------------------------------------


def test_batch_work_reaches_its_batch_and_nobody_in_the_other_batch(env) -> None:
    a = _ok(_assignment(env, "tutora", "A essay", **BATCH_A(env)), 201)
    q = _quiz(env, "tutora", "A quiz", **BATCH_A(env))
    e = _exam(env, "tutora", "A exam", **BATCH_A(env))
    for kind, row, listing in (("assignments", a, "/assignments"), ("quizzes", q, "/quizzes"),
                               ("exams", e, "/exams")):
        path = f"/{kind}/{row['public_id']}"
        # The intended student and their guardian.
        assert env.call("sa", "GET", path).status_code == 200, kind
        assert env.call("ga", "GET", path).status_code == 200, kind
        assert row["title"] in _titles(env, "sa", listing), kind
        # Same course, other batch: not listed, and the direct link is a 404.
        assert env.call("sb", "GET", path).status_code == 404, kind
        assert env.call("gb", "GET", path).status_code == 404, kind
        assert row["title"] not in _titles(env, "sb", listing), kind
        assert row["title"] not in _titles(env, "gb", listing), kind


def test_a_student_outside_the_batch_cannot_submit_by_url(env) -> None:
    a = _ok(_assignment(env, "tutora", "A only", **BATCH_A(env)), 201)
    refused = env.call("sb", "PUT", f"/assignments/{a['public_id']}/submission",
                       json={"content": "not mine"})
    assert refused.status_code in (403, 404), refused.text[:200]
    assert env.sql("SELECT 1 FROM assignment_submissions s JOIN assignments a ON a.id = s.assignment_id "
                   "WHERE a.public_id = :p", p=a["public_id"]) == []


def test_course_wide_work_still_reaches_every_batch(env) -> None:
    a = _ok(_assignment(env, "admin", "Everyone", scope="COURSE"), 201)
    for who in ("sa", "sa2", "sb", "ga", "gb"):
        assert env.call(who, "GET", f"/assignments/{a['public_id']}").status_code == 200, who


# -- named students -------------------------------------------------------------


def test_work_set_for_named_students_reaches_only_those_students(env) -> None:
    named = {"scope": "STUDENTS", "student_ids": [str(env.ids["sa2_id"]), str(env.ids["sb_id"])]}
    a = _ok(_assignment(env, "admin", "Named", **named), 201)
    q = _quiz(env, "admin", "Named quiz", **named)
    e = _exam(env, "admin", "Named exam", **named)
    for kind, row in (("assignments", a), ("quizzes", q), ("exams", e)):
        path = f"/{kind}/{row['public_id']}"
        assert env.call("sa2", "GET", path).status_code == 200, kind
        assert env.call("sb", "GET", path).status_code == 200, kind
        assert env.call("gb", "GET", path).status_code == 200, kind
        # Their classmate, and the classmate's guardian, are not named.
        assert env.call("sa", "GET", path).status_code == 404, kind
        assert env.call("ga", "GET", path).status_code == 404, kind

    # Publication announced it to the names only.
    told = {r[0] for r in env.sql(
        "SELECT u.username FROM notifications n JOIN users u ON u.id = n.user_id "
        "WHERE n.type = 'assignment_published' AND n.meta->>'assignment_id' = :p", p=a["public_id"],
    )}
    assert told == {f"{env.tag}.sa2@t.test", f"{env.tag}.sb@t.test"}

    # And the named student may hand it in while the classmate may not.
    _ok(env.call("sa2", "PUT", f"/assignments/{a['public_id']}/submission", json={"content": "x"}))
    assert env.call("sa", "PUT", f"/assignments/{a['public_id']}/submission",
                    json={"content": "x"}).status_code in (403, 404)


def test_a_tutor_can_only_name_students_they_teach(env) -> None:
    refused = _assignment(env, "tutora", "Poach", scope="STUDENTS",
                          student_ids=[str(env.ids["sa_id"]), str(env.ids["sb_id"])])
    assert refused.status_code == 422, refused.text[:300]
    # The refusal names no student, so it cannot be used to locate one.
    assert "sb" not in refused.json().get("message", "").lower()
    assert env.sql("SELECT 1 FROM assignments WHERE title = :t", t=f"{env.tag} Poach") == []

    ok = _ok(_assignment(env, "tutora", "Mine", scope="STUDENTS",
                         student_ids=[str(env.ids["sa_id"])]), 201)
    assert env.call("sa", "GET", f"/assignments/{ok['public_id']}").status_code == 200


def test_named_scope_needs_names_and_other_scopes_refuse_them(env) -> None:
    assert _assignment(env, "admin", "Empty", scope="STUDENTS").status_code == 422
    assert _assignment(env, "admin", "Mixed", **BATCH_A(env),
                       student_ids=[str(env.ids["sa_id"])]).status_code == 422
    # A student not on the course at all.
    assert _assignment(env, "admin", "Stranger", scope="STUDENTS",
                       student_ids=[str(env.ids["ga_id"])]).status_code == 422


# -- revisions and change notices -----------------------------------------------


def _notices(env, type_: str, key: str, value: str) -> set[str]:
    return {r[0] for r in env.sql(
        "SELECT u.username FROM notifications n JOIN users u ON u.id = n.user_id "
        "WHERE n.type = :t AND n.meta->>:k = :v", t=type_, k=key, v=value,
    )}


def _who(env, *keys: str) -> set[str]:
    return {f"{env.tag}.{k}@t.test" for k in keys}


def test_editing_a_draft_records_nothing_and_tells_nobody(env) -> None:
    a = _ok(_assignment(env, "tutora", "Draft", **BATCH_A(env), state="DRAFT"), 201)
    _ok(env.call("tutora", "PATCH", f"/assignments/{a['public_id']}", json={"due_date": _due()}))
    assert env.sql("SELECT 1 FROM assessment_revisions r JOIN assignments a ON a.id = r.assignment_id "
                   "WHERE a.public_id = :p", p=a["public_id"]) == []
    assert _notices(env, "assessment_updated", "assignment_id", a["public_id"]) == set()
    assert _notices(env, "assignment_published", "assignment_id", a["public_id"]) == set()


def test_a_material_edit_after_publication_is_versioned_and_announced_to_the_batch(env) -> None:
    a = _ok(_assignment(env, "tutora", "Versioned", **BATCH_A(env)), 201)
    new_due = (datetime.now(timezone.utc) + timedelta(days=14)).replace(microsecond=0)
    _ok(env.call("tutora", "PATCH", f"/assignments/{a['public_id']}",
                 json={"due_date": new_due.isoformat(), "max_score": 25}))
    rows = env.sql(
        "SELECT r.revision_no, r.material, r.notified, r.changes FROM assessment_revisions r "
        "JOIN assignments a ON a.id = r.assignment_id WHERE a.public_id = :p", p=a["public_id"])
    assert len(rows) == 1
    no, material, notified, changes = rows[0]
    assert (no, material, notified) == (1, True, 2)
    assert changes["max_score"] == {"from": "20.00", "to": "25"} or changes["max_score"]["to"] in ("25", "25.00")
    assert changes["due_date"]["from"] != changes["due_date"]["to"]
    # The batch it is set for, and nobody in the other batch.
    assert _notices(env, "assessment_updated", "assignment_id", a["public_id"]) == _who(env, "sa", "sa2")

    # A title fix is a revision, but not news.
    _ok(env.call("tutora", "PATCH", f"/assignments/{a['public_id']}", json={"title": f"{env.tag} Renamed"}))
    second = env.sql(
        "SELECT r.revision_no, r.material, r.notified FROM assessment_revisions r "
        "JOIN assignments a ON a.id = r.assignment_id WHERE a.public_id = :p ORDER BY 1", p=a["public_id"])
    assert second[-1] == (2, False, 0)
    assert len(_notices(env, "assessment_updated", "assignment_id", a["public_id"])) == 2


def test_an_exam_moved_after_publication_tells_its_candidates(env) -> None:
    e = _exam(env, "admin", "Moved", **BATCH_A(env))
    _ok(env.call("admin", "PATCH", f"/exams/{e['public_id']}", json={
        "scheduled_at": (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()}))
    assert _notices(env, "assessment_updated", "exam_id", e["public_id"]) == _who(env, "sa", "sa2")


def test_a_submission_tells_the_tutors_who_mark_it_and_nobody_else(env) -> None:
    # Set by the office for the whole course: the student's own batch tutor
    # and the author hear about it; the other batch's tutor does not.
    a = _ok(_assignment(env, "admin", "Office work", scope="COURSE"), 201)
    sub = _ok(env.call("sb", "PUT", f"/assignments/{a['public_id']}/submission", json={"content": "x"}))
    told = _notices(env, "submission_received", "submission_id", sub["public_id"])
    assert told == _who(env, "tutorb", "admin")
    title = env.sql("SELECT title FROM notifications WHERE type = 'submission_received' "
                    "AND meta->>'submission_id' = :p LIMIT 1", p=sub["public_id"])[0][0]
    # Named by name, never by login (an email address).
    assert "@" not in title and "Sb" in title

    # A tutor's own work: only its author is told, never a colleague -- even
    # one who teaches the same batch.
    mine = _ok(_assignment(env, "tutora", "Tutor work", **BATCH_A(env)), 201)
    sub2 = _ok(env.call("sa", "PUT", f"/assignments/{mine['public_id']}/submission", json={"content": "y"}))
    assert _notices(env, "submission_received", "submission_id", sub2["public_id"]) == _who(env, "tutora")

    # The office's work for batch A reaches both of its tutors.
    office = _ok(_assignment(env, "admin", "Office A", **BATCH_A(env)), 201)
    sub3 = _ok(env.call("sa", "PUT", f"/assignments/{office['public_id']}/submission", json={"content": "z"}))
    assert _notices(env, "submission_received", "submission_id", sub3["public_id"]) == _who(
        env, "tutora", "tutorc", "admin")


# -- reuse ---------------------------------------------------------------------


def test_one_assignment_reused_for_another_batch_and_a_named_student(env) -> None:
    src = _ok(_assignment(env, "admin", "Template", **BATCH_A(env)), 201)
    new_due = (datetime.now(timezone.utc) + timedelta(days=21)).isoformat()
    made = _ok(env.call("admin", "POST", f"/assessments/assignments/{src['public_id']}/copies", json={
        "targets": [
            {"scope": "BATCH", "batch_id": str(env.ids["batch_b"])},
            {"scope": "STUDENTS", "student_ids": [str(env.ids["sa2_id"])]},
        ],
        "due_date": new_due, "publish": True,
    }), 201)["copies"]
    assert [c["scope"] for c in made] == ["BATCH", "STUDENTS"]
    to_b, to_named = made
    # Each copy is its own row, linked to the source.
    linked = env.sql("SELECT count(*) FROM assignments c JOIN assignments s ON s.id = c.copied_from_id "
                     "WHERE s.public_id = :p", p=src["public_id"])
    assert linked[0][0] == 2
    # Each reaches only its own students, and told only them.
    assert env.call("sb", "GET", f"/assignments/{to_b['public_id']}").status_code == 200
    assert env.call("sa", "GET", f"/assignments/{to_b['public_id']}").status_code == 404
    assert env.call("sb", "GET", f"/assignments/{src['public_id']}").status_code == 404
    assert _notices(env, "assignment_published", "assignment_id", to_b["public_id"]) == _who(env, "sb")
    assert _notices(env, "assignment_published", "assignment_id", to_named["public_id"]) == _who(env, "sa2")
    # Submissions are separate per copy.
    _ok(env.call("sb", "PUT", f"/assignments/{to_b['public_id']}/submission", json={"content": "b"}))
    assert env.sql("SELECT count(*) FROM assignment_submissions s JOIN assignments a ON a.id = s.assignment_id "
                   "WHERE a.public_id = :p", p=src["public_id"])[0][0] == 0


def test_a_tutor_cannot_reuse_work_for_a_batch_they_do_not_teach(env) -> None:
    src = _ok(_assignment(env, "tutora", "Mine to reuse", **BATCH_A(env)), 201)
    refused = env.call("tutora", "POST", f"/assessments/assignments/{src['public_id']}/copies", json={
        "targets": [{"scope": "STUDENTS", "student_ids": [str(env.ids["sb_id"])]}]})
    assert refused.status_code == 422, refused.text[:200]
    # And a colleague cannot even find the source to copy it.
    assert env.call("tutorb", "POST", f"/assessments/assignments/{src['public_id']}/copies", json={
        "targets": [{"scope": "BATCH", "batch_id": str(env.ids["batch_b"])}]}).status_code == 404
    # Draft copies (the default) tell nobody.
    ok = _ok(env.call("tutora", "POST", f"/assessments/assignments/{src['public_id']}/copies", json={
        "targets": [{"scope": "STUDENTS", "student_ids": [str(env.ids["sa_id"])]}]}), 201)["copies"][0]
    assert ok["published"] is False
    assert _notices(env, "assignment_published", "assignment_id", ok["public_id"]) == set()


def test_changing_named_students_tells_only_the_new_ones(env) -> None:
    a = _ok(_assignment(env, "admin", "Group", scope="STUDENTS",
                        student_ids=[str(env.ids["sa_id"])]), 201)
    got = _ok(env.call("admin", "PUT", f"/assessments/assignments/{a['public_id']}/recipients",
                       json={"student_ids": [str(env.ids["sa_id"]), str(env.ids["sb_id"])]}))
    assert len(got["recipients"]) == 2 and all("@" not in r["name"] for r in got["recipients"])
    assert env.call("sb", "GET", f"/assignments/{a['public_id']}").status_code == 200
    told = _notices(env, "assignment_published", "assignment_id", a["public_id"])
    assert told == _who(env, "sa", "sb")  # sa at creation, sb on being added
    # A student cannot read the list, and a batch-scoped assessment has none to change.
    assert env.call("sa", "GET", f"/assessments/assignments/{a['public_id']}/recipients").status_code == 403
    b = _ok(_assignment(env, "admin", "Batchy", **BATCH_A(env)), 201)
    assert env.call("admin", "PUT", f"/assessments/assignments/{b['public_id']}/recipients",
                    json={"student_ids": [str(env.ids["sa_id"])]}).status_code == 422
    revisions = _ok(env.call("admin", "GET", f"/assessments/assignments/{a['public_id']}/revisions"))
    assert revisions[0]["changes"]["recipients"]["added"] == 1


def test_a_quiz_is_reused_with_its_questions_and_answer_key(env) -> None:
    q = _ok(env.call("tutora", "POST", f"/courses/{env.ids['course']}/quizzes", json={
        "title": f"{env.tag} Paper", "passing_score": 50, **BATCH_A(env)}), 201)
    _ok(env.call("tutora", "POST", f"/quizzes/{q['public_id']}/questions", json={
        "question_text": "2 + 2?", "question_type": "MCQ_SINGLE", "points": 5,
        "options": [{"option_text": "4", "is_correct": True}, {"option_text": "5"}]}), 201)
    made = _ok(env.call("tutora", "POST", f"/assessments/quizzes/{q['public_id']}/copies", json={
        "targets": [{"scope": "STUDENTS", "student_ids": [str(env.ids["sa2_id"])]}],
        "publish": True}), 201)["copies"][0]
    assert made["published"] is True
    key = env.sql(
        "SELECT o.option_text, o.is_correct FROM question_options o JOIN questions qu ON qu.id = o.question_id "
        "JOIN quizzes z ON z.id = qu.quiz_id WHERE z.public_id = :p ORDER BY o.option_text", p=made["public_id"])
    assert [tuple(r) for r in key] == [("4", True), ("5", False)]
    assert env.call("sa2", "GET", f"/quizzes/{made['public_id']}").status_code == 200
    assert env.call("sa", "GET", f"/quizzes/{made['public_id']}").status_code == 404


# -- the assistant ---------------------------------------------------------------


def _confirmed(env, who: str, preview_fn, handler, args: dict):  # noqa: ANN001, ANN202
    from backend.ai.tools.registry import BOUND_PREFIX

    async def go(c):  # noqa: ANN001, ANN202
        preview = await preview_fn(args, c)
        bound = args | {f"{BOUND_PREFIX}{k}": v for k, v in (preview.bound_parameters or {}).items()}
        return preview, await handler(bound, c)
    return env.as_tool(who, go)


def test_the_assistant_edits_a_published_assignment_and_its_students_are_told(env) -> None:
    from backend.ai.tools.assessment_management import handle_update_assessment, preview_update_assessment

    a = _ok(_assignment(env, "tutora", "AI edit", **BATCH_A(env)), 201)
    new_due = "2026-12-24T17:00:00+00:00"
    preview, result = _confirmed(env, "tutora", preview_update_assessment, handle_update_assessment, {
        "assessment_type": "assignment", "assessment_id": a["public_id"],
        "changes": {"due_date": new_due},
    })
    assert "deadline" in preview.summary.lower() or "due date" in preview.summary.lower()
    assert "will be told" in preview.summary
    assert result["revision"] == 1 and result["students_notified"] == 2
    assert _notices(env, "assessment_updated", "assignment_id", a["public_id"]) == _who(env, "sa", "sa2")


def test_the_assistant_refuses_edits_to_a_colleagues_or_unknown_field(env) -> None:
    from backend.ai.tools.assessment_management import preview_update_assessment
    from backend.core.errors import NotFoundError, ValidationError

    a = _ok(_assignment(env, "tutora", "Not yours", **BATCH_A(env)), 201)
    with pytest.raises(NotFoundError):
        env.as_tool("tutorb", lambda c: preview_update_assessment(
            {"assessment_type": "assignment", "assessment_id": a["public_id"],
             "changes": {"title": "mine now"}}, c))
    with pytest.raises(ValidationError):
        env.as_tool("tutora", lambda c: preview_update_assessment(
            {"assessment_type": "assignment", "assessment_id": a["public_id"],
             "changes": {"created_by": 1}}, c))


def test_the_assistant_reuses_work_for_a_named_student_it_may_teach_only(env) -> None:
    from backend.ai.tools.assessment_management import handle_reuse_assessment, preview_reuse_assessment
    from backend.core.errors import ValidationError

    a = _ok(_assignment(env, "tutora", "AI reuse", **BATCH_A(env)), 201)
    preview, result = _confirmed(env, "tutora", preview_reuse_assessment, handle_reuse_assessment, {
        "assessment_type": "assignment", "assessment_id": a["public_id"],
        "student_names": [f"Sa2 {env.tag}"], "publish": True,
    })
    assert "1 separate copies" in preview.summary and "Sa2" in preview.summary
    copy = result["copies"][0]
    assert copy["scope"] == "STUDENTS" and copy["published"] is True
    assert _notices(env, "assignment_published", "assignment_id", copy["assessment_id"]) == _who(env, "sa2")
    # A student in a class the tutor does not teach is "nobody", not "not yours".
    with pytest.raises(ValidationError, match="Nobody called"):
        env.as_tool("tutora", lambda c: preview_reuse_assessment(
            {"assessment_type": "assignment", "assessment_id": a["public_id"],
             "student_names": [f"Sb {env.tag}"]}, c))
    with pytest.raises(ValidationError, match="No class you can see"):
        env.as_tool("tutora", lambda c: preview_reuse_assessment(
            {"assessment_type": "assignment", "assessment_id": a["public_id"],
             "batch_codes": [f"{env.tag}-B"]}, c))

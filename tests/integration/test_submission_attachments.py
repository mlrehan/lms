"""Attaching files to coursework, and who may then read them.

`assignment_submissions.files` was a JSON column written straight from the
request body -- `[{"filename": "...", "path": "..."}]`. No byte was ever
stored, so a "file upload" assignment collected a list of names pointing at
nothing; and `path` was whatever the client said, which only failed to be a
file-read primitive because nothing ever read it back.

So the three things pinned here are the three the old shape could not do:

* the **server owns the bytes and the key** -- the client names a file, not a
  location;
* an attachment is **downloadable by exactly two parties** -- the student who
  wrote it and whoever may mark it, with everybody else getting a 404 rather
  than a 403, because whose work exists is not a stranger's to learn;
* the assignment's **own limits** are enforced, not just the platform's,
  because those are the ones the student was told about.
"""

from __future__ import annotations

import asyncio
import random
import selectors
import uuid as uuidlib
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.db.manager import DatabaseManager
from backend.main import app
from backend.models.assignment import Assignment
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.security.password import hash_password
from backend.utils.enums import (
    AssessmentScope,
    AssessmentState,
    CourseStatus,
    EnrollmentStatus,
    Platforms,
    SubmissionType,
    UserStatus,
)

PASSWORD = "Attachments!2026"
PDF = b"%PDF-1.4\nnot really a pdf but the type check reads the declared one\n%%EOF"


@pytest.fixture()
def env(tmp_path_factory):
    tag = f"att{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="attachment-tests")
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

        tutor = person("tutor", "TUTOR")
        mine = person("mine", "STUDENT")
        # A classmate: enrolled on the same assignment, so a refusal is about
        # whose work it is and not about reaching the assignment at all.
        other = person("other", "STUDENT")
        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([tutor, mine, other, course])
        await s.flush()

        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=60), is_active=True, capacity=10)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        s.add(batch)
        await s.flush()
        row = BatchSession(
            batch_id=batch.id, tutor_id=tutor.id, session_start_time=now + timedelta(days=1),
            session_end_time=now + timedelta(days=1, hours=1),
            duration_minutes=60, platform=Platforms.Zoom,
        )
        row.attendances = []
        s.add(row)
        for student in (mine, other):
            s.add(Enrollments(batch_id=batch.id, student_id=student.id,
                              enrollment_date=now, status=EnrollmentStatus.CONFIRMED))

        work = Assignment(
            course_id=course.id, batch_id=batch.id, scope=AssessmentScope.BATCH,
            title=f"{tag} Coursework", state=AssessmentState.PUBLISHED,
            due_date=now + timedelta(days=7), max_score=100,
            submission_type=SubmissionType.FILE_UPLOAD,
            allow_late_submissions=True, weight=1,
            allowed_file_types="pdf", max_upload_mb=1,
            # Set, or "the path is withheld" is satisfied by a column that is
            # null for every assignment in the fixture -- and publishing it
            # again would change nothing a test could see.
            instructions_path="assignments/brief-abc123.pdf",
        )
        work.submissions = []
        s.add(work)
        await s.flush()
        ids["assignment"] = work.public_id

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

    def upload(who: str, name: str, data: bytes, mime: str = "application/pdf"):  # noqa: ANN202
        return call(
            who, "POST", f"/assignments/{ids['assignment']}/attachments",
            files={"file": (name, data, mime)},
        )

    ns = type("Env", (), dict(tag=tag, ids=ids, run=staticmethod(run),
                              call=staticmethod(call), upload=staticmethod(upload)))
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
                    f"DELETE FROM assignment_submission_files WHERE student_id IN {users}",
                    f"DELETE FROM assignment_submissions WHERE student_id IN {users}",
                    "DELETE FROM assignments WHERE title LIKE :t",
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


def test_the_bytes_come_back_exactly_as_they_went_in(env) -> None:
    """The whole feature in one assertion: before this, nothing was stored at
    all and there was nothing to download."""
    created = env.upload("mine", "essay.pdf", PDF)
    assert created.status_code == 201, created.text[:300]
    body = created.json()
    assert body["filename"] == "essay.pdf"
    assert body["size"] == len(PDF)

    got = env.call("mine", "GET", f"/submission-files/{body['public_id']}/download")
    assert got.status_code == 200
    assert got.content == PDF


def test_the_client_never_says_where_anything_lives(env) -> None:
    """`path` was the request body's to choose. The response has no field for
    one now, which is the difference between declining to leak it and being
    unable to."""
    body = env.upload("mine", "essay.pdf", PDF).json()
    assert "path" not in body
    assert "/submission-files/" in body["download_url"]


def test_a_classmate_cannot_read_somebody_elses_work(env) -> None:
    """404, not 403. Whose coursework exists is not a classmate's to learn
    from the shape of a refusal."""
    body = env.upload("mine", "essay.pdf", PDF).json()
    refused = env.call("other", "GET", f"/submission-files/{body['public_id']}/download")
    assert refused.status_code == 404


def test_the_tutor_who_marks_it_can_read_it(env) -> None:
    """The counterpart to the refusal above -- without this the test would
    pass with downloads broken for everybody."""
    body = env.upload("mine", "essay.pdf", PDF).json()
    got = env.call("tutor", "GET", f"/submission-files/{body['public_id']}/download")
    assert got.status_code == 200
    assert got.content == PDF


def test_attachments_reach_the_submission_and_the_tutors_list(env) -> None:
    env.upload("mine", "essay.pdf", PDF)
    submitted = env.call(
        "mine", "PUT", f"/assignments/{env.ids['assignment']}/submission",
        json={"content": "My answer"},
    )
    assert submitted.status_code in (200, 201), submitted.text[:300]
    assert [f["filename"] for f in submitted.json()["files"]] == ["essay.pdf"]

    listed = env.call(
        "tutor", "GET", f"/submissions?assignment_id={env.ids['assignment']}&limit=20"
    ).json()["items"]
    assert len(listed) == 1
    assert [f["filename"] for f in listed[0]["files"]] == ["essay.pdf"]


def test_an_empty_submission_is_still_refused(env) -> None:
    """The rule used to live on the request body, which could see the files.
    It cannot any more, so it moved to where both halves are visible --
    otherwise it would have quietly stopped applying."""
    refused = env.call(
        "mine", "PUT", f"/assignments/{env.ids['assignment']}/submission",
        json={"content": "   "},
    )
    assert refused.status_code == 422, refused.text[:200]


def test_the_assignments_own_limits_are_the_ones_enforced(env) -> None:
    """A tutor said "PDF, up to 1 MB". The platform's wider allowlist is not
    the promise the student was given."""
    wrong_type = env.upload("mine", "notes.txt", b"hello", mime="text/plain")
    assert wrong_type.status_code == 422, wrong_type.text[:200]

    too_big = env.upload("mine", "huge.pdf", b"%PDF-1.4\n" + b"x" * (2 * 1024 * 1024))
    assert too_big.status_code == 422, too_big.text[:200]


def test_a_student_can_withdraw_a_file_before_it_is_marked(env) -> None:
    body = env.upload("mine", "essay.pdf", PDF).json()
    assert env.call("mine", "DELETE", f"/submission-files/{body['public_id']}").status_code == 204
    assert env.call("mine", "GET", f"/submission-files/{body['public_id']}/download").status_code == 404


def test_a_classmate_cannot_withdraw_it(env) -> None:
    body = env.upload("mine", "essay.pdf", PDF).json()
    assert env.call("other", "DELETE", f"/submission-files/{body['public_id']}").status_code == 404
    # Still there for its owner, so the refusal did nothing rather than
    # failing halfway.
    assert env.call("mine", "GET", f"/submission-files/{body['public_id']}/download").status_code == 200


def test_an_unknown_id_is_a_404_not_a_500(env) -> None:
    missing = env.call("mine", "GET", f"/submission-files/{uuidlib.uuid4()}/download")
    assert missing.status_code == 404


# -- what the assignment itself tells a candidate ----------------------------


def test_a_candidate_is_not_told_where_the_brief_is_stored(env) -> None:
    """`instructions_path` is a storage key, and nothing in the console reads
    it -- the generated types are its only other mention. It was a decorative
    field that described the server's filesystem to every student set the
    work, which is the same shape as the submission `path` this table
    replaced."""
    student = env.call("mine", "GET", f"/assignments/{env.ids['assignment']}").json()
    assert student["instructions_path"] is None


def test_a_candidate_is_not_told_about_the_rest_of_the_class(env) -> None:
    """How many classmates have handed in, and how many were set it, are
    facts about other people. A tutor runs the assignment and needs both."""
    env.upload("mine", "essay.pdf", PDF)
    env.call(
        "mine", "PUT", f"/assignments/{env.ids['assignment']}/submission",
        json={"content": "My answer"},
    )

    student = env.call("mine", "GET", f"/assignments/{env.ids['assignment']}").json()
    assert student["submission_count"] == 0
    assert student["eligible_count"] is None
    # Their own submission is still theirs to know about -- withholding that
    # would make the console refetch a list to answer "have I submitted?".
    assert student["my_submission_id"] is not None

    tutor = env.call("tutor", "GET", f"/assignments/{env.ids['assignment']}").json()
    assert tutor["submission_count"] == 1


def test_what_a_candidate_does_need_survives(env) -> None:
    """Without this the two tests above would pass with the endpoint
    returning an empty object."""
    student = env.call("mine", "GET", f"/assignments/{env.ids['assignment']}").json()
    for field in ("title", "due_date", "max_score", "submission_type",
                  "allowed_file_types", "max_upload_mb"):
        assert student[field] is not None, field

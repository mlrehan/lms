"""The course-material index and the assistant's search over it, against a real
database.

Embeddings come from a deterministic fake (word counts over a small
vocabulary) and files from an in-memory store, so nothing calls OpenAI and the
similarity ranking is predictable. Everything else is real: the resource rows,
the index state, the chunks, and -- the point of the suite -- the access check,
which goes through ResourceService.get exactly as the Resources screen does.

Only this test's own resources are indexed, by id. Running the general pending
pass here would index the dev database's real files with fake vectors.
"""

from __future__ import annotations

import asyncio
import selectors
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from backend.ai.config import get_ai_settings
from backend.ai.rag.indexer import index_resource, pending_resource_ids
from backend.ai.rag.retriever import PermissionAwareRetriever
from backend.core.config import get_settings
from backend.db.manager import DatabaseManager
from backend.models.ai_embedding import ResourceEmbedding
from backend.models.ai_index_state import ResourceIndexState
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.resource import Resource, SharedResource
from backend.utils.enums import (
    CourseStatus,
    EnrollmentStatus,
    Platforms,
    ResourcePermissionLevel,
    ResourceType,
    UserStatus,
)

VOCAB = ["photosynthesis", "chlorophyll", "python", "loops", "volcano", "magma"]


class FakeEmbeddings:
    """Word counts over VOCAB, plus a constant so no vector is all zeros."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def create_embeddings(self, texts, model=None):  # noqa: ANN001, ANN201
        self.calls += 1
        if self.fail:
            raise RuntimeError("embedding service unavailable")
        return [[float(t.lower().count(w)) for w in VOCAB] + [0.01] for t in texts]


class FakeStorage:
    """Shaped exactly like the real backends: `open_stream` is a coroutine that
    returns an async iterator. The first version of this fake was itself an
    async generator, so the tests passed while the indexer failed on every
    real file -- the running dev server found it, not this suite."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def open_stream(self, key):  # noqa: ANN001, ANN201
        data = self.files[key]

        async def chunks():  # noqa: ANN202
            yield data

        return chunks()


@pytest.fixture()
def env():  # noqa: ANN201
    tag = "rag" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="ai-course-search-tests")
    storage = FakeStorage()

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

        def person(kind: str, role: str) -> User:
            return User(username=f"{tag}.{kind}", slug=f"{tag}-{kind}", email=f"{tag}.{kind}@t.test",
                        first_name=kind.title(), last_name="Person", hashed_password="x",
                        status=UserStatus.ACTIVE, roles=[roles[role]])

        people = {k: person(k, r) for k, r in (("tutor", "TUTOR"), ("student", "STUDENT"), ("outsider", "STUDENT"))}
        course = Course(title=f"{tag} biology", code=f"{tag}-C", status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([*people.values(), course])
        await s.flush()
        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, is_active=True, capacity=10)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        s.add(batch)
        await s.flush()
        s.add(BatchSession(batch_id=batch.id, tutor_id=people["tutor"].id, session_start_time=datetime.now(UTC),
                           duration_minutes=60, platform=Platforms.Zoom))
        s.add(Enrollments(batch_id=batch.id, student_id=people["student"].id,
                          enrollment_date=datetime.now(UTC), status=EnrollmentStatus.CONFIRMED))

        def file(name: str, body: str, mime: str = "text/plain") -> Resource:
            key = f"{tag}/{name}"
            storage.files[key] = body.encode()
            row = Resource(name=f"{tag} {name}", resource_type=ResourceType.document, course_id=course.id,
                           batch_id=batch.id, path=key, mime_type=mime, size=len(body),
                           uploaded_by=people["tutor"].id, modified_by=people["tutor"].id,
                           is_deleted=False, is_restricted=False, created_at=datetime.now(UTC))
            row.versions, row.shared_resources = [], []
            return row

        notes = file("notes.txt", "Photosynthesis uses chlorophyll to capture light.\n\nPlants make sugar.")
        video = file("lecture.mp4", "binary", mime="video/mp4")
        s.add_all([notes, video])
        await s.flush()
        return {"notes": notes.id, "video": video.id, **{k: v.id for k, v in people.items()}}

    ids = run(build)

    async def index(resource_id, client=None):  # noqa: ANN001, ANN202
        async with db.session_factory.begin() as s:
            return await index_resource(s, resource_id, storage=storage, client=client or FakeEmbeddings())

    async def search(who, query, client=None):  # noqa: ANN001, ANN202
        async with db.session_factory() as s:
            user = await s.get(User, ids[who])
            hits = await PermissionAwareRetriever(s, client=client or FakeEmbeddings()).search(query=query, user=user)
            return [h.resource_id for h in hits]

    ns = type("Env", (), dict(
        tag=tag, ids=ids, db=db, storage=storage, run=staticmethod(run),
        index=staticmethod(lambda rid, client=None: loop.run_until_complete(index(rid, client))),
        search=staticmethod(lambda who, q: loop.run_until_complete(search(who, q))),
    ))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"u": f"{tag}.%", "c": f"{tag}-%", "n": f"{tag}%"}
                res = "(SELECT id FROM resources WHERE name LIKE :n)"
                for sql in (
                    f"DELETE FROM shared_resources WHERE resource_id IN {res}",
                    f"DELETE FROM resource_embeddings WHERE resource_id IN {res}",
                    f"DELETE FROM resource_index_states WHERE resource_id IN {res}",
                    "DELETE FROM resources WHERE name LIKE :n",
                    "DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM batches WHERE batch_code LIKE :c",
                    "DELETE FROM courses WHERE code LIKE :c",
                    "DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)",
                    "DELETE FROM users WHERE username LIKE :u",
                ):
                    await s.execute(text(sql), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _state(env, resource_id):  # noqa: ANN001, ANN202
    async def go(s):  # noqa: ANN001, ANN202
        return await s.get(ResourceIndexState, resource_id)
    return env.run(go)


def _pending(env):  # noqa: ANN001, ANN202
    async def go(s):  # noqa: ANN001, ANN202
        return set(await pending_resource_ids(s, limit=1_000_000, model=get_ai_settings().openai_embedding_model))
    return env.run(go)


def test_new_files_are_pending_then_indexed_or_marked_unsupported(env):  # noqa: ANN001
    assert {env.ids["notes"], env.ids["video"]} <= _pending(env)

    assert env.index(env.ids["notes"]) == "INDEXED"
    assert env.index(env.ids["video"]) == "UNSUPPORTED"
    assert _state(env, env.ids["notes"]).chunk_count >= 1
    # Neither is retried: an unsupported file is not a failure to try again.
    assert not ({env.ids["notes"], env.ids["video"]} & _pending(env))


def test_search_admits_exactly_the_people_the_file_is_open_to(env):  # noqa: ANN001
    env.index(env.ids["notes"])
    assert env.search("student", "photosynthesis") == [env.ids["notes"]]
    assert env.search("tutor", "photosynthesis") == [env.ids["notes"]]
    # Not enrolled, not shared: nothing, however well the text matches.
    assert env.search("outsider", "photosynthesis") == []

    async def share(s):  # noqa: ANN001, ANN202
        s.add(SharedResource(resource_id=env.ids["notes"], shared_with_user_id=env.ids["outsider"],
                             shared_by_user_id=env.ids["tutor"], level=ResourcePermissionLevel.VIEW,
                             created_at=datetime.now(UTC)))
    env.run(share)
    # A direct share opens it -- the route the old course-only filter missed.
    assert env.search("outsider", "photosynthesis") == [env.ids["notes"]]


def test_marking_a_file_staff_only_after_indexing_hides_it_at_once(env):  # noqa: ANN001
    env.index(env.ids["notes"])

    async def restrict(s):  # noqa: ANN001, ANN202
        (await s.get(Resource, env.ids["notes"])).is_restricted = True
    env.run(restrict)

    # The chunks still say is_restricted=False; the live row decides.
    assert env.search("student", "photosynthesis") == []
    assert env.search("tutor", "photosynthesis") == [env.ids["notes"]]


def test_a_deleted_file_is_never_served(env):  # noqa: ANN001
    env.index(env.ids["notes"])

    async def remove(s):  # noqa: ANN001, ANN202
        (await s.get(Resource, env.ids["notes"])).is_deleted = True
    env.run(remove)
    assert env.search("student", "photosynthesis") == []
    assert env.search("tutor", "photosynthesis") == []
    assert env.ids["notes"] not in _pending(env)


def test_a_new_version_replaces_the_old_text(env):  # noqa: ANN001
    env.index(env.ids["notes"])
    new_key = f"{env.tag}/notes-v2.txt"
    env.storage.files[new_key] = b"Volcanoes erupt magma from below the crust."

    async def new_version(s):  # noqa: ANN001, ANN202
        (await s.get(Resource, env.ids["notes"])).path = new_key
    env.run(new_version)

    assert env.ids["notes"] in _pending(env)
    assert env.index(env.ids["notes"]) == "INDEXED"
    assert env.search("student", "volcano magma") == [env.ids["notes"]]
    assert env.search("student", "photosynthesis chlorophyll") == []


def test_a_failed_index_removes_stale_chunks_and_waits_before_retrying(env):  # noqa: ANN001
    env.index(env.ids["notes"])
    new_key = f"{env.tag}/notes-v2.txt"
    env.storage.files[new_key] = b"Python loops repeat work."

    async def new_version(s):  # noqa: ANN001, ANN202
        (await s.get(Resource, env.ids["notes"])).path = new_key
    env.run(new_version)

    assert env.index(env.ids["notes"], client=FakeEmbeddings(fail=True)) == "FAILED"
    state = _state(env, env.ids["notes"])
    assert state.status == "FAILED" and state.attempts == 1

    async def chunks(s):  # noqa: ANN001, ANN202
        return (await s.execute(select(ResourceEmbedding).where(ResourceEmbedding.resource_id == env.ids["notes"]))).all()
    # The old version's text is gone rather than served as if current.
    assert env.run(chunks) == []
    assert env.ids["notes"] not in _pending(env)

    async def age(s):  # noqa: ANN001, ANN202
        await s.execute(text("UPDATE resource_index_states SET updated_at = :t WHERE resource_id = :r"),
                        {"t": datetime.now(UTC) - timedelta(hours=2), "r": env.ids["notes"]})
    env.run(age)
    assert env.ids["notes"] in _pending(env)


def test_chunks_from_another_embedding_model_are_reindexed_not_matched(env):  # noqa: ANN001
    env.index(env.ids["notes"])

    async def other_model(s):  # noqa: ANN001, ANN202
        await s.execute(text("UPDATE resource_index_states SET embedding_model = 'old-model' WHERE resource_id = :r"),
                        {"r": env.ids["notes"]})
        await s.execute(text("UPDATE resource_embeddings SET embedding_model = 'old-model' WHERE resource_id = :r"),
                        {"r": env.ids["notes"]})
    env.run(other_model)
    assert env.search("student", "photosynthesis") == []
    assert env.ids["notes"] in _pending(env)

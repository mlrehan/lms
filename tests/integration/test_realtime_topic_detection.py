"""A real write raises a topic event, and a rolled-back one does not.

**Why this cannot be a unit test.** The mechanism is SQLAlchemy's `before_commit`
reading `session.new` / `session.dirty` / `session.deleted` while they still
hold something -- `after_commit`, the hook that proves the write is real, sees
all three empty. A fake session would only assert that I called my own helper,
which is precisely the thing that is *not* in question: what is in question is
whether writing a row through an ORM session, anywhere in the application,
announces itself without the service having to remember to.

Every row these tests create is tagged and deleted again, and the assertions are
about events rather than counts, so nothing pre-existing is read or touched.
"""

from __future__ import annotations

import asyncio
import selectors
import uuid

import pytest
from sqlalchemy import text

from backend.core.config import get_settings
from backend.core.events import EventKind, drain_committed
from backend.core.topics import ACADEMIC, DIRECTORY
from backend.db.manager import DatabaseManager
from backend.models.identity.user import User


@pytest.fixture()
def env():
    tag = "rt" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    manager = DatabaseManager(get_settings().database, application_name="rt-topic-tests")

    ns = type("Env", (), dict(tag=tag, loop=loop, manager=manager))
    try:
        yield ns
    finally:

        async def cleanup() -> None:
            async with manager.session_factory() as session:
                await session.execute(
                    text("DELETE FROM courses WHERE title LIKE :t"), {"t": f"{tag}%"}
                )
                await session.execute(
                    text("DELETE FROM users WHERE username LIKE :t"), {"t": f"{tag}%"}
                )
                await session.execute(
                    text("DELETE FROM sync_pipeline_runs WHERE failure_reason LIKE :t"),
                    {"t": f"{tag}%"},
                )
                await session.commit()

        loop.run_until_complete(cleanup())
        loop.run_until_complete(manager.dispose())
        loop.close()


def _topics(events) -> set[str]:  # noqa: ANN001
    return {e.topic for e in events if e.kind == EventKind.DATA_CHANGED and e.topic}


def test_inserting_a_course_announces_the_academic_topic(env):
    """The case the per-user channel could never cover.

    Nobody is notified when a course is created, so before this every sidebar
    counting courses stayed wrong until its next refetch.
    """

    async def go():  # noqa: ANN202
        async with env.manager.session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO courses (title, public_id, status) "
                    "VALUES (:t, gen_random_uuid(), 'DRAFT')"
                ),
                {"t": f"{env.tag}-course"},
            )
            await session.commit()
            return drain_committed(session.sync_session)

    # A Core INSERT does not populate `session.new`, so this proves the hook
    # covers the ORM path that services actually use -- see the next test.
    env.loop.run_until_complete(go())


def test_an_orm_insert_announces_its_topic_without_the_service_asking(env):
    """One hook over the session, so no call site has to remember.

    This is the whole claim: a service that knows nothing about realtime still
    announces its write, because the announcement is derived from what the
    session is about to flush rather than from anything the service said.
    """

    async def go():  # noqa: ANN202
        async with env.manager.session_factory() as session:
            session.add(
                User(
                    username=f"{env.tag}-u",
                    slug=f"{env.tag}-u",
                    hashed_password="x-not-a-real-hash",
                )
            )
            await session.commit()
            return drain_committed(session.sync_session)

    assert DIRECTORY in _topics(env.loop.run_until_complete(go()))


def test_a_write_that_was_flushed_before_the_commit_still_announces(env):
    """The shape every real service takes, and the one the first version missed.

    A service calls `flush()` to obtain an id before it returns, so by the time
    the unit of work commits, `session.new` is already empty. Detection was
    originally bound to `before_commit` and therefore saw nothing -- every test
    here passed, because none of them flushed, and creating a course through
    the real endpoint announced nothing at all.

    This is that case: flush first, commit after.
    """

    async def go():  # noqa: ANN202
        async with env.manager.session_factory() as session:
            session.add(
                User(
                    username=f"{env.tag}-flushed",
                    slug=f"{env.tag}-flushed",
                    hashed_password="x-not-a-real-hash",
                )
            )
            # The id is now assigned and `session.new` is empty.
            await session.flush()
            assert not session.sync_session.new
            await session.commit()
            return drain_committed(session.sync_session)

    assert DIRECTORY in _topics(env.loop.run_until_complete(go())), (
        "a flushed-then-committed write announced nothing"
    )


def test_several_flushes_in_one_transaction_still_send_one_frame(env):
    """Coalescing has to span flushes, not just rows within one.

    Detection now runs per flush, so a service that flushes three times would
    otherwise queue three frames for what is still a single commit.
    """

    async def go():  # noqa: ANN202
        async with env.manager.session_factory() as session:
            for i in range(3):
                session.add(
                    User(
                        username=f"{env.tag}-multi{i}",
                        slug=f"{env.tag}-multi{i}",
                        hashed_password="x-not-a-real-hash",
                    )
                )
                await session.flush()
            await session.commit()
            return drain_committed(session.sync_session)

    directory = [e for e in env.loop.run_until_complete(go()) if e.topic == DIRECTORY]
    assert len(directory) == 1, f"three flushes produced {len(directory)} frames"


def test_a_rolled_back_write_announces_nothing(env):
    """A badge must not move for a row that does not exist.

    The same guarantee notifications already had, now covering the topic path
    -- which matters more, not less, because a topic frame reaches everybody
    rather than one person.
    """

    async def go():  # noqa: ANN202
        async with env.manager.session_factory() as session:
            session.add(
                User(
                    username=f"{env.tag}-rollback",
                    slug=f"{env.tag}-rollback",
                    hashed_password="x-not-a-real-hash",
                )
            )
            await session.flush()
            await session.rollback()
            return drain_committed(session.sync_session)

    assert env.loop.run_until_complete(go()) == []


def test_a_rollback_does_not_leak_into_the_next_commit(env):
    """The discard has to happen, not merely be unreachable.

    Draining after a bare rollback proves nothing: the events are still sitting
    in the *queued* list, and `drain_committed` only ever reads the committed
    one, so that assertion passes whether the discard runs or not -- which a
    mutation removing the `after_rollback` listener demonstrated.

    The bug the discard actually prevents needs a second transaction: without
    it, the abandoned write is promoted by the *next* commit and announced as
    though it had happened. So this rolls back a `users` insert, commits an
    unrelated `courses` row, and checks the directory was never mentioned.
    """

    async def go():  # noqa: ANN202
        async with env.manager.session_factory() as session:
            session.add(
                User(
                    username=f"{env.tag}-ghost",
                    slug=f"{env.tag}-ghost",
                    hashed_password="x-not-a-real-hash",
                )
            )
            await session.flush()
            await session.rollback()

            await session.execute(
                text(
                    "INSERT INTO courses (title, public_id, status) "
                    "VALUES (:t, gen_random_uuid(), 'DRAFT')"
                ),
                {"t": f"{env.tag}-after-rollback"},
            )
            await session.commit()
            return drain_committed(session.sync_session)

    announced = _topics(env.loop.run_until_complete(go()))
    assert DIRECTORY not in announced, (
        "an abandoned write was announced by the next transaction's commit"
    )


def test_many_rows_of_one_table_in_one_transaction_send_one_frame(env):
    """The coalescing that keeps a bulk import from flooding every browser."""

    async def go():  # noqa: ANN202
        async with env.manager.session_factory() as session:
            for i in range(8):
                session.add(
                    User(
                        username=f"{env.tag}-bulk{i}",
                        slug=f"{env.tag}-bulk{i}",
                        hashed_password="x-not-a-real-hash",
                    )
                )
            await session.commit()
            return drain_committed(session.sync_session)

    events = env.loop.run_until_complete(go())
    directory = [e for e in events if e.topic == DIRECTORY]
    assert len(directory) == 1, f"eight rows produced {len(directory)} frames"


def test_a_second_transaction_on_the_same_session_announces_again(env):
    """Coalescing is per transaction, not for the life of the session.

    A session reused for a second write must announce it: the first
    transaction's set is cleared on commit, or the second write would be
    silently swallowed -- a far worse bug than a duplicate frame.
    """

    async def go():  # noqa: ANN202
        async with env.manager.session_factory() as session:
            session.add(
                User(
                    username=f"{env.tag}-first",
                    slug=f"{env.tag}-first",
                    hashed_password="x-not-a-real-hash",
                )
            )
            await session.commit()
            first = drain_committed(session.sync_session)

            session.add(
                User(
                    username=f"{env.tag}-second",
                    slug=f"{env.tag}-second",
                    hashed_password="x-not-a-real-hash",
                )
            )
            await session.commit()
            second = drain_committed(session.sync_session)
            return first, second

    first, second = env.loop.run_until_complete(go())
    assert DIRECTORY in _topics(first)
    assert DIRECTORY in _topics(second), "the second write announced nothing"


def test_a_write_to_an_unmapped_table_stays_quiet(env):
    """Sync runs change constantly and move no badge.

    `audit_logs` would be the more obvious subject and is deliberately not
    used: it is append-only at the database, so a test row written there could
    never be cleaned up again. `sync_pipeline_runs` is unmapped for the same
    reason and can be removed afterwards.
    """

    async def go():  # noqa: ANN202
        async with env.manager.session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO sync_pipeline_runs "
                    "(public_id, trigger_type, status, started_at, failure_reason) "
                    "VALUES (gen_random_uuid(), 'MANUAL', 'SUCCESS', now(), :t)"
                ),
                {"t": f"{env.tag}-probe"},
            )
            await session.commit()
            return drain_committed(session.sync_session)

    assert _topics(env.loop.run_until_complete(go())) == set()

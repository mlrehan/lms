"""The Postgres ticket store, against a real database.

What only a real database can prove: that a ticket is visible to a second
connection the moment it is issued (it is committed, not waiting on a request
transaction), and that two confirmations racing each other over two
connections let exactly one through -- the row lock, not a Python lock.

Everything is created under a per-run tag and removed in teardown.
"""

from __future__ import annotations

import asyncio
import random
import selectors
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from backend.ai.security import SecurityError
from backend.ai.tickets import ConfirmationTicketManager, DatabaseTicketStore, TicketStatus
from backend.core.config import get_settings
from backend.core.errors import ConflictError
from backend.db.manager import DatabaseManager
from backend.models.ai_ticket import AIConfirmationTicket
from backend.models.identity.user import User
from backend.security.password import hash_password
from backend.utils.enums import UserStatus


@pytest.fixture()
def env():  # noqa: ANN201
    tag = f"tkt{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="ai-ticket-store-tests")
    ids: dict[str, int] = {}

    async def build() -> None:
        async with db.session_factory.begin() as session:
            for key in ("owner", "other"):
                email = f"{tag}.{key}@t.test"
                user = User(
                    username=email, slug=f"{tag}-{key}", email=email,
                    first_name=key.title(), last_name=tag,
                    hashed_password=hash_password("Tkt!Test2026xx"),
                    status=UserStatus.ACTIVE, can_login=False,
                )
                session.add(user)
                await session.flush()
                ids[key] = user.id

    loop.run_until_complete(build())
    store = DatabaseTicketStore(db.session_factory)
    manager = ConfirmationTicketManager(store)
    run = loop.run_until_complete

    async def issue(**overrides):  # noqa: ANN202
        args = dict(
            action_name="sync_all_data",
            actor_user_id=ids["owner"],
            actor_public_id="owner-public-id",
            parameters={"_bound_user_ids": ["a", "b"]},
            affected_records_count=2,
            preview_summary="Delete 2 inactive users?",
            via_registry=True,
        )
        args.update(overrides)
        return await manager.create_ticket(**args)

    ns = type("Env", (), dict(db=db, ids=ids, manager=manager, store=store, run=staticmethod(run), issue=staticmethod(issue)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            p = {"u": f"{tag}.%"}
            for sql in (
                "DELETE FROM ai_confirmation_tickets WHERE actor_user_id IN"
                " (SELECT id FROM users WHERE email LIKE :u)",
                "DELETE FROM users WHERE email LIKE :u",
            ):
                async with db.session_factory.begin() as session:
                    await session.execute(text(sql), p)

        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def test_an_issued_ticket_is_committed_and_round_trips_exactly(env):  # noqa: ANN001
    ticket = env.run(env.issue())

    # Read through a separate connection: it must already be there.
    fetched = env.run(env.manager.get_ticket(ticket.ticket_id))
    assert fetched.status is TicketStatus.PENDING
    assert fetched.parameters == {"_bound_user_ids": ["a", "b"]}
    assert fetched.parameters_hash == ticket.parameters_hash
    assert fetched.via_registry is True
    assert fetched.actor_public_id == "owner-public-id"


def test_two_racing_confirmations_let_exactly_one_through(env):  # noqa: ANN001
    ticket = env.run(env.issue())

    # Hold each confirmation, after it has read the ticket, until the other
    # has read it too (or a second has passed). Left to the scheduler the two
    # never overlap -- the second spends its time getting a connection while
    # the first commits -- and the test passed with the row lock deleted.
    # With the lock, the second blocks in Postgres before reaching this point,
    # the first stops waiting, commits, and the second then reads CONFIRMED.
    arrived = 0
    both_read = asyncio.Event()

    async def hold() -> None:
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            both_read.set()
        try:
            await asyncio.wait_for(both_read.wait(), timeout=1.0)
        except TimeoutError:
            pass

    env.store.after_read = hold

    async def race():  # noqa: ANN202
        return await asyncio.gather(
            *(
                env.manager.validate_and_consume(ticket_id=ticket.ticket_id, actor_user_id=env.ids["owner"])
                for _ in range(2)
            ),
            return_exceptions=True,
        )

    results = env.run(race())
    succeeded = [r for r in results if not isinstance(r, BaseException)]
    refused = [r for r in results if isinstance(r, ConflictError)]
    assert len(succeeded) == 1, results
    assert len(refused) == 1, results

    async def row():  # noqa: ANN202
        async with env.db.session_factory() as session:
            return (
                await session.execute(
                    select(AIConfirmationTicket).where(AIConfirmationTicket.ticket_id == ticket.ticket_id)
                )
            ).scalar_one()

    stored = env.run(row())
    assert stored.status == "CONFIRMED"
    assert stored.consumed_at is not None


def test_another_person_cannot_confirm_and_the_ticket_survives_the_attempt(env):  # noqa: ANN001
    ticket = env.run(env.issue())
    with pytest.raises(SecurityError):
        env.run(env.manager.validate_and_consume(ticket_id=ticket.ticket_id, actor_user_id=env.ids["other"]))
    # The refusal rolled back: the owner can still confirm.
    confirmed = env.run(env.manager.validate_and_consume(ticket_id=ticket.ticket_id, actor_user_id=env.ids["owner"]))
    assert confirmed.status is TicketStatus.CONFIRMED


def test_an_expired_ticket_is_refused_without_any_sweep(env):  # noqa: ANN001
    ticket = env.run(env.issue(ttl_seconds=-1))
    assert env.run(env.manager.pending_for_user(env.ids["owner"])) == []
    with pytest.raises(ConflictError, match="expired"):
        env.run(env.manager.validate_and_consume(ticket_id=ticket.ticket_id, actor_user_id=env.ids["owner"]))


def test_no_cancels_every_pending_ticket(env):  # noqa: ANN001
    first = env.run(env.issue())
    second = env.run(env.issue(action_name="manage_user"))
    cancelled = env.run(env.manager.cancel_pending_for_user(env.ids["owner"]))
    assert {t.ticket_id for t in cancelled} == {first.ticket_id, second.ticket_id}
    assert env.run(env.manager.pending_for_user(env.ids["owner"])) == []
    with pytest.raises(ConflictError, match="cancelled"):
        env.run(env.manager.validate_and_consume(ticket_id=first.ticket_id, actor_user_id=env.ids["owner"]))


def test_old_tickets_are_removed_when_new_ones_are_issued(env):  # noqa: ANN001
    stale = env.run(env.issue())

    async def age_it() -> None:
        async with env.db.session_factory.begin() as session:
            await session.execute(
                text("UPDATE ai_confirmation_tickets SET expires_at = :t WHERE ticket_id = :id"),
                {"t": datetime.now(UTC) - timedelta(days=2), "id": stale.ticket_id},
            )

    env.run(age_it())
    env.run(env.issue())
    from backend.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        env.run(env.manager.get_ticket(stale.ticket_id))

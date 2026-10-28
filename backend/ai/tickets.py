"""Two-Phase Action Confirmation Tickets (Human-in-the-Loop Safeguards).

A ticket records that a person was shown one specific action -- described by
the server, with its targets bound -- and may now confirm it, once, before it
expires.

**One set of rules, two places to keep them.** `ConfirmationTicketManager`
holds every rule about a ticket (ownership, expiry, single use, parameter
integrity); a `TicketStore` only persists. The application runs on
`DatabaseTicketStore`, configured at startup; `InMemoryTicketStore` is what an
unconfigured process (a unit test, a script) gets.

**Why the database store exists.** Kept in a dictionary, a ticket vanished on
restart, was invisible to any second API process -- so "yes" succeeded or
failed by which process answered -- and could be confirmed twice by two
processes at once. In Postgres each operation runs in its own committed
transaction, so a ticket exists the moment the person is shown it rather than
whenever the chat request's transaction happens to commit, and consuming one
takes a row lock, so two confirmations serialise and the second is refused.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Awaitable, Callable, Protocol

from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.ai.config import get_ai_settings
from backend.ai.security import SecurityError
from backend.core.errors import ConflictError, NotFoundError
from backend.core.logging import get_logger

logger = get_logger(__name__)

# Used and expired tickets are kept this long for anyone investigating what was
# confirmed, then removed opportunistically when new tickets are issued.
_RETENTION = timedelta(days=1)


class TicketStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ConfirmationTicket(BaseModel):
    """An approval ticket for one consequential operation."""

    ticket_id: str
    action_name: str
    actor_user_id: int
    actor_public_id: str
    parameters: dict[str, Any]
    parameters_hash: str
    affected_records_count: int
    preview_summary: str
    created_at: datetime
    expires_at: datetime
    status: TicketStatus = TicketStatus.PENDING
    # True when the registry staged this ticket for a tool call: confirming it
    # re-runs that tool's handler with exactly these parameters.
    via_registry: bool = False

    @property
    def is_expired(self) -> bool:
        return datetime.now(UTC) >= self.expires_at

    @property
    def effective_status(self) -> TicketStatus:
        """EXPIRED is derived from the clock, never written: a ticket must not
        stay valid because nothing happened to sweep it."""
        if self.status is TicketStatus.PENDING and self.is_expired:
            return TicketStatus.EXPIRED
        return self.status


def _compute_parameters_hash(params: dict[str, Any]) -> str:
    """Deterministic SHA-256 of canonical JSON parameters."""
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _check_consumable(
    ticket: ConfirmationTicket,
    *,
    actor_user_id: int,
    provided_parameters: dict[str, Any] | None,
) -> None:
    """Every rule a ticket must pass before it may be used. Raises on failure."""
    if ticket.actor_user_id != actor_user_id:
        logger.warning(
            "Ticket %s ownership mismatch: expected %d, got %d",
            ticket.ticket_id,
            ticket.actor_user_id,
            actor_user_id,
        )
        raise SecurityError("You cannot confirm an action initiated by another user.")

    status = ticket.effective_status
    if status is TicketStatus.EXPIRED:
        raise ConflictError("This confirmation preview has expired. Please initiate the action again.")
    if status is TicketStatus.CONFIRMED:
        raise ConflictError("This action has already been executed.")
    if status is TicketStatus.CANCELLED:
        raise ConflictError("This action was cancelled.")

    if provided_parameters is not None:
        current_hash = _compute_parameters_hash(provided_parameters)
        if current_hash != ticket.parameters_hash:
            logger.error(
                "Parameter tampering detected for ticket %s: original %s != current %s",
                ticket.ticket_id,
                ticket.parameters_hash,
                current_hash,
            )
            raise SecurityError("Action parameters were altered since preview generation.")


TicketCheck = Callable[[ConfirmationTicket], None]


class TicketStore(Protocol):
    """Persistence only. The rules live in ConfirmationTicketManager."""

    async def add(self, ticket: ConfirmationTicket) -> None: ...

    async def get(self, ticket_id: str) -> ConfirmationTicket | None: ...

    async def pending_for_user(self, actor_user_id: int) -> list[ConfirmationTicket]: ...

    async def cancel(self, ticket_ids: list[str]) -> None: ...

    async def consume(self, ticket_id: str, check: TicketCheck) -> ConfirmationTicket:
        """Hold the ticket exclusively, run `check` (which raises to refuse),
        then mark it used. Exclusivity across check and write is the point:
        without it two confirmations can both pass the check."""
        ...


class InMemoryTicketStore:
    """For an unconfigured process: one process, nothing survives a restart."""

    def __init__(self) -> None:
        self._tickets: dict[str, ConfirmationTicket] = {}
        self._lock = asyncio.Lock()

    async def add(self, ticket: ConfirmationTicket) -> None:
        self._tickets[ticket.ticket_id] = ticket.model_copy()

    async def get(self, ticket_id: str) -> ConfirmationTicket | None:
        ticket = self._tickets.get(ticket_id)
        return ticket.model_copy() if ticket is not None else None

    async def pending_for_user(self, actor_user_id: int) -> list[ConfirmationTicket]:
        return [
            t.model_copy()
            for t in self._tickets.values()
            if t.actor_user_id == actor_user_id and t.effective_status is TicketStatus.PENDING
        ]

    async def cancel(self, ticket_ids: list[str]) -> None:
        for tid in ticket_ids:
            ticket = self._tickets.get(tid)
            if ticket is not None and ticket.status is TicketStatus.PENDING:
                ticket.status = TicketStatus.CANCELLED

    async def consume(self, ticket_id: str, check: TicketCheck) -> ConfirmationTicket:
        async with self._lock:
            ticket = self._tickets.get(ticket_id)
            if ticket is None:
                raise NotFoundError(f"Confirmation ticket '{ticket_id}' not found.")
            check(ticket)
            ticket.status = TicketStatus.CONFIRMED
            return ticket.model_copy()


class DatabaseTicketStore:
    """Postgres-backed. Every operation is its own committed transaction."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        # Test seam, None in the application: awaited after a ticket is read
        # inside `consume` and before it is checked. Two confirmations left to
        # the scheduler do not overlap -- the second spends its time getting a
        # connection while the first commits -- so a race test needs a way to
        # hold the first at this point. With the row lock the second can never
        # reach it; without the lock both do, and both would succeed.
        self.after_read: Callable[[], Awaitable[None]] | None = None

    @staticmethod
    def _to_ticket(row: Any) -> ConfirmationTicket:
        return ConfirmationTicket(
            ticket_id=row.ticket_id,
            action_name=row.action_name,
            actor_user_id=row.actor_user_id,
            actor_public_id=row.actor_public_id,
            parameters=dict(row.parameters),
            parameters_hash=row.parameters_hash,
            affected_records_count=row.affected_records_count,
            preview_summary=row.preview_summary,
            created_at=row.created_at,
            expires_at=row.expires_at,
            status=TicketStatus(row.status),
            via_registry=row.via_registry,
        )

    async def add(self, ticket: ConfirmationTicket) -> None:
        from backend.models.ai_ticket import AIConfirmationTicket

        async with self._session_factory.begin() as session:
            # Opportunistic cleanup, bounded by the expiry index. Here because
            # issuing a ticket is the only moment the table grows.
            await session.execute(
                delete(AIConfirmationTicket).where(
                    AIConfirmationTicket.expires_at < datetime.now(UTC) - _RETENTION
                )
            )
            session.add(
                AIConfirmationTicket(
                    ticket_id=ticket.ticket_id,
                    action_name=ticket.action_name,
                    actor_user_id=ticket.actor_user_id,
                    actor_public_id=ticket.actor_public_id,
                    parameters=ticket.parameters,
                    parameters_hash=ticket.parameters_hash,
                    affected_records_count=ticket.affected_records_count,
                    preview_summary=ticket.preview_summary,
                    via_registry=ticket.via_registry,
                    status=TicketStatus.PENDING.value,
                    created_at=ticket.created_at,
                    expires_at=ticket.expires_at,
                )
            )

    async def get(self, ticket_id: str) -> ConfirmationTicket | None:
        from backend.models.ai_ticket import AIConfirmationTicket

        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(AIConfirmationTicket).where(AIConfirmationTicket.ticket_id == ticket_id)
                )
            ).scalar_one_or_none()
            return self._to_ticket(row) if row is not None else None

    async def pending_for_user(self, actor_user_id: int) -> list[ConfirmationTicket]:
        from backend.models.ai_ticket import AIConfirmationTicket

        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(AIConfirmationTicket).where(
                        AIConfirmationTicket.actor_user_id == actor_user_id,
                        AIConfirmationTicket.status == TicketStatus.PENDING.value,
                        AIConfirmationTicket.expires_at > datetime.now(UTC),
                    )
                )
            ).scalars().all()
            return [self._to_ticket(r) for r in rows]

    async def cancel(self, ticket_ids: list[str]) -> None:
        from backend.models.ai_ticket import AIConfirmationTicket

        if not ticket_ids:
            return
        async with self._session_factory.begin() as session:
            await session.execute(
                update(AIConfirmationTicket)
                .where(
                    AIConfirmationTicket.ticket_id.in_(ticket_ids),
                    AIConfirmationTicket.status == TicketStatus.PENDING.value,
                )
                .values(status=TicketStatus.CANCELLED.value)
            )

    async def consume(self, ticket_id: str, check: TicketCheck) -> ConfirmationTicket:
        from backend.models.ai_ticket import AIConfirmationTicket

        async with self._session_factory.begin() as session:
            row = (
                await session.execute(
                    select(AIConfirmationTicket)
                    .where(AIConfirmationTicket.ticket_id == ticket_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is None:
                raise NotFoundError(f"Confirmation ticket '{ticket_id}' not found.")
            if self.after_read is not None:
                await self.after_read()
            ticket = self._to_ticket(row)
            check(ticket)  # raising rolls the transaction back and releases the lock
            row.status = TicketStatus.CONFIRMED.value
            row.consumed_at = datetime.now(UTC)
            ticket.status = TicketStatus.CONFIRMED
            return ticket


class ConfirmationTicketManager:
    """Issues, validates and consumes tickets. Every rule is here."""

    def __init__(self, store: TicketStore | None = None) -> None:
        self.store: TicketStore = store or InMemoryTicketStore()

    async def create_ticket(
        self,
        *,
        action_name: str,
        actor_user_id: int,
        actor_public_id: str,
        parameters: dict[str, Any],
        affected_records_count: int,
        preview_summary: str,
        ttl_seconds: int | None = None,
        via_registry: bool = False,
    ) -> ConfirmationTicket:
        """Issue a new approval ticket."""
        settings = get_ai_settings()
        ttl = ttl_seconds or settings.confirmation_ticket_ttl_seconds
        now = datetime.now(UTC)

        ticket = ConfirmationTicket(
            ticket_id=f"act_{secrets.token_hex(16)}",
            action_name=action_name,
            actor_user_id=actor_user_id,
            actor_public_id=actor_public_id,
            parameters=parameters,
            parameters_hash=_compute_parameters_hash(parameters),
            affected_records_count=affected_records_count,
            preview_summary=preview_summary,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl),
            status=TicketStatus.PENDING,
            via_registry=via_registry,
        )
        await self.store.add(ticket)
        logger.info(
            "Created confirmation ticket %s for action '%s' by user %s (TTL: %ds)",
            ticket.ticket_id,
            action_name,
            actor_public_id,
            ttl,
        )
        return ticket

    async def get_ticket(self, ticket_id: str) -> ConfirmationTicket:
        """Retrieve a ticket, with expiry reflected in its status, or raise NotFoundError."""
        ticket = await self.store.get(ticket_id)
        if ticket is None:
            raise NotFoundError(f"Confirmation ticket '{ticket_id}' not found.")
        ticket.status = ticket.effective_status
        return ticket

    async def pending_for_user(self, actor_user_id: int) -> list[ConfirmationTicket]:
        """Unexpired pending tickets for this person, newest first."""
        tickets = await self.store.pending_for_user(actor_user_id)
        return sorted(tickets, key=lambda t: t.created_at, reverse=True)

    async def cancel_pending_for_user(self, actor_user_id: int) -> list[ConfirmationTicket]:
        """Cancel every pending ticket this person holds.

        All of them, not the latest: "no" must never leave a pending action
        behind for a later "yes" to confirm by accident.
        """
        pending = await self.pending_for_user(actor_user_id)
        await self.store.cancel([t.ticket_id for t in pending])
        for t in pending:
            t.status = TicketStatus.CANCELLED
            logger.info("Cancelled pending confirmation ticket %s for user %d", t.ticket_id, actor_user_id)
        return pending

    async def validate_and_consume(
        self,
        *,
        ticket_id: str,
        actor_user_id: int,
        provided_parameters: dict[str, Any] | None = None,
    ) -> ConfirmationTicket:
        """Validate ownership, expiry and integrity, then consume -- exactly once."""
        ticket = await self.store.consume(
            ticket_id,
            lambda t: _check_consumable(
                t, actor_user_id=actor_user_id, provided_parameters=provided_parameters
            ),
        )
        logger.info("Ticket %s confirmed and consumed for '%s'", ticket_id, ticket.action_name)
        return ticket


_ticket_manager_instance: ConfirmationTicketManager | None = None


def get_ticket_manager() -> ConfirmationTicketManager:
    """The process-wide ticket manager (in-memory until configured at startup)."""
    global _ticket_manager_instance
    if _ticket_manager_instance is None:
        _ticket_manager_instance = ConfirmationTicketManager()
    return _ticket_manager_instance


def configure_ticket_store(store: TicketStore) -> None:
    """Point the process-wide manager at `store`. Called once, at startup."""
    get_ticket_manager().store = store

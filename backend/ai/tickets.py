"""Two-Phase Action Confirmation Ticket Engine (Human-in-the-Loop Safeguards).

Prevents autonomous execution of high-risk or irreversible state mutations.
Generates cryptographically fingerprinted preview tickets that require explicit
operator confirmation within a strict time-to-live (TTL).
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field

from backend.ai.config import get_ai_settings
from backend.ai.security import AISecurityError, SecurityError
from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.core.logging import get_logger

logger = get_logger(__name__)


class TicketStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ConfirmationTicket(BaseModel):
    """Ephemeral approval ticket for high-risk operations."""

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

    @property
    def is_expired(self) -> bool:
        return datetime.now(UTC) >= self.expires_at


def _compute_parameters_hash(params: dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash of canonical JSON parameters."""
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ConfirmationTicketManager:
    """Manages generation, storage, and validation of action approval tickets."""

    def __init__(self) -> None:
        self._tickets: dict[str, ConfirmationTicket] = {}

    def create_ticket(
        self,
        *,
        action_name: str,
        actor_user_id: int,
        actor_public_id: str,
        parameters: dict[str, Any],
        affected_records_count: int,
        preview_summary: str,
        ttl_seconds: int | None = None,
    ) -> ConfirmationTicket:
        """Issue a new ephemeral approval ticket."""
        settings = get_ai_settings()
        ttl = ttl_seconds or settings.confirmation_ticket_ttl_seconds
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl)

        ticket_id = f"act_{secrets.token_hex(16)}"
        param_hash = _compute_parameters_hash(parameters)

        ticket = ConfirmationTicket(
            ticket_id=ticket_id,
            action_name=action_name,
            actor_user_id=actor_user_id,
            actor_public_id=actor_public_id,
            parameters=parameters,
            parameters_hash=param_hash,
            affected_records_count=affected_records_count,
            preview_summary=preview_summary,
            created_at=now,
            expires_at=expires_at,
            status=TicketStatus.PENDING,
        )

        self._tickets[ticket_id] = ticket
        logger.info(
            "Created confirmation ticket %s for action '%s' by user %s (TTL: %ds)",
            ticket_id,
            action_name,
            actor_public_id,
            ttl,
        )
        return ticket

    def get_ticket(self, ticket_id: str) -> ConfirmationTicket:
        """Retrieve ticket by ID or raise NotFoundError."""
        ticket = self._tickets.get(ticket_id)
        if not ticket:
            raise NotFoundError(f"Confirmation ticket '{ticket_id}' not found.")
        if ticket.status == TicketStatus.PENDING and ticket.is_expired:
            ticket.status = TicketStatus.EXPIRED
        return ticket

    def get_latest_pending_for_user(self, actor_user_id: int) -> ConfirmationTicket | None:
        """Find the most recent non-expired pending ticket for this user."""
        candidates = [
            t for t in self._tickets.values()
            if t.actor_user_id == actor_user_id and t.status == TicketStatus.PENDING and not t.is_expired
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda t: t.created_at, reverse=True)
        return candidates[0]

    def cancel_pending_for_user(self, actor_user_id: int) -> ConfirmationTicket | None:
        """Cancel the latest pending ticket for this user."""
        ticket = self.get_latest_pending_for_user(actor_user_id)
        if ticket:
            ticket.status = TicketStatus.CANCELLED
            logger.info("Cancelled pending confirmation ticket %s for user %d", ticket.ticket_id, actor_user_id)
            return ticket
        return None

    def validate_and_consume(
        self,
        *,
        ticket_id: str,
        actor_user_id: int,
        provided_parameters: dict[str, Any] | None = None,
    ) -> ConfirmationTicket:
        """Validate ticket ownership, expiration, and parameter integrity, then consume it."""
        ticket = self.get_ticket(ticket_id)

        # 1. Verify ownership
        if ticket.actor_user_id != actor_user_id:
            logger.warning(
                "Ticket %s ownership mismatch: expected %d, got %d",
                ticket_id,
                ticket.actor_user_id,
                actor_user_id,
            )
            raise SecurityError("You cannot confirm an action initiated by another user.")

        # 2. Verify state
        if ticket.status == TicketStatus.EXPIRED or ticket.is_expired:
            ticket.status = TicketStatus.EXPIRED
            raise ConflictError("This confirmation preview has expired. Please initiate the action again.")

        if ticket.status == TicketStatus.CONFIRMED:
            raise ConflictError("This action has already been executed.")

        if ticket.status == TicketStatus.CANCELLED:
            raise ConflictError("This action was cancelled.")

        # 3. Verify parameter integrity if provided
        if provided_parameters is not None:
            current_hash = _compute_parameters_hash(provided_parameters)
            if current_hash != ticket.parameters_hash:
                logger.error(
                    "Parameter tampering detected for ticket %s: original %s != current %s",
                    ticket_id,
                    ticket.parameters_hash,
                    current_hash,
                )
                raise SecurityError("Action parameters were altered since preview generation.")

        # 4. Mark as confirmed
        ticket.status = TicketStatus.CONFIRMED
        logger.info(
            "Ticket %s successfully confirmed and consumed for '%s'",
            ticket_id,
            ticket.action_name,
        )
        return ticket


_ticket_manager_instance: ConfirmationTicketManager | None = None


def get_ticket_manager() -> ConfirmationTicketManager:
    """Return singleton instance of ConfirmationTicketManager."""
    global _ticket_manager_instance
    if _ticket_manager_instance is None:
        _ticket_manager_instance = ConfirmationTicketManager()
    return _ticket_manager_instance

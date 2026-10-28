"""Unit tests for Two-Phase Confirmation Ticket Engine."""

import asyncio

import pytest
from datetime import UTC, datetime, timedelta

from backend.ai.security import SecurityError
from backend.ai.tickets import (
    ConfirmationTicketManager,
    TicketStatus,
)
from backend.core.errors import ConflictError, NotFoundError


def test_create_and_validate_ticket_success():
    manager = ConfirmationTicketManager()
    ticket = asyncio.run(manager.create_ticket(
        action_name="publish_assessment",
        actor_user_id=10,
        actor_public_id="user-10-uuid",
        parameters={"assessment_id": "quiz-123", "target_batch": "11234"},
        affected_records_count=24,
        preview_summary="Publish quiz to 24 students in batch 11234",
    ))

    assert ticket.ticket_id.startswith("act_")
    assert ticket.status == TicketStatus.PENDING
    assert not ticket.is_expired
    assert len(ticket.parameters_hash) == 64

    # Validate and consume
    consumed = asyncio.run(manager.validate_and_consume(
        ticket_id=ticket.ticket_id,
        actor_user_id=10,
        provided_parameters={"assessment_id": "quiz-123", "target_batch": "11234"},
    ))
    assert consumed.status == TicketStatus.CONFIRMED

    # Consuming again raises ConflictError
    with pytest.raises(ConflictError):
        asyncio.run(manager.validate_and_consume(
            ticket_id=ticket.ticket_id,
            actor_user_id=10,
        ))


def test_parameter_tampering_detected():
    manager = ConfirmationTicketManager()
    ticket = asyncio.run(manager.create_ticket(
        action_name="publish_assessment",
        actor_user_id=10,
        actor_public_id="user-10-uuid",
        parameters={"assessment_id": "quiz-123", "target_batch": "11234"},
        affected_records_count=24,
        preview_summary="Publish quiz to 24 students",
    ))

    tampered_params = {"assessment_id": "quiz-123", "target_batch": "99999"}  # Altered!
    with pytest.raises(SecurityError) as exc_info:
        asyncio.run(manager.validate_and_consume(
            ticket_id=ticket.ticket_id,
            actor_user_id=10,
            provided_parameters=tampered_params,
        ))
    assert "altered" in str(exc_info.value).lower()


def test_ownership_mismatch_rejected():
    manager = ConfirmationTicketManager()
    ticket = asyncio.run(manager.create_ticket(
        action_name="delete_batch",
        actor_user_id=10,
        actor_public_id="user-10-uuid",
        parameters={"batch_id": "b-123"},
        affected_records_count=1,
        preview_summary="Delete batch",
    ))

    # User 99 tries to confirm user 10's action
    with pytest.raises(SecurityError) as exc_info:
        asyncio.run(manager.validate_and_consume(
            ticket_id=ticket.ticket_id,
            actor_user_id=99,
        ))
    assert "another user" in str(exc_info.value).lower()


def test_expired_ticket_rejected():
    manager = ConfirmationTicketManager()
    # TTL of -1 second (already expired)
    ticket = asyncio.run(manager.create_ticket(
        action_name="publish_assessment",
        actor_user_id=10,
        actor_public_id="user-10-uuid",
        parameters={"assessment_id": "quiz-123"},
        affected_records_count=10,
        preview_summary="Publish",
        ttl_seconds=-1,
    ))
    assert ticket.is_expired

    with pytest.raises(ConflictError) as exc_info:
        asyncio.run(manager.validate_and_consume(
            ticket_id=ticket.ticket_id,
            actor_user_id=10,
        ))
    assert "expired" in str(exc_info.value).lower()


def test_nonexistent_ticket_raises_not_found():
    manager = ConfirmationTicketManager()
    with pytest.raises(NotFoundError):
        asyncio.run(manager.get_ticket("act_nonexistent_12345"))

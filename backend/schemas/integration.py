"""Integration schemas (spec §25)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import Field

from backend.schemas.base import APIModel, RequestModel

WebhookName = Annotated[str, Field(min_length=2, max_length=120)]


class WebhookEndpointResponse(APIModel):
    public_id: uuid.UUID
    name: str
    target_url: str
    events: list[str]
    is_active: bool = True
    description: str | None = None
    failure_count: int = 0
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_failure_reason: str | None = None
    created_at: datetime | None = None
    # Deliberately no `secret` field. A response model that merely declines
    # to populate one is a single careless edit from leaking it; a model with
    # no such field cannot.


class WebhookCreatedResponse(WebhookEndpointResponse):
    """The only response that carries the secret, and only at creation.

    Separated into its own model so the secret cannot be returned by any
    other route by accident — a shared model with an optional field would
    make that a one-line mistake.
    """

    secret: str = Field(
        description="Shown once. Store it now; it is never returned again."
    )
    signature_docs: str = Field(
        default=(
            "Each delivery carries X-LMS-Timestamp and X-LMS-Signature "
            "(sha256=hex of HMAC-SHA256 over b'{timestamp}.' + raw body). "
            "Reject deliveries older than 300 seconds, and compare "
            "signatures in constant time."
        )
    )


class CreateWebhookRequest(RequestModel):
    name: WebhookName
    target_url: Annotated[str, Field(min_length=8, max_length=500)]
    events: list[str] = Field(
        min_length=1,
        max_length=50,
        description="Event codes from /integrations/webhooks/events.",
    )
    description: Annotated[str | None, Field(max_length=255)] = None


class UpdateWebhookRequest(RequestModel):
    name: WebhookName | None = None
    target_url: Annotated[str | None, Field(min_length=8, max_length=500)] = None
    events: Annotated[list[str] | None, Field(max_length=50)] = None
    description: Annotated[str | None, Field(max_length=255)] = None
    is_active: bool | None = None


class RotateSecretResponse(APIModel):
    public_id: uuid.UUID
    secret: str = Field(description="The new secret. The previous one stops working now.")


class WebhookEventCatalogResponse(APIModel):
    events: list[str]
    note: str = Field(
        default=(
            "Event codes mirror the notification catalogue, so anything the "
            "platform can tell a person about it can also tell a system about."
        )
    )


class WebhookDeliveryResponse(APIModel):
    public_id: uuid.UUID
    event: str
    status: str
    attempts: int = 0
    response_status: int | None = None
    error: str | None = None
    created_at: datetime | None = None
    delivered_at: datetime | None = None
    next_attempt_at: datetime | None = None
    payload: dict[str, Any] | None = None


class TestDeliveryResponse(APIModel):
    delivered: bool
    response_status: int | None = None
    error: str | None = None
    delivery_id: uuid.UUID


# =============================================================================
# CALENDAR FEEDS
# =============================================================================


class CalendarFeedResponse(APIModel):
    public_id: uuid.UUID
    name: str
    is_active: bool = True
    created_at: datetime | None = None
    last_accessed_at: datetime | None = None
    access_count: int = 0


class CalendarFeedCreatedResponse(CalendarFeedResponse):
    url: str = Field(
        description="Shown once. Anyone holding this link can read the timetable."
    )
    warning: str = Field(
        default=(
            "This link is the credential — calendar clients cannot send an "
            "Authorization header. Share it only with your own calendar, and "
            "revoke it if it leaks."
        )
    )


class CreateCalendarFeedRequest(RequestModel):
    name: Annotated[str, Field(min_length=2, max_length=120)] = "My timetable"

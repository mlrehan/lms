"""Web Push registration (spec §21's PUSH channel, made real)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field

from backend.schemas.base import APIModel, RequestModel


class PushKeyResponse(APIModel):
    """What a browser needs before it can subscribe at all."""

    enabled: bool = Field(description="False when this deployment has no VAPID keys configured.")
    public_key: str | None = Field(
        default=None,
        description=(
            "The VAPID application server key, passed to pushManager.subscribe. "
            "Public by design -- it identifies this deployment to a push service "
            "and authorises nothing."
        ),
    )


class PushSubscribeRequest(RequestModel):
    """Exactly what `PushSubscription.toJSON()` produces in the browser."""

    endpoint: Annotated[str, Field(min_length=20, max_length=2048)]
    p256dh: Annotated[str, Field(min_length=16, max_length=255)]
    auth: Annotated[str, Field(min_length=8, max_length=255)]


class PushUnsubscribeRequest(RequestModel):
    endpoint: Annotated[str, Field(min_length=20, max_length=2048)]


class PushDeviceResponse(APIModel):
    public_id: str
    user_agent: str | None = None
    created_at: datetime
    last_used_at: datetime | None = None

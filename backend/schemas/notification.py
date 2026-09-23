"""Notification preference schemas (spec §21)."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from backend.schemas.base import APIModel, RequestModel


class NotificationPreferenceResponse(APIModel):
    type: str
    category: str
    description: str
    enabled: bool
    mandatory: bool = Field(
        default=False,
        description="Security notices cannot be switched off; the toggle is shown locked.",
    )


class NotificationPreferencesResponse(APIModel):
    categories: list[str] = Field(description="Display order for grouping.")
    preferences: list[NotificationPreferenceResponse]
    channels_note: str = Field(
        default=(
            "These switches decide what is worth telling you at all. Anything "
            "left on arrives in the app, and on any device you have turned on "
            "above. Email and SMS are modelled but have no transport, so there "
            "is no per-channel setting for them."
        ),
        description=(
            "Stated rather than implied, so nobody expects an email. Rewritten "
            "when Web Push gained a real transport: the previous wording said "
            "push was modelled and undeliverable, which had stopped being true "
            "and is the worst kind of note -- one that stops the reader checking."
        ),
    )


class SetNotificationPreferenceRequest(RequestModel):
    enabled: bool


class PreferenceResetResponse(APIModel):
    cleared: int

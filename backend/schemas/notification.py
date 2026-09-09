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
            "Only in-app notifications are delivered. Email, SMS and push are "
            "modelled but have no transport, so no per-channel setting is offered."
        ),
        description="Stated rather than implied, so nobody expects an email.",
    )


class SetNotificationPreferenceRequest(RequestModel):
    enabled: bool


class PreferenceResetResponse(APIModel):
    cleared: int

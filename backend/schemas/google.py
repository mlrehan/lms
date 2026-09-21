"""Google Calendar integration schemas.

Nothing here can carry a token or the client secret: the status is built from explicit fields,
not from the connection row, so adding a column to the table can never leak through it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from backend.schemas.base import APIModel, RequestModel


class GoogleStatusResponse(APIModel):
    configured: bool = Field(description="GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are set.")
    problem: str | None = Field(default=None, description="Why sign-in cannot work yet, if it cannot.")
    connected: bool
    account_email: str | None = None
    connected_at: datetime | None = None
    expected_email: str | None = Field(default=None, description="The account a Super Admin must sign in as.")
    redirect_uri: str = Field(description="Must be an Authorized redirect URI on the OAuth client in Google Cloud.")
    invite_attendees: bool
    send_updates: str
    share_with_admins: bool
    pull_session_times: bool
    calendars: int = Field(description="Batches that currently have a Google calendar.")
    pending_changes: int = Field(default=0, description="Enrolment changes made in Google that are waiting for a decision.")
    admins_can_edit: bool = False


class GoogleConnectResponse(APIModel):
    url: str = Field(description="Send the browser here to sign in with Google.")


class GoogleCallbackRequest(RequestModel):
    code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=1, max_length=2048)


class GoogleBatchResponse(APIModel):
    batch_id: uuid.UUID
    has_calendar: bool
    calendar_url: str | None = None
    last_synced_at: datetime | None = None
    sessions: int
    sessions_in_google: int


class GoogleChangeRequestResponse(APIModel):
    public_id: uuid.UUID
    kind: str = Field(description="ENROL_ADD or ENROL_REMOVE")
    status: str = Field(description="PENDING, APPROVED, REJECTED or SUPERSEDED")
    email: str | None = None
    student_name: str | None = None
    batch_id: uuid.UUID
    batch_code: str
    note: str | None = None
    detected_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None
    last_error: str | None = Field(default=None, description="Why an approval was refused, when it was.")

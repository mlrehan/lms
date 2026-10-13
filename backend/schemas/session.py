"""Class session schemas (spec §8)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from backend.core.video_links import VideoLinkError, validate_video_url
from backend.schemas.base import APIModel, RequestModel
from backend.utils.enums import Platforms


_LINK_NOTE = (
    "Only populated for callers who may edit the session (tutors and "
    "administrators). Everyone else joins through POST /sessions/{id}/join, "
    "which is what makes the join window enforceable rather than cosmetic."
)


class JoinFields(APIModel):
    """What any caller may know about joining, without being given the link."""

    join_opens_at: datetime | None = Field(
        default=None, description="Thirty minutes before the start."
    )
    join_closes_at: datetime | None = Field(default=None, description="The session's end.")
    can_join_now: bool = Field(
        default=False,
        description=(
            "True when this caller could join at this moment. The API re-checks "
            "on join; this only decides whether the button is live."
        ),
    )
    has_recording: bool = Field(
        default=False,
        description=(
            "True when this caller has a recording to watch -- either one "
            "stored in the LMS or one on the provider that the session page "
            "can frame."
        ),
    )


class SessionSummary(JoinFields):
    """The timetable row. Carries the join *state* but never the link: this is
    the list a student actually looks at, so it is the list where a link would
    have done the most damage."""

    public_id: uuid.UUID
    session_start_time: datetime | None = None
    session_end_time: datetime | None = None
    duration_minutes: int | None = None
    platform: Platforms
    classroom: str | None = None


class SessionResponse(SessionSummary, JoinFields):
    batch_id: uuid.UUID
    batch_code: str | None = None
    course_title: str | None = None
    tutor_id: uuid.UUID
    tutor_username: str | None = None
    meeting_link: str | None = Field(default=None, description=_LINK_NOTE)
    recording_link: str | None = Field(default=None, description=_LINK_NOTE)
    can_manage: bool = Field(
        default=False, description="True when this caller may edit the session."
    )
    tutor_notes: str | None = None
    student_notes: str | None = None
    attendance_recorded: bool = Field(
        default=False, description="True once a register has been marked for this session."
    )


class _SessionTimes(RequestModel):
    @model_validator(mode="after")
    def _end_after_start(self):  # type: ignore[no-untyped-def]
        start = getattr(self, "session_start_time", None)
        end = getattr(self, "session_end_time", None)
        if start and end and end <= start:
            raise ValueError("session_end_time must be after session_start_time")
        return self


class SessionCreateRequest(_SessionTimes):
    tutor_id: uuid.UUID = Field(
        description=(
            "The tutor taking this session. Assigning one grants them access to "
            "the batch's students, so it must be a user holding the TUTOR role."
        )
    )
    session_start_time: datetime
    session_end_time: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    platform: Platforms = Platforms.Zoom
    classroom: Annotated[str | None, Field(max_length=255)] = None
    meeting_link: Annotated[str | None, Field(max_length=2048)] = None
    tutor_notes: str | None = None

    # Same reason as on the update schema: the link reaches an href.
    @field_validator("meeting_link")
    @classmethod
    def _safe_link(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        try:
            return validate_video_url(value)
        except VideoLinkError as exc:
            raise ValueError(str(exc)) from None


class SessionUpdateRequest(_SessionTimes):
    tutor_id: uuid.UUID | None = None
    session_start_time: datetime | None = None
    session_end_time: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    platform: Platforms | None = None
    classroom: Annotated[str | None, Field(max_length=255)] = None
    meeting_link: Annotated[str | None, Field(max_length=2048)] = None
    recording_link: Annotated[str | None, Field(max_length=2048)] = None
    tutor_notes: str | None = None
    student_notes: str | None = None

    # A meeting or recording link is written into an `href` and an `iframe
    # src`. `javascript:` and `data:` there execute in the page, and both were
    # accepted and stored until this check existed -- as was "not-a-url",
    # which simply produced a dead player nobody could diagnose.
    @field_validator("meeting_link", "recording_link")
    @classmethod
    def _safe_link(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        try:
            return validate_video_url(value)
        except VideoLinkError as exc:
            raise ValueError(str(exc)) from None


class CalendarSession(APIModel):
    """One block on the calendar: enough to draw and filter it without a request per session."""

    public_id: uuid.UUID
    batch_id: uuid.UUID
    batch_code: str
    course_title: str | None = None
    tutor_id: uuid.UUID
    tutor_name: str | None = None
    session_start_time: datetime
    session_end_time: datetime = Field(description="Start plus duration (an hour if neither is stored) when no end was saved.")
    platform: Platforms
    classroom: str | None = None
    meeting_link: str | None = Field(default=None, description=_LINK_NOTE)
    can_join_now: bool = False
    origin: str | None = None


class CalendarResponse(APIModel):
    items: list[CalendarSession]
    truncated: bool = Field(description="True when the window held more sessions than the cap; narrow it.")


class OverviewPerson(APIModel):
    public_id: uuid.UUID
    name: str
    email: str | None = Field(default=None, description="Only for administrators and the batch's tutors.")
    phone: str | None = None
    detail: str | None = Field(default=None, description="A guardian's relationship, or a manager's job title.")


class OverviewRosterEntry(APIModel):
    student: OverviewPerson
    enrollment_status: str
    attendance: str | None = None
    organization: str | None = None
    guardians: list[OverviewPerson] = []
    managers: list[OverviewPerson] = []


class OverviewCourse(APIModel):
    public_id: uuid.UUID
    title: str
    code: str | None = None
    level: str | None = None


class OverviewBatch(APIModel):
    public_id: uuid.UUID
    batch_code: str
    capacity: int | None = None
    enrolled: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_active: bool


class SessionOverview(JoinFields):
    public_id: uuid.UUID
    number: int
    total: int
    session_start_time: datetime
    session_end_time: datetime | None = None
    duration_minutes: int | None = None
    platform: Platforms
    classroom: str | None = None
    meeting_link: str | None = Field(default=None, description=_LINK_NOTE)
    recording_link: str | None = Field(default=None, description=_LINK_NOTE)
    can_manage: bool = False
    student_notes: str | None = None
    tutor_notes: str | None = None
    origin: str | None = None
    in_google: bool
    course: OverviewCourse
    batch: OverviewBatch
    tutor: OverviewPerson
    roster: list[OverviewRosterEntry]
    roster_is_partial: bool = Field(description="True when the caller sees only their own people, not the whole batch.")
    attendance_counts: dict[str, int]
    can_see_contacts: bool


class SessionJoinResponse(APIModel):
    """One admission to one class.

    Returned by a POST rather than a GET on purpose: handing out a meeting link
    is an act that is recorded, not a property of the session that a cache or a
    prefetch may repeat on the caller's behalf.
    """

    meeting_link: str
    platform: Platforms
    classroom: str | None = None
    session_start_time: datetime
    session_end_time: datetime | None = None
    join_opens_at: datetime
    join_closes_at: datetime
    joined_outside_window: bool = Field(
        description=(
            "True when the window was shut and the caller's session.override "
            "opened it. Shown back to them, and audited."
        )
    )


class SessionRecordingResponse(APIModel):
    """Where to play a recording, never where to download one."""

    playback_url: str | None = Field(
        default=None,
        description=(
            "Relative to the API root (the same base every other call uses), "
            "so a browser that reaches this API through a proxy composes it the "
            "same way it composes everything else. Streams the recording after "
            "re-checking permission on every request, including every seek. "
            "Present only for recordings stored in the LMS."
        ),
    )
    embed_url: str | None = Field(
        default=None,
        description=(
            "Relative to the API root, like `playback_url`. Frame this to "
            "watch a recording that lives on the provider: the path re-checks "
            "permission on every request and then redirects to the player. "
            "Present only when there is no recording stored in the LMS -- a "
            "stored one plays in our own player and wins."
        ),
    )
    external_url: str | None = Field(
        default=None,
        description=(
            "The provider's own link. Only ever given to callers who may edit "
            "the session -- it is a link out of the LMS and past its checks."
        ),
    )
    name: str | None = None
    mime_type: str | None = None
    size: int | None = None


class SessionRecordingAttachRequest(RequestModel):
    resource_id: uuid.UUID = Field(
        description="A file already in the library. The caller needs EDIT on it."
    )

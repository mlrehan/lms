"""User request/response schemas (spec §4)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated
from zoneinfo import available_timezones

from pydantic import EmailStr, Field, field_serializer, field_validator

from backend.core.privacy import may_see_contact
from backend.schemas.auth import Password
from backend.schemas.base import APIModel, RequestModel
from backend.utils.enums import Genders, UserStatus

Username = Annotated[str, Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9._-]+$")]

# Computed once at import time from the stdlib's own IANA database -- the
# same source `bootstrap/seeders/geo.py` seeds `time_zones` from, so this
# check and the seeded table can never disagree. Validating here rather than
# with a DB round trip: this is a pure function of a fixed, already-loaded
# set, and a Pydantic field validator is synchronous.
_VALID_TIMEZONES = available_timezones()


class LocationRef(APIModel):
    """A minimal reference to a Country or City, embedded in a user's
    profile. The full geo record (population, coordinates, ...) belongs to
    `GET /geo/...`, not to every user response that mentions one."""

    public_id: uuid.UUID
    name: str


class UserSummary(APIModel):
    """The shape used in lists and when a user is referenced from another
    resource. Deliberately narrow: a roster of 10,000 students should not
    ship everyone's address and emergency contact to render a table."""

    public_id: uuid.UUID
    username: str
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    full_name: str
    status: UserStatus
    profile_picture: str | None = Field(
        default=None,
        validation_alias="profile_picture_url",
        description="API path of the picture (fetch with the same credentials); null when none is set.",
    )
    can_login: bool = True
    is_synced: bool = False

    # Contact details are for the person themselves and the Super Admin only (see `core/privacy.py`). A login name
    # is often the email address, so it is withheld the same way and replaced by the full name.
    #
    # Field serializers, not a model-level one: a model serializer collapses the OpenAPI schema to an untyped
    # object and the generated client types with it.
    @field_serializer("email")
    def _email_for_viewer(self, value: str | None) -> str | None:
        return value if may_see_contact(self.public_id) else None

    @field_serializer("username")
    def _username_for_viewer(self, value: str) -> str:
        return value if may_see_contact(self.public_id) else self.full_name


class UserResponse(UserSummary):
    """The full profile, returned for a single-user read."""


    external_student_id: int | None = None
    external_tutor_id: int | None = None

    title: str | None = None
    gender: Genders
    date_of_birth: date | None = None
    phone_number: str | None = None
    mobile: str | None = None
    designation: str | None = None
    web: str | None = None
    company: str | None = None
    address: str | None = None
    postcode: str | None = None
    timezone: str | None = None
    country: LocationRef | None = None
    city: LocationRef | None = Field(default=None, validation_alias="current_city")
    bio: str | None = None
    is_public: bool

    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    emergency_contact_relationship: str | None = None

    is_locked: bool
    last_login: datetime | None = None
    created_at: datetime

    roles: list[str] = Field(default_factory=list, description="Role names held by this user.")

    @field_serializer("phone_number", "mobile", "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relationship")
    def _contact_for_viewer(self, value: str | None) -> str | None:
        return value if may_see_contact(self.public_id) else None

    @field_validator("roles", mode="before")
    @classmethod
    def _role_names(cls, value: object) -> object:
        """Accept the ORM's `list[Role]` as well as a plain `list[str]`.

        Lets a router return the ORM object straight to
        `UserResponse.model_validate(user)` without hand-copying fields --
        the hand-copied version is where a newly added column silently fails
        to appear in the API.
        """
        if isinstance(value, list):
            return [item if isinstance(item, str) else getattr(item, "name", str(item)) for item in value]
        return value


class CurrentUserResponse(UserResponse):
    """`/auth/me`. Carries the caller's resolved permission set so a client
    can render its navigation without guessing which role implies what --
    the server stays the only authority on what is actually allowed."""

    permissions: list[str] = Field(default_factory=list)

    # Where the sign-in address says they are (see `services/locale_service.py`). Informational: a person's own
    # location, shown to them so a time zone that changed by itself can be explained.
    detected_timezone: str | None = None
    locale_city: str | None = None
    locale_country: str | None = None
    timezone_is_auto: bool = False


class LocaleRefreshResponse(APIModel):
    ip_changed: bool
    timezone_changed: bool
    timezone: str | None = None
    detected_timezone: str | None = None
    city: str | None = None
    country: str | None = None


class UserCreateRequest(RequestModel):
    username: Username
    email: EmailStr
    password: Password
    first_name: str | None = Field(default=None, max_length=50)
    last_name: str | None = Field(default=None, max_length=50)
    title: str | None = Field(default=None, max_length=20)
    gender: Genders = Genders.MALE
    date_of_birth: date | None = None
    phone_number: str | None = Field(default=None, max_length=75)
    mobile: str | None = Field(default=None, max_length=75)
    can_login: bool = Field(
        default=True,
        description="An administrator who types in a password is vouching for the "
        "account, so a manually created user can sign in. Synced accounts are the "
        "opposite: they start disabled.",
    )
    roles: list[str] = Field(
        default_factory=list,
        description="Role names to grant. Must already exist in the role catalog.",
    )


class UserUpdateRequest(RequestModel):
    """Every field optional: this is a PATCH. A field omitted is left alone;
    a field sent as `null` is explicitly cleared."""

    email: EmailStr | None = None
    first_name: str | None = Field(default=None, max_length=50)
    last_name: str | None = Field(default=None, max_length=50)
    title: str | None = Field(default=None, max_length=20)
    gender: Genders | None = None
    date_of_birth: date | None = None
    phone_number: str | None = Field(default=None, max_length=75)
    mobile: str | None = Field(default=None, max_length=75)
    designation: str | None = Field(default=None, max_length=100)
    web: str | None = Field(default=None, max_length=255)
    company: str | None = Field(default=None, max_length=255)
    address: str | None = None
    postcode: str | None = Field(default=None, max_length=35)
    timezone: str | None = Field(default=None, max_length=30)
    country_id: uuid.UUID | None = Field(
        default=None, description="A country's public_id, from GET /geo/countries."
    )
    city_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "A city's public_id, from GET /geo/countries/{id}/cities. If set, "
            "must belong to country_id when both are given in the same "
            "request -- otherwise the city's own country is used."
        ),
    )
    bio: str | None = None
    is_public: bool | None = None
    emergency_contact_name: str | None = Field(default=None, max_length=150)
    emergency_contact_phone: str | None = Field(default=None, max_length=75)
    emergency_contact_relationship: str | None = Field(default=None, max_length=50)

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str | None) -> str | None:
        if value is not None and value not in _VALID_TIMEZONES:
            raise ValueError(f"{value!r} is not a recognized IANA timezone name.")
        return value


class UserStatusRequest(RequestModel):
    status: UserStatus


class UserRolesRequest(RequestModel):
    roles: list[str] = Field(description="The complete set of role names this user should hold.")


class AdminSetPasswordRequest(RequestModel):
    """An administrator resetting someone else's password. Distinct from
    `ChangePasswordRequest`, which requires the *current* password because
    the caller is acting on their own account."""

    new_password: Password


class UserLoginAccessRequest(RequestModel):
    can_login: bool


class UserLoginAccessResponse(APIModel):
    can_login: bool
    default_password_in_use: bool = Field(
        description="True while the account still has the shared default password "
        "-- enabling login then hands the account to anyone who knows it."
    )


class SyncRunResponse(APIModel):
    public_id: uuid.UUID
    kind: str = "USERS"
    trigger_type: str
    dry_run: bool
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    stats: dict | None = None
    errors: list[dict] | None = None
    failure_reason: str | None = None

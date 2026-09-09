"""Authentication request/response schemas (spec §3)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field

from backend.schemas.base import APIModel, RequestModel

# NIST SP 800-63B: length is the property that matters; composition rules
# ("must contain a symbol") mostly produce `Password1!` and are dropped here.
# The upper bound is not cosmetic -- Argon2 is deliberately slow, so an
# unbounded password field is a CPU exhaustion vector on an unauthenticated
# endpoint.
Password = Annotated[str, Field(min_length=12, max_length=128)]


class LoginRequest(RequestModel):
    """Spec §3 allows signing in with either an email or a username, so this
    is one field that accepts both rather than two mutually-exclusive ones."""

    identifier: Annotated[str, Field(min_length=1, max_length=255, description="Email address or username.")]
    password: Annotated[str, Field(min_length=1, max_length=128)]
    remember_me: bool = Field(
        default=False,
        description="Issues a longer-lived refresh token (spec §3 'Remember me').",
    )


class RefreshRequest(RequestModel):
    refresh_token: Annotated[str, Field(min_length=1, max_length=500)]


class LogoutRequest(RequestModel):
    refresh_token: Annotated[str, Field(min_length=1, max_length=500)]


class ChangePasswordRequest(RequestModel):
    current_password: Annotated[str, Field(min_length=1, max_length=128)]
    new_password: Password


class TokenResponse(APIModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds.")


class SessionResponse(APIModel):
    """One active refresh-token session -- spec §3's 'Session management',
    i.e. 'which devices am I signed in on, and can I end one?'"""

    public_id: uuid.UUID
    created_at: datetime
    expires_at: datetime
    user_agent: str | None = None
    ip_address: str | None = None
    is_current: bool = Field(default=False, description="True for the session making this request.")

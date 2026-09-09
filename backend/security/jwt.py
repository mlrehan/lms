"""Access-token issuing and verification.

Two token types, deliberately built from different primitives:

* **Access token** -- a signed, short-lived (15 min) JWT. Stateless: verified
  from its signature alone, so the hot path costs no database round-trip for
  *authenticity*. It carries only an identifier and token type; roles and
  permissions are resolved per-request from the database instead of being
  baked into the token, so revoking a role takes effect on the next request
  rather than whenever the token happens to expire.

* **Refresh token** -- see :mod:`backend.security.refresh_tokens`. Opaque
  random bytes, not a JWT, stored hashed and rotated on every use.

The `sub` claim is the user's `public_id` (a UUID), never the integer primary
key -- the same reason the API never exposes integer ids in URLs: they are
enumerable, and a token is one of the easiest places to leak one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

import jwt
from jwt import InvalidTokenError

from backend.core.config import SecuritySettings
from backend.core.errors import AuthenticationError

TokenPurpose = Literal["access"]

_CLAIM_TYPE: Final = "typ"


class AccessTokenClaims:
    """The verified contents of an access token."""

    __slots__ = ("subject", "jti", "issued_at", "expires_at")

    def __init__(
        self,
        *,
        subject: uuid.UUID,
        jti: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> None:
        self.subject = subject
        self.jti = jti
        self.issued_at = issued_at
        self.expires_at = expires_at


class JWTService:
    """Issues and verifies access tokens under one set of settings."""

    def __init__(self, settings: SecuritySettings) -> None:
        secret = settings.jwt_secret.get_secret_value()
        if not secret:
            # Refusing here rather than issuing unsigned/weakly-signed tokens:
            # a service that "works" without a configured signing key is
            # issuing forgeable credentials.
            raise RuntimeError("SECURITY_JWT_SECRET is not configured.")

        self._secret = secret
        self._algorithm = settings.jwt_algorithm
        self._issuer = settings.jwt_issuer
        self._audience = settings.jwt_audience
        self._access_ttl = timedelta(seconds=settings.access_token_ttl_seconds)

    @property
    def access_ttl_seconds(self) -> int:
        return int(self._access_ttl.total_seconds())

    def create_access_token(self, *, subject: uuid.UUID) -> str:
        now = datetime.now(UTC)
        payload: dict[str, Any] = {
            "sub": str(subject),
            "jti": uuid.uuid4().hex,
            "iat": now,
            "exp": now + self._access_ttl,
            "iss": self._issuer,
            "aud": self._audience,
            _CLAIM_TYPE: "access",
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def verify_access_token(self, token: str) -> AccessTokenClaims:
        """Return the token's claims, or raise :class:`AuthenticationError`.

        Every failure mode -- bad signature, expiry, wrong issuer/audience,
        wrong token type, malformed subject -- is reported as the same opaque
        error. Distinguishing them would tell an attacker holding a token
        exactly which property to fix next.
        """
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
        except InvalidTokenError as exc:
            raise AuthenticationError("Invalid or expired token.") from exc

        # A refresh token must never be accepted where an access token is
        # required. Without this check the two are interchangeable to anyone
        # holding either, and the short access lifetime stops meaning anything.
        if payload.get(_CLAIM_TYPE) != "access":
            raise AuthenticationError("Invalid or expired token.")

        try:
            subject = uuid.UUID(str(payload["sub"]))
        except (KeyError, ValueError) as exc:
            raise AuthenticationError("Invalid or expired token.") from exc

        return AccessTokenClaims(
            subject=subject,
            jti=str(payload.get("jti", "")),
            issued_at=datetime.fromtimestamp(payload["iat"], tz=UTC),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )

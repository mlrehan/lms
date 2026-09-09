"""Opaque refresh tokens: generation, hashing, and comparison.

A refresh token is **not** a JWT. It carries no claims and means nothing on
its own -- it is a random 256-bit lookup key whose only authority comes from
matching a row in `tokens`. That is what makes it revocable: deleting or
flagging the row ends the session immediately, which a self-contained signed
token can never do before it expires.

**Hashed with SHA-256, not Argon2 -- deliberately, and this is the one place
in the codebase where that is the right call.** Argon2 is correct for
passwords because passwords are low-entropy and human-chosen, so an attacker
holding the hash can guess them; deliberate slowness is the defence. A
refresh token is 256 bits from `secrets.token_urlsafe`, so guessing it is not
a threat model, and Argon2's per-hash random salt would make lookup
impossible -- we would have to load every row and verify one by one. SHA-256
gives a deterministic value we can put a unique index on and find in one
query, while still meaning a leaked `tokens` table yields nothing usable.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Final

# 32 bytes -> 43 url-safe characters. Comfortably inside the column's
# String(500) and far beyond guessing range.
_TOKEN_BYTES: Final = 32


def generate_refresh_token() -> str:
    """Return a new, unguessable refresh token (the raw value)."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_refresh_token(raw_token: str) -> str:
    """Return the storable hash of ``raw_token``."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def refresh_tokens_match(raw_token: str, stored_hash: str) -> bool:
    """Constant-time comparison of a presented token against a stored hash.

    `hmac.compare_digest` rather than `==`: string equality short-circuits on
    the first differing byte, and the timing difference is measurable enough
    to reconstruct a value byte by byte.
    """
    return hmac.compare_digest(hash_refresh_token(raw_token), stored_hash)

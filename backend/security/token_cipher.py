"""Encryption for third-party tokens stored in the database (AES-256-GCM).

A Google refresh token is a long-lived credential for the institution's calendar. It is
stored encrypted with the deployment's master key and never returned by any API, logged, or
included in an error message.

Each value gets a fresh random nonce, and the ciphertext is bound to its *purpose* through
the associated data, so a blob copied from one column into another (or another system's
blob presented here) fails authentication instead of decrypting to something.
"""

from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.core.config import get_settings

_SCHEME = "v1"
_NONCE_BYTES = 12


class TokenCipherError(Exception):
    """The value could not be decrypted (wrong key, tampered, or wrong purpose). Carries no value."""


def _key() -> bytes:
    key = get_settings().security.master_key_bytes()
    if len(key) != 32:
        raise TokenCipherError("The master encryption key must be 32 bytes.")
    return key


def encrypt(plaintext: str, *, purpose: str) -> str:
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_key()).encrypt(nonce, plaintext.encode("utf-8"), purpose.encode("utf-8"))
    return ":".join((_SCHEME, base64.urlsafe_b64encode(nonce).decode(), base64.urlsafe_b64encode(ciphertext).decode()))


def decrypt(blob: str, *, purpose: str) -> str:
    try:
        scheme, nonce_b64, ct_b64 = blob.split(":")
        if scheme != _SCHEME:
            raise ValueError
        nonce = base64.urlsafe_b64decode(nonce_b64)
        ciphertext = base64.urlsafe_b64decode(ct_b64)
        return AESGCM(_key()).decrypt(nonce, ciphertext, purpose.encode("utf-8")).decode("utf-8")
    except (ValueError, InvalidTag):
        raise TokenCipherError("Stored token could not be decrypted.") from None

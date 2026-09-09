"""Signing outbound webhook deliveries.

A webhook URL is not a secret — it sits in a database row, in logs, and in
whatever the receiver's framework prints on an error. So the URL cannot
authenticate the call, and a receiver that trusts "it arrived at my secret
path" is trusting a value that leaks by design. The signature is what makes a
delivery attributable.

Three properties, and each one is a specific attack removed:

* **HMAC-SHA256 over the exact bytes sent**, so a body altered in transit
  fails. Signing a re-serialised copy would let two JSON encodings of the
  same object disagree; the bytes that are hashed are the bytes that go on
  the wire.
* **The timestamp is inside the signed material**, not merely alongside it.
  Signing only the body lets an attacker replay yesterday's delivery for ever
  with its signature intact; signing `timestamp.body` means an old delivery
  can be recognised as old, and the receiver is told the window to enforce.
* **Comparison is `hmac.compare_digest`.** A receiver doing `==` leaks the
  correct signature one byte at a time to anyone who can time it. This module
  cannot make the receiver behave, but :func:`verify` is what the
  documentation points at, so the example is right.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

SIGNATURE_HEADER = "X-LMS-Signature"
TIMESTAMP_HEADER = "X-LMS-Timestamp"
EVENT_HEADER = "X-LMS-Event"
DELIVERY_HEADER = "X-LMS-Delivery"

# How far out of date a delivery may be before a receiver should refuse it.
# Advertised rather than enforced here -- the receiver is the only party that
# can enforce it, so the number is documented and the timestamp is provided.
REPLAY_WINDOW_SECONDS = 300


def new_secret() -> str:
    """A fresh signing secret. Shown once, at creation, and never echoed."""
    return secrets.token_urlsafe(32)


def signature_for(*, secret: str, timestamp: int, body: bytes) -> str:
    """`sha256=<hex>` over `"{timestamp}.".encode() + body`.

    The separator matters: without it, a timestamp of `12` with body `3...`
    and a timestamp of `123` with body `...` hash identically, and an
    attacker who can influence either can shift bytes between them.
    """
    material = f"{timestamp}.".encode() + body
    digest = hmac.new(secret.encode(), material, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify(
    *,
    secret: str,
    timestamp: int,
    body: bytes,
    signature: str,
    window_seconds: int = REPLAY_WINDOW_SECONDS,
    now: int | None = None,
) -> bool:
    """The check a receiver should perform. Provided so the docs can be right.

    Order matters: the freshness check happens first and cheaply, so a flood
    of stale replays never reaches the HMAC computation.
    """
    current = now if now is not None else int(time.time())
    if abs(current - timestamp) > window_seconds:
        return False
    expected = signature_for(secret=secret, timestamp=timestamp, body=body)
    return hmac.compare_digest(expected, signature)

"""Generate a VAPID key pair for Web Push.

    python -m backend.cli.generate_vapid_keys

Prints the two settings to add to `.env`. The pair identifies this deployment
to push services; rotating it invalidates every existing subscription, because
a browser records the application server key it subscribed with -- so generate
once per environment and keep it.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def _b64(raw: bytes) -> str:
    """URL-safe base64 with no padding.

    Padding is not optional-but-tolerated here: a browser's
    `applicationServerKey` is decoded strictly, and a trailing `=` is one of
    the two reasons a subscribe call fails with an unhelpful DOMException.
    """
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def main() -> None:
    key = ec.generate_private_key(ec.SECP256R1())

    private = _b64(key.private_numbers().private_value.to_bytes(32, "big"))
    # Uncompressed point (65 bytes, leading 0x04) -- the only encoding the Web
    # Push spec allows for an application server key.
    public = _b64(
        key.public_key().public_bytes(
            encoding=Encoding.X962, format=PublicFormat.UncompressedPoint
        )
    )

    print("# Web Push (VAPID). Keep the private key out of source control.")
    print(f"PUSH_VAPID_PUBLIC_KEY={public}")
    print(f"PUSH_VAPID_PRIVATE_KEY={private}")
    print("PUSH_SUBJECT=mailto:you@example.org")


if __name__ == "__main__":
    main()

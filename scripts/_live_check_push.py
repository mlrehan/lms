"""Does sending a message actually cause a push to leave the server?

`tests/integration/test_web_push.py` proves the *service* encrypts and signs
correctly. This proves the wiring around it: that an ordinary `POST /messages`
reaches the after-commit hook, that the hook spawns the send without the sender
waiting for it, and that the push goes out with the transaction committed rather
than before it.

Stands up a local HTTP server playing the part of a browser vendor's push
endpoint, registers a subscription pointing at it, then sends one message.

Needs the API running with PUSH__VAPID_* configured.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

API = "http://127.0.0.1:8000/api/v1"
FAILURES: list[str] = []
RECEIVED: list[tuple[dict, bytes]] = []


def check(label: str, actual, expected) -> None:  # noqa: ANN001
    ok = actual == expected
    if not ok:
        FAILURES.append(f"{label}: expected {expected!r}, got {actual!r}")
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {actual!r}")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        RECEIVED.append((dict(self.headers.items()), self.rfile.read(length)))
        self.send_response(201)
        self.end_headers()

    def log_message(self, *args) -> None:  # noqa: ANN002
        pass


def local_ip_port() -> tuple[str, int]:
    server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return "127.0.0.1", server.server_address[1]


def token(identifier: str, password: str) -> str:
    with httpx.Client(timeout=20.0) as c:
        r = c.post(f"{API}/auth/login", json={"identifier": identifier, "password": password})
        r.raise_for_status()
        return r.json()["access_token"]


def main() -> None:
    world = json.loads(sys.stdin.read())
    student = {"Authorization": f"Bearer {token(world['student'], world['password'])}"}
    tutor = {"Authorization": f"Bearer {token(world['tutor'], world['password'])}"}

    with httpx.Client(timeout=20.0) as c:
        key = c.get(f"{API}/push/key", headers=student).json()
    check("the server reports push as configured", key.get("enabled"), True)
    if not key.get("enabled"):
        print("\nSet PUSH__VAPID_PUBLIC_KEY / PUSH__VAPID_PRIVATE_KEY and restart the API.")
        sys.exit(1)

    host, port = local_ip_port()
    endpoint = f"http://{host}:{port}/push/live-check"

    # Real P-256 material, so the server genuinely encrypts against it rather
    # than skipping a step because the keys looked wrong.
    browser = ec.generate_private_key(ec.SECP256R1())
    p256dh = _b64(browser.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))
    auth = _b64(os.urandom(16))

    with httpx.Client(timeout=20.0) as c:
        registered = c.post(
            f"{API}/push/subscriptions",
            headers=student,
            json={"endpoint": endpoint, "p256dh": p256dh, "auth": auth},
        )
        check("this device registers", registered.status_code, 201)

        listed = c.get(f"{API}/push/subscriptions", headers=student).json()
        check("and appears in my device list", len(listed), 1)

        me = c.get(f"{API}/auth/me", headers=student).json()

        started = time.monotonic()
        sent = c.post(
            f"{API}/messages",
            headers=tutor,
            json={
                "to": [me["public_id"]],
                "subject": "Push live check",
                "body_html": "<p>Sent by the push live check.</p>",
                "email_copy": False,
            },
        )
        check("the message is accepted", sent.status_code, 201)
        # The sender must not be waiting on a third-party push service.
        print(f"      sender waited: {time.monotonic() - started:.3f}s")

    deadline = time.monotonic() + 20
    while not RECEIVED and time.monotonic() < deadline:
        time.sleep(0.05)

    check("a push left the server", bool(RECEIVED), True)
    if RECEIVED:
        headers, body = RECEIVED[0]
        lowered = {k.lower(): v for k, v in headers.items()}
        print(f"      arrived after: {time.monotonic() - started:.3f}s")
        check("signed with VAPID", lowered.get("authorization", "").lower().startswith("vapid"), True)
        check("encrypted", lowered.get("content-encoding"), "aes128gcm")
        # The banner may land on an unlocked device, and the payload was
        # composed before the reader was known.
        check("carries no message subject", b"Push live check" not in body, True)
        check("and no sender name", b"livechk" not in body.lower(), True)

    with httpx.Client(timeout=20.0) as c:
        gone = c.post(f"{API}/push/unsubscribe", headers=student, json={"endpoint": endpoint})
        check("the device can be removed", gone.status_code, 204)
        check("and is gone", len(c.get(f"{API}/push/subscriptions", headers=student).json()), 0)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for line in FAILURES:
            print("  -", line)
        sys.exit(1)
    print("all push live checks passed")


if __name__ == "__main__":
    main()

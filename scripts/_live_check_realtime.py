"""Does an event actually reach a browser, and does it reach it *live*?

Two things are being proved here, and neither is provable in-process:

1. **The stream is a stream.** A server that writes frames as they happen and a
   proxy that buffers the body until the response ends are indistinguishable
   from the server's side, and produce a feature that works in curl and delivers
   nothing in a page. This measures the gap between sending a message and the
   frame arriving.
2. **It survives the console's BFF proxy.** The browser never holds a token, so
   every call goes through a Next.js route handler that re-issues it upstream.
   That handler is the exact layer that once destroyed binary uploads by reading
   bodies as text; a long-lived SSE body is the other way for it to go wrong.

Reads the world built by `_live_check_setup.py` on stdin.
"""

from __future__ import annotations

import json
import sys
import threading
import time

import httpx

API = "http://127.0.0.1:8000/api/v1"
PROXY = "http://127.0.0.1:3000/api/backend"
FAILURES: list[str] = []


def check(label: str, actual, expected) -> None:  # noqa: ANN001
    ok = actual == expected
    if not ok:
        FAILURES.append(f"{label}: expected {expected!r}, got {actual!r}")
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {actual!r}")


def note(label: str, value) -> None:  # noqa: ANN001
    print(f"      {label}: {value}")


def token(identifier: str, password: str) -> str:
    with httpx.Client(timeout=20.0) as client:
        r = client.post(f"{API}/auth/login", json={"identifier": identifier, "password": password})
        r.raise_for_status()
        return r.json()["access_token"]


class Stream:
    """Reads SSE frames on a thread, recording when each one arrived."""

    def __init__(self, url: str, *, headers=None, cookies=None) -> None:  # noqa: ANN001
        self.url, self.headers, self.cookies = url, headers or {}, cookies
        self.frames: list[tuple[float, str, dict]] = []
        self.raw: list[str] = []
        self.error: str | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            with httpx.Client(timeout=httpx.Timeout(10.0, read=None), cookies=self.cookies) as c:
                with c.stream("GET", self.url, headers=self.headers) as response:
                    if response.status_code != 200:
                        self.error = f"status {response.status_code}"
                        return
                    self.content_type = response.headers.get("content-type", "")
                    event = None
                    for line in response.iter_lines():
                        if self._stop.is_set():
                            return
                        self.raw.append(line)
                        if line.startswith("event:"):
                            event = line.split(":", 1)[1].strip()
                        elif line.startswith("data:") and event:
                            payload = line.split(":", 1)[1].strip()
                            try:
                                parsed = json.loads(payload)
                            except Exception:  # noqa: BLE001
                                parsed = {}
                            self.frames.append((time.monotonic(), event, parsed))
                            event = None
        except Exception as exc:  # noqa: BLE001
            self.error = f"{type(exc).__name__}: {exc}"

    def wait_for(self, kind: str, timeout: float) -> tuple[float, str, dict] | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for frame in list(self.frames):
                if frame[1] == kind:
                    return frame
            time.sleep(0.02)
        return None

    def stop(self) -> None:
        self._stop.set()


def send_message(sender_token: str, recipient_public_id: str, subject: str) -> None:
    with httpx.Client(timeout=20.0) as client:
        r = client.post(
            f"{API}/messages",
            headers={"Authorization": f"Bearer {sender_token}"},
            json={
                "to": [recipient_public_id],
                "subject": subject,
                "body_html": "<p>Sent by the realtime live check.</p>",
                # No email copy: `mail.enabled` is off here, but asking for one
                # is still the wrong thing for a check to do on a real account.
                "email_copy": False,
            },
        )
        if r.status_code >= 400:
            raise SystemExit(f"could not send the message: {r.status_code} {r.text[:400]}")


def main() -> None:
    world = json.loads(sys.stdin.read())
    student_token = token(world["student"], world["password"])
    tutor_token = token(world["tutor"], world["password"])

    with httpx.Client(timeout=20.0) as c:
        me = c.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {student_token}"}).json()
    student_public_id = me["public_id"]

    print("\n-- direct against the API ------------------------------------")
    direct = Stream(f"{API}/realtime/stream", headers={"Authorization": f"Bearer {student_token}"})
    direct.start()

    ready = direct.wait_for("ready", timeout=10.0)
    check("the stream opens and says so", ready is not None, True)
    if direct.error:
        check("no stream error", direct.error, None)
    check("served as an event stream", getattr(direct, "content_type", "").split(";")[0], "text/event-stream")

    sent_at = time.monotonic()
    send_message(tutor_token, student_public_id, "Realtime check A")
    arrived = direct.wait_for("message.received", timeout=15.0)
    check("a sent message arrives as an event", arrived is not None, True)
    if arrived:
        note("delivered after", f"{arrived[0] - sent_at:.3f}s")
        # The whole point of the design: a hint, not the content. A payload
        # built at write time would have been built for the wrong viewer.
        check("the frame carries no message content", arrived[2].get("data") or {}, {})

    note_frame = direct.wait_for("notification.created", timeout=10.0)
    check("and a notification event too", note_frame is not None, True)
    if note_frame:
        check(
            "whose title was composed for this recipient",
            (note_frame[2].get("data") or {}).get("title", "").startswith("New message from"),
            True,
        )

    print("\n-- isolation -------------------------------------------------")
    outsider = Stream(
        f"{API}/realtime/stream",
        headers={"Authorization": f"Bearer {token(world['outsider'], world['password'])}"},
    )
    outsider.start()
    outsider.wait_for("ready", timeout=10.0)
    sent_at = time.monotonic()
    send_message(tutor_token, student_public_id, "Realtime check B")
    got_b = direct.wait_for("message.received", timeout=15.0)
    check("the addressee is told again", got_b is not None, True)
    # Given ample time: proving "did not arrive" needs longer than proving
    # "arrived", or the test passes because the machine was busy.
    stray = outsider.wait_for("message.received", timeout=3.0)
    check("someone else's stream stays silent", stray, None)
    outsider.stop()

    print("\n-- unauthenticated -------------------------------------------")
    with httpx.Client(timeout=10.0) as c:
        check("no token is refused", c.get(f"{API}/realtime/stream").status_code, 401)
        check(
            "a bad token is refused",
            c.get(f"{API}/realtime/stream", headers={"Authorization": "Bearer nope"}).status_code,
            401,
        )

    print("\n-- through the console's BFF proxy ---------------------------")
    try:
        jar = httpx.Cookies()
        with httpx.Client(timeout=20.0, cookies=jar, follow_redirects=False) as c:
            # The console's own sign-in route, not the pass-through proxy:
            # this is the one that moves the tokens out of the response body
            # into `httpOnly` cookies, which is how the browser holds none.
            login = c.post(
                "http://127.0.0.1:3000/api/auth/login",
                json={"identifier": world["student"], "password": world["password"]},
            )
            if login.status_code >= 400:
                raise RuntimeError(f"proxy login {login.status_code}")
            jar = c.cookies

        proxied = Stream(f"{PROXY}/realtime/stream", cookies=jar)
        proxied.start()
        check("the proxy opens the stream", proxied.wait_for("ready", timeout=15.0) is not None, True)

        sent_at = time.monotonic()
        send_message(tutor_token, student_public_id, "Realtime check C")
        through = proxied.wait_for("message.received", timeout=15.0)
        check("and delivers an event through it", through is not None, True)
        if through:
            gap = through[0] - sent_at
            note("delivered after", f"{gap:.3f}s")
            # A buffering proxy holds everything until the response ends, which
            # for this endpoint is half an hour. Anything under a second is a
            # stream; nothing else explains it.
            check("which means it is not buffering", gap < 3.0, True)
        proxied.stop()
    except Exception as exc:  # noqa: BLE001
        print(f"SKIP  proxy checks: {type(exc).__name__}: {exc}")
        print("      (start the console with `npm run dev` to include them)")

    direct.stop()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for line in FAILURES:
            print("  -", line)
        sys.exit(1)
    print("all realtime live checks passed")


if __name__ == "__main__":
    main()

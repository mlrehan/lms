"""Drive the join and recording endpoints against a *running* server.

Everything else in this change is proved at the service layer or through an
in-process ASGI app. Neither of those exercises routing order, the permission
dependency on each route, or what a real socket does with a `Range` request --
and this codebase has been caught out three times by exactly that gap.

Reads the world built by `_live_check_setup.py` on stdin.
"""

from __future__ import annotations

import json
import sys

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
FAILURES: list[str] = []


def check(label: str, actual, expected) -> None:  # noqa: ANN001
    ok = actual == expected
    if not ok:
        FAILURES.append(f"{label}: expected {expected!r}, got {actual!r}")
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {actual!r}")


def token(client: httpx.Client, identifier: str, password: str) -> str:
    response = client.post(
        f"{BASE}/auth/login", json={"identifier": identifier, "password": password}
    )
    response.raise_for_status()
    return response.json()["access_token"]


def main() -> None:
    world = json.loads(sys.stdin.read())
    live, soon = world["live"], world["soon"]

    with httpx.Client(timeout=20.0) as client:
        student = {"Authorization": f"Bearer {token(client, world['student'], world['password'])}"}
        tutor = {"Authorization": f"Bearer {token(client, world['tutor'], world['password'])}"}
        outsider = {"Authorization": f"Bearer {token(client, world['outsider'], world['password'])}"}
        admin = {"Authorization": f"Bearer {token(client, world['admin'], world['password'])}"}

        print("\n-- the link is withheld from the payload ---------------------")
        payload = client.get(f"{BASE}/sessions/{live}", headers=student).json()
        check("student sees no meeting_link", payload["meeting_link"], None)
        check("student sees no recording_link", payload["recording_link"], None)
        check("student can_join_now", payload["can_join_now"], True)
        check("student can_manage", payload["can_manage"], False)
        check("student has_recording", payload["has_recording"], True)

        staff = client.get(f"{BASE}/sessions/{live}", headers=tutor).json()
        check("tutor does get meeting_link", staff["meeting_link"] is not None, True)
        check("tutor can_manage", staff["can_manage"], True)

        print("\n-- joining ---------------------------------------------------")
        opened = client.post(f"{BASE}/sessions/{live}/join", headers=student)
        check("student joins a running class", opened.status_code, 200)
        check("and is given the link", opened.json()["meeting_link"].startswith("https://"), True)
        check("not marked as an override", opened.json()["joined_outside_window"], False)

        shut = client.post(f"{BASE}/sessions/{soon}/join", headers=student)
        check("a class six hours away is refused", shut.status_code, 409)
        check("and the refusal says when", "opens_at" in (shut.json().get("details") or {}), True)

        denied = client.post(f"{BASE}/sessions/{live}/join", headers=outsider)
        check("an outsider gets 404, never 403", denied.status_code, 404)

        print("\n-- the authorised exception ----------------------------------")
        forced = client.post(f"{BASE}/sessions/{soon}/join", headers=admin)
        check("session.override opens a shut door", forced.status_code, 200)
        check("and the ticket says so", forced.json()["joined_outside_window"], True)
        ordinary = client.post(f"{BASE}/sessions/{live}/join", headers=admin)
        check("but an ordinary join is not marked", ordinary.json()["joined_outside_window"], False)

        listing = client.get(f"{BASE}/sessions", headers=admin, params={"page_size": 100}).json()
        row = next(r for r in listing["items"] if r["public_id"] == soon)
        check("the timetable offers them the button", row["can_join_now"], True)
        check("and the timetable carries no link at all", "meeting_link" in row, False)
        student_rows = client.get(f"{BASE}/sessions", headers=student, params={"page_size": 100}).json()["items"]
        student_row = next(r for r in student_rows if r["public_id"] == soon)
        check("but a student is not offered it", student_row["can_join_now"], False)

        print("\n-- recordings ------------------------------------------------")
        rec = client.get(f"{BASE}/sessions/{live}/recording", headers=student).json()
        check("student gets a playback path", rec["playback_url"], f"/sessions/{live}/recording/stream")
        check("student is never given the provider link", rec["external_url"], None)
        staff_rec = client.get(f"{BASE}/sessions/{live}/recording", headers=tutor).json()
        check("tutor does get the provider link", staff_rec["external_url"] is not None, True)

        check(
            "an outsider cannot see the recording",
            client.get(f"{BASE}/sessions/{live}/recording", headers=outsider).status_code,
            404,
        )

        print("\n-- streaming over a real socket ------------------------------")
        whole = client.get(f"{BASE}/sessions/{live}/recording/stream", headers=student)
        check("full stream is 200", whole.status_code, 200)
        check("of the right length", len(whole.content), world["media_bytes"])
        check("and advertises seeking", whole.headers.get("accept-ranges"), "bytes")
        check("played inline, not downloaded", whole.headers["content-disposition"].startswith("inline"), True)
        check("not sniffable", whole.headers.get("x-content-type-options"), "nosniff")

        part = client.get(
            f"{BASE}/sessions/{live}/recording/stream",
            headers={**student, "Range": "bytes=100-199"},
        )
        check("a seek returns 206", part.status_code, 206)
        check("with the right range", part.headers.get("content-range"), f"bytes 100-199/{world['media_bytes']}")
        check("and exactly those bytes", len(part.content), 100)
        check("which are the right ones", part.content, bytes(range(256))[100:200])

        check(
            "an outsider cannot stream it",
            client.get(f"{BASE}/sessions/{live}/recording/stream", headers=outsider).status_code,
            404,
        )

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for line in FAILURES:
            print("  -", line)
        sys.exit(1)
    print("all live checks passed")


if __name__ == "__main__":
    main()

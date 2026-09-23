"""Staff-only media, over HTTP, against the running server.

The service tests prove the rule. This proves the *routes* apply it -- each of
the four doors is a different endpoint with its own dependency chain, and a
guard that lives in the service is only as good as the routes that go through
it. It also proves the ranged player is wired to `/preview`, which is what makes
a shared recording seekable rather than a download that restarts on every scrub.

Reads the world built by `_live_check_setup.py` on stdin.
"""

from __future__ import annotations

import json
import sys
import httpx

API = "http://127.0.0.1:8000/api/v1"
FAILURES: list[str] = []


def check(label: str, actual, expected) -> None:  # noqa: ANN001
    ok = actual == expected
    if not ok:
        FAILURES.append(f"{label}: expected {expected!r}, got {actual!r}")
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {actual!r}")


def token(client: httpx.Client, identifier: str, password: str) -> str:
    r = client.post(f"{API}/auth/login", json={"identifier": identifier, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]


def main() -> None:
    world = json.loads(sys.stdin.read())

    with httpx.Client(timeout=30.0) as c:
        tutor = {"Authorization": f"Bearer {token(c, world['tutor'], world['password'])}"}
        student = {"Authorization": f"Bearer {token(c, world['student'], world['password'])}"}
        admin = {"Authorization": f"Bearer {token(c, world['admin'], world['password'])}"}

        # The setup script already put a real video in storage and attached it
        # to a session; find it through the tutor's own listing.
        listed = c.get(f"{API}/resources", headers=tutor, params={"query": "livechk", "limit": 50}).json()
        items = listed["items"]
        check("the tutor can see the recording", len(items) >= 1, True)
        if not items:
            sys.exit(1)
        rid = items[0]["public_id"]

        print("\n-- before it is restricted -----------------------------------")
        check("a student can open it", c.get(f"{API}/resources/{rid}", headers=student).status_code, 200)
        seen = c.get(f"{API}/resources", headers=student, params={"query": "livechk", "limit": 50}).json()
        check("and it is in their list", any(i["public_id"] == rid for i in seen["items"]), True)

        link = c.put(f"{API}/resources/{rid}/share-link", headers=tutor, params={"enabled": True})
        check("a public link can be issued", link.status_code, 200)
        share_token = link.json().get("share_token")
        check("which opens without signing in", c.get(f"{API}/shared/{share_token}").status_code in (200, 307), True)

        print("\n-- restrict it ----------------------------------------------")
        marked = c.patch(f"{API}/resources/{rid}", headers=tutor, json={"is_restricted": True})
        check("the tutor can mark it staff-only", marked.status_code, 200)
        check("and the response says so", marked.json().get("is_restricted"), True)

        print("\n-- door 1: opening ------------------------------------------")
        # 404, never 403: a file this person should not have been offered must
        # not be provable to exist by the shape of the refusal.
        check("the student now gets 404", c.get(f"{API}/resources/{rid}", headers=student).status_code, 404)
        check("not 403", c.get(f"{API}/resources/{rid}", headers=student).status_code != 403, True)
        check("the tutor still gets 200", c.get(f"{API}/resources/{rid}", headers=tutor).status_code, 200)
        check("and so does an administrator", c.get(f"{API}/resources/{rid}", headers=admin).status_code, 200)

        print("\n-- door 2: the listing --------------------------------------")
        after = c.get(f"{API}/resources", headers=student, params={"query": "livechk", "limit": 50}).json()
        check("it is gone from the student's list", any(i["public_id"] == rid for i in after["items"]), False)
        staff_list = c.get(f"{API}/resources", headers=tutor, params={"query": "livechk", "limit": 50}).json()
        check("still in the tutor's", any(i["public_id"] == rid for i in staff_list["items"]), True)
        check("flagged in it", next(i for i in staff_list["items"] if i["public_id"] == rid)["is_restricted"], True)

        print("\n-- door 3: sharing ------------------------------------------")
        with httpx.Client(timeout=20.0) as me:
            student_id = me.get(f"{API}/auth/me", headers=student).json()["public_id"]
        refused = c.post(
            f"{API}/resources/{rid}/share",
            headers=tutor,
            json={"user_ids": [student_id], "level": "VIEW"},
        )
        check("sharing it with the student is refused", refused.status_code, 422)

        print("\n-- door 4: the public link ----------------------------------")
        check("the old link is dead", c.get(f"{API}/shared/{share_token}").status_code, 404)
        reissue = c.put(f"{API}/resources/{rid}/share-link", headers=tutor, params={"enabled": True})
        check("and a new one is refused", reissue.status_code, 422)

        print("\n-- playback, for the staff who may -------------------------")
        whole = c.get(f"{API}/resources/{rid}/preview", headers=tutor)
        check("the tutor can stream it", whole.status_code, 200)
        check("and may seek", whole.headers.get("accept-ranges"), "bytes")
        part = c.get(
            f"{API}/resources/{rid}/preview", headers={**tutor, "Range": "bytes=10-49"}
        )
        check("a range returns 206", part.status_code, 206)
        check("of exactly those bytes", len(part.content), 40)
        check("the student cannot stream it", c.get(f"{API}/resources/{rid}/preview", headers=student).status_code, 404)

        print("\n-- and it can be undone -------------------------------------")
        back = c.patch(f"{API}/resources/{rid}", headers=tutor, json={"is_restricted": False})
        check("unmarking works", back.json().get("is_restricted"), False)
        check("the student can open it again", c.get(f"{API}/resources/{rid}", headers=student).status_code, 200)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for line in FAILURES:
            print("  -", line)
        sys.exit(1)
    print("all restricted-media live checks passed")


if __name__ == "__main__":
    main()

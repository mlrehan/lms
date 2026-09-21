"""Attendance as a workflow: queue, draft, submit, correct, on behalf of a tutor -- and the trail it leaves."""

from __future__ import annotations

import asyncio
import random
import selectors
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from backend.core.config import get_settings
from backend.db.manager import DatabaseManager
from backend.main import app
from backend.models.attendance import Attendance
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.security.password import hash_password
from backend.utils.enums import AttendanceStatus, CourseStatus, EnrollmentStatus, Platforms, UserStatus

PASSWORD = "Att!Test2026xx"
P, L, A, E = "PRESENT", "LATE", "ABSENT", "EXCUSED"


@pytest.fixture()
def world():
    tag = f"at{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="attendance-tests")
    ids: dict[str, str] = {}
    people: dict[str, dict] = {}
    tokens: dict[str, str] = {}

    async def build() -> None:
        async with db.session_factory.begin() as s:
            roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

            def person(key: str, role: str) -> User:
                email = f"{tag}.{key}@t.test"
                people[key] = {"email": email, "name": f"{key.title()} {tag}"}
                return User(username=email, slug=f"{tag}-{key}", email=email, first_name=key.title(), last_name=tag, hashed_password=hash_password(PASSWORD),
                            status=UserStatus.ACTIVE, can_login=True, roles=[roles[role]])

            u = {k: person(k, r) for k, r in [("tutora", "TUTOR"), ("tutorb", "TUTOR"), ("boss", "ADMIN"), ("s1", "STUDENT"), ("s2", "STUDENT"), ("s3", "STUDENT")]}
            course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
            course.batches, course.resources, course.tags, course.tutors = [], [], [], []
            s.add_all([*u.values(), course])
            await s.flush()
            b = Batch(batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(), end_date=date.today() + timedelta(days=30), is_active=True, capacity=10)
            b.sessions, b.enrollments, b.student_reviews = [], [], []
            s.add(b)
            await s.flush()
            now = datetime.now(timezone.utc)
            for k in ("s1", "s2", "s3"):
                s.add(Enrollments(batch_id=b.id, student_id=u[k].id, enrollment_date=now, status=EnrollmentStatus.CONFIRMED))

            def sess(tutor: User, days: int, **kw):  # noqa: ANN003, ANN202
                x = BatchSession(batch_id=b.id, tutor_id=tutor.id, session_start_time=now + timedelta(days=days), session_end_time=now + timedelta(days=days, hours=2),
                                 duration_minutes=120, platform=Platforms.Zoom, **kw)
                x.attendances = []
                s.add(x)
                return x

            x, y, legacy, cancelled = sess(u["tutora"], -1), sess(u["tutorb"], -2), sess(u["tutora"], -3), sess(u["tutora"], -4, cancelled_at=now)
            await s.flush()
            s.add(Attendance(session_id=legacy.id, student_id=u["s1"].id, recorded_by=u["tutora"].id, status=AttendanceStatus.PRESENT))
            await s.flush()
            ids.update(x=str(x.public_id), y=str(y.public_id), legacy=str(legacy.public_id), cancelled=str(cancelled.public_id), batch=str(b.public_id), tutora=str(u["tutora"].public_id))
            for k, v in u.items():
                people[k]["public_id"] = str(v.public_id)

    loop.run_until_complete(build())
    lifespan = app.router.lifespan_context(app)
    loop.run_until_complete(lifespan.__aenter__())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")

    def call(who: str, method: str, path: str, **kw):  # noqa: ANN202
        async def go():  # noqa: ANN202
            if who not in tokens:
                ident, pwd = ("superadmin", "ConsoleDrive!2026") if who == "superadmin" else (people[who]["email"], PASSWORD)
                r = await client.post("/api/v1/auth/login", json={"identifier": ident, "password": pwd})
                assert r.status_code == 200, r.text
                tokens[who] = r.json()["access_token"]
            return await client.request(method, f"/api/v1{path}", headers={"Authorization": f"Bearer {tokens[who]}"}, **kw)
        return loop.run_until_complete(go())

    def sheet(who: str, key: str = "x"):  # noqa: ANN202
        return call(who, "GET", f"/attendance/sessions/{ids[key]}/sheet")

    def save(who: str, marks: dict[str, str | None], *, submit: bool = False, key: str = "x", notes: str | None = None, remarks: dict | None = None):  # noqa: ANN202
        entries = [{"student_id": people[k]["public_id"], "status": v, "remarks": (remarks or {}).get(k)} for k, v in marks.items()]
        body: dict = {"entries": entries, "submit": submit}
        if notes is not None:
            body["notes"] = notes
        return call(who, "PUT", f"/attendance/sessions/{ids[key]}/sheet", json=body)

    def raw(sql: str):  # noqa: ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return (await s.execute(text(sql))).all()
        return loop.run_until_complete(go())

    ns = type("W", (), dict(tag=tag, ids=ids, people=people, call=staticmethod(call), sheet=staticmethod(sheet), save=staticmethod(save), raw=staticmethod(raw)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                bs = "SELECT id FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"
                await s.execute(text(f"DELETE FROM attendance_sheets WHERE session_id IN ({bs})"), p)
                await s.execute(text(f"DELETE FROM attendances WHERE session_id IN ({bs})"), p)
                await s.execute(text(f"DELETE FROM batch_sessions WHERE id IN ({bs})"), p)
                await s.execute(text("DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
                await s.execute(text("DELETE FROM batches WHERE batch_code LIKE :c"), p)
                await s.execute(text("DELETE FROM courses WHERE title LIKE :t"), p)
                await s.execute(text("DELETE FROM tokens WHERE user_id IN (SELECT id FROM users WHERE email LIKE :u)"), p)
                await s.execute(text("DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE email LIKE :u)"), p)
                await s.execute(text("DELETE FROM users WHERE email LIKE :u"), p)
        loop.run_until_complete(client.aclose())
        loop.run_until_complete(lifespan.__aexit__(None, None, None))
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def everyone(status: str = P) -> dict[str, str]:
    return {"s1": status, "s2": status, "s3": status}


# ------------------------------------------------------------------------------------------------- the queue


def test_a_tutor_sees_only_their_own_sessions_and_a_super_admin_sees_them_all(world) -> None:
    w = world
    mine = w.call("tutora", "GET", "/attendance/queue", params={"batch_id": w.ids["batch"]}).json()["items"]
    assert sorted(i["session_id"] for i in mine) == sorted([w.ids["x"], w.ids["legacy"]]) and all(i["can_edit"] for i in mine)      # not tutorb's, not the cancelled one
    every = w.call("superadmin", "GET", "/attendance/queue", params={"batch_id": w.ids["batch"]}).json()["items"]
    assert sorted(i["session_id"] for i in every) == sorted([w.ids["x"], w.ids["y"], w.ids["legacy"]])
    narrowed = w.call("superadmin", "GET", "/attendance/queue", params={"batch_id": w.ids["batch"], "tutor_id": w.ids["tutora"]}).json()["items"]
    assert sorted(i["session_id"] for i in narrowed) == sorted([w.ids["x"], w.ids["legacy"]])


def test_an_administrator_can_see_the_queue_but_not_take_a_register(world) -> None:
    items = world.call("boss", "GET", "/attendance/queue", params={"batch_id": world.ids["batch"]}).json()["items"]
    assert len(items) == 3 and not any(i["can_edit"] for i in items)


def test_the_queue_can_be_filtered_by_state(world) -> None:
    w = world
    assert {i["state"] for i in w.call("superadmin", "GET", "/attendance/queue", params={"batch_id": w.ids["batch"], "state": "FINALIZED"}).json()["items"]} == {"FINALIZED"}
    pending = {i["session_id"] for i in w.call("superadmin", "GET", "/attendance/queue", params={"batch_id": w.ids["batch"], "state": "PENDING"}).json()["items"]}
    assert pending == {w.ids["x"], w.ids["y"]}                                                # the legacy one is already done


# ------------------------------------------------------------------------------------------------- draft and submit


def test_a_new_sheet_lists_the_roster_by_name_with_nobody_marked(world) -> None:
    body = world.sheet("tutora").json()
    assert body["meta"]["state"] == "NOT_STARTED" and body["summary"] == {"present": 0, "late": 0, "absent": 0, "excused": 0, "unmarked": 3, "total": 3, "rate": None}
    assert sorted(r["student"]["name"] for r in body["roster"]) == sorted(world.people[k]["name"] for k in ("s1", "s2", "s3"))
    assert body["permissions"] == {"can_edit": True, "is_assigned_tutor": True, "would_be_on_behalf": False}
    assert all(p["email"] not in str(body) for p in world.people.values())                      # names only


def test_a_draft_is_saved_but_is_not_attendance(world) -> None:
    w = world
    r = w.save("tutora", {"s1": P, "s2": A}, notes="Fire drill halfway through")
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["state"] == "DRAFT" and body["notes"] == "Fire drill halfway through"
    assert body["summary"]["present"] == 1 and body["summary"]["absent"] == 1 and body["summary"]["unmarked"] == 1
    assert w.raw(f"SELECT count(*) FROM attendances WHERE session_id = (SELECT id FROM batch_sessions WHERE public_id = '{w.ids['x']}')")[0][0] == 0   # nothing reached the record
    # ... and drafting again, with a change and a clear, updates it.
    again = w.save("tutora", {"s2": L, "s1": None}).json()
    assert again["summary"]["late"] == 1 and again["summary"]["present"] == 0 and again["summary"]["unmarked"] == 2


def test_submitting_needs_every_student_marked(world) -> None:
    r = world.save("tutora", {"s1": P, "s2": P}, submit=True)
    assert r.status_code == 422 and r.json()["details"] == {"unmarked": 1}
    assert world.sheet("tutora").json()["meta"]["state"] == "NOT_STARTED"


def test_submitting_finalizes_and_writes_the_attendance_record(world) -> None:
    w = world
    w.save("tutora", {"s1": P}, submit=False)                                                    # a draft first ...
    r = w.save("tutora", {"s2": L, "s3": A}, submit=True, remarks={"s3": "Called in sick"})
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["state"] == "FINALIZED" and body["meta"]["submitted_on_behalf"] is False and body["meta"]["finalized_by"]["name"] == w.people["tutora"]["name"]
    assert body["summary"] == {"present": 1, "late": 1, "absent": 1, "excused": 0, "unmarked": 0, "total": 3, "rate": 66.67}
    rows = w.raw(f"SELECT status, remarks FROM attendances WHERE session_id = (SELECT id FROM batch_sessions WHERE public_id = '{w.ids['x']}') ORDER BY status")
    assert [tuple(x) for x in rows] == [("ABSENT", "Called in sick"), ("LATE", None), ("PRESENT", None)]


def test_a_submitted_sheet_cannot_be_saved_as_a_draft_again(world) -> None:
    world.save("tutora", everyone(), submit=True)
    assert world.save("tutora", {"s1": A}, submit=False).status_code == 409


# ------------------------------------------------------------------------------------------------- authority


def test_only_the_assigned_tutor_or_the_super_admin_may_take_a_register(world) -> None:
    w = world
    assert w.save("tutorb", everyone(), submit=True).status_code == 403                         # another tutor, same batch
    assert w.save("boss", everyone(), submit=True).status_code == 403                           # an Administrator
    assert w.call("tutorb", "PUT", f"/sessions/{w.ids['x']}/attendance", json={"entries": [{"student_id": w.people["s1"]["public_id"], "status": P}]}).status_code == 403
    assert w.sheet("tutora").json()["meta"]["state"] == "NOT_STARTED"                           # nothing was written by any of them


def test_the_old_register_endpoint_no_longer_bypasses_the_rules(world) -> None:
    w = world
    ok = w.call("tutora", "PUT", f"/sessions/{w.ids['x']}/attendance", json={"entries": [{"student_id": w.people["s1"]["public_id"], "status": P}]})
    assert ok.status_code == 200 and w.sheet("tutora").json()["meta"]["state"] == "FINALIZED"   # it goes through the sheet, so it is audited too


def test_a_super_admin_can_take_it_on_the_tutors_behalf_and_it_is_recorded(world) -> None:
    w = world
    perms = w.sheet("superadmin").json()["permissions"]
    assert perms == {"can_edit": True, "is_assigned_tutor": False, "would_be_on_behalf": True}
    r = w.save("superadmin", everyone(), submit=True)
    assert r.status_code == 200
    meta = r.json()["meta"]
    assert meta["submitted_on_behalf"] is True and meta["assigned_tutor"]["name"] == w.people["tutora"]["name"] and meta["finalized_by"]["name"] != w.people["tutora"]["name"]

    events = w.call("tutora", "GET", f"/attendance/sessions/{w.ids['x']}/sheet/history").json()["events"]
    finalized = next(e for e in events if e["action"] == "FINALIZED")
    assert finalized["on_behalf"] is True and finalized["assigned_tutor"]["name"] == w.people["tutora"]["name"] and finalized["actor"]["name"] != w.people["tutora"]["name"]
    assert finalized["counts"]["PRESENT"] == 3 and finalized["at"]


def test_the_assigned_tutors_own_submission_is_not_on_behalf(world) -> None:
    w = world
    w.save("tutora", everyone(), submit=True)
    finalized = next(e for e in w.call("tutora", "GET", f"/attendance/sessions/{w.ids['x']}/sheet/history").json()["events"] if e["action"] == "FINALIZED")
    assert finalized["on_behalf"] is False and finalized["actor"]["name"] == w.people["tutora"]["name"]


# ------------------------------------------------------------------------------------------------- edits are events


def test_a_correction_after_submission_records_who_changed_which_student_from_what_to_what(world) -> None:
    w = world
    w.save("tutora", everyone(), submit=True)
    fixed = w.save("superadmin", {"s2": E}, submit=True, remarks={"s2": "Medical letter"})
    assert fixed.status_code == 200 and fixed.json()["summary"]["excused"] == 1
    events = w.call("tutora", "GET", f"/attendance/sessions/{w.ids['x']}/sheet/history").json()["events"]
    assert [e["action"] for e in events] == ["EDITED", "FINALIZED", "STARTED"]                    # newest first
    edit = events[0]
    assert edit["on_behalf"] is True and edit["changes"] == [{"student": w.people["s2"]["name"], "was": P, "now": E, "remarks_changed": True}]
    assert w.raw(f"SELECT updated_by_id IS NOT NULL, updated_at IS NOT NULL FROM attendances WHERE status = 'EXCUSED' AND session_id = (SELECT id FROM batch_sessions WHERE public_id = '{w.ids['x']}')")[0] == (True, True)


def test_resubmitting_without_a_change_adds_nothing_to_the_trail(world) -> None:
    w = world
    w.save("tutora", everyone(), submit=True)
    w.save("tutora", {"s1": P}, submit=True)
    assert [e["action"] for e in w.call("tutora", "GET", f"/attendance/sessions/{w.ids['x']}/sheet/history").json()["events"]] == ["FINALIZED", "STARTED"]


def test_a_note_change_alone_is_an_edit(world) -> None:
    w = world
    w.save("tutora", everyone(), submit=True)
    w.save("tutora", {}, submit=True, notes="Guest speaker attended")
    latest = w.call("tutora", "GET", f"/attendance/sessions/{w.ids['x']}/sheet/history").json()["events"][0]
    assert latest["action"] == "EDITED" and latest["notes_changed"] and latest["changes"] == []


def test_the_trail_cannot_be_rewritten_even_by_the_database_owner(world) -> None:
    w = world
    w.save("tutora", everyone(), submit=True)
    with pytest.raises((DBAPIError, Exception)) as raised:
        w.raw("UPDATE attendance_sheet_events SET on_behalf = NOT on_behalf")
    assert "cannot be modified" in str(raised.value)


# ------------------------------------------------------------------------------------------------- edge cases


def test_marks_from_before_sheets_existed_read_as_finalized_and_gain_a_trail_when_edited(world) -> None:
    w = world
    body = w.sheet("tutora", "legacy").json()
    assert body["meta"]["state"] == "FINALIZED" and body["meta"]["legacy"] is True
    assert w.save("tutora", {"s2": L, "s3": A}, submit=True, key="legacy").status_code == 200
    events = w.call("tutora", "GET", f"/attendance/sessions/{w.ids['legacy']}/sheet/history").json()["events"]
    assert [e["action"] for e in events] == ["EDITED"] and len(events[0]["changes"]) == 2


def test_a_cancelled_session_cannot_have_attendance_taken(world) -> None:
    assert world.save("tutora", everyone(), submit=True, key="cancelled").status_code == 409


def test_a_student_who_is_not_in_the_batch_refuses_the_whole_request(world) -> None:
    body = {"entries": [{"student_id": world.people["tutorb"]["public_id"], "status": P}], "submit": False}
    assert world.call("tutora", "PUT", f"/attendance/sessions/{world.ids['x']}/sheet", json=body).status_code == 422


def test_students_cannot_open_a_sheet(world) -> None:
    assert world.sheet("s1").status_code == 403
    assert world.call("s1", "GET", "/attendance/queue").status_code == 403

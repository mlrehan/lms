"""The "people in my care" view: a manager sees their own employees' progress and nobody else's."""

from __future__ import annotations

import asyncio
import random
import selectors
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.db.manager import DatabaseManager
from backend.main import app
from backend.models.assignment import Assignment
from backend.models.attendance import Attendance
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.guardian import StudentGuardian
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.organization import ManagedStudent, Organization, OrganizationManager, OrganizationMembership
from backend.security.password import hash_password
from backend.utils.enums import (
    AttendanceStatus, CourseStatus, EnrollmentStatus, OrganizationMembershipStatus, Platforms, SubmissionType, UserStatus,
)

PASSWORD = "Team!Test2026xx"


@pytest.fixture()
def world():
    tag = f"tm{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="team-tests")
    people: dict[str, dict] = {}
    tokens: dict[str, str] = {}

    async def build() -> None:
        async with db.session_factory.begin() as s:
            roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

            def person(key: str, role: str) -> User:
                email = f"{tag}.{key}@t.test"
                people[key] = {"email": email}
                return User(username=email, slug=f"{tag}-{key}", email=email, first_name=key.title(), last_name=tag, hashed_password=hash_password(PASSWORD),
                            status=UserStatus.ACTIVE, can_login=True, roles=[roles[role]])

            u = {k: person(k, r) for k, r in [("boss", "CORPORATE_MANAGER"), ("emp1", "STUDENT"), ("emp2", "STUDENT"), ("outsider", "STUDENT"), ("colleague", "STUDENT"), ("parent", "GUARDIAN"), ("tutor", "TUTOR")]}
            org = Organization(name=f"{tag} Org", is_active=True)
            org.managers, org.memberships = [], []
            course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
            course.batches, course.resources, course.tags, course.tutors = [], [], [], []
            s.add_all([*u.values(), org, course])
            await s.flush()
            now = datetime.now(timezone.utc)
            s.add(OrganizationManager(organization_id=org.id, user_id=u["boss"].id, title="L&D", is_active=True, invited_at=now))
            # Three employees of the same company; the boss is given two of
            # them. `colleague` is the point: employment alone grants
            # nothing now, so a manager who is not linked to them must not
            # see them even though they share an employer.
            for k in ("emp1", "emp2", "colleague"):
                s.add(OrganizationMembership(organization_id=org.id, user_id=u[k].id, status=OrganizationMembershipStatus.ACTIVE, department="Ops", employee_code=k.upper()))
            for k in ("emp1", "emp2"):
                s.add(ManagedStudent(manager_id=u["boss"].id, student_id=u[k].id, relationship_type="Line manager", created_at=now))
            s.add(StudentGuardian(guardian_id=u["parent"].id, student_id=u["emp2"].id, relationship_type="Parent", is_primary=True, created_at=now))
            b = Batch(batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(), end_date=date.today() + timedelta(days=30), is_active=True, capacity=10)
            b.sessions, b.enrollments, b.student_reviews = [], [], []
            s.add(b)
            await s.flush()
            for k in ("emp1", "emp2", "outsider", "colleague"):
                s.add(Enrollments(batch_id=b.id, student_id=u[k].id, enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
            sessions = []
            for days in (-4, -3, -2, -1):
                sess = BatchSession(batch_id=b.id, tutor_id=u["tutor"].id, session_start_time=now + timedelta(days=days), session_end_time=now + timedelta(days=days, hours=1),
                                    duration_minutes=60, platform=Platforms.Zoom)
                sess.attendances = []
                s.add(sess)
                sessions.append(sess)
            s.add(Assignment(course_id=course.id, title=f"{tag} report", due_date=now - timedelta(days=1), max_score=100, submission_type=SubmissionType.TEXT))
            await s.flush()
            # emp1 attends one of four sessions (25%); emp2 attends all four.
            for i, sess in enumerate(sessions):
                s.add(Attendance(session_id=sess.id, student_id=u["emp1"].id, recorded_by=u["tutor"].id, status=AttendanceStatus.PRESENT if i == 0 else AttendanceStatus.ABSENT))
                s.add(Attendance(session_id=sess.id, student_id=u["emp2"].id, recorded_by=u["tutor"].id, status=AttendanceStatus.PRESENT))
            await s.flush()
            for k, v in u.items():
                people[k]["public_id"] = str(v.public_id)

    loop.run_until_complete(build())
    lifespan = app.router.lifespan_context(app)
    loop.run_until_complete(lifespan.__aenter__())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")

    def get(who: str, path: str):  # noqa: ANN202
        async def go():  # noqa: ANN202
            if who not in tokens:
                r = await client.post("/api/v1/auth/login", json={"identifier": people[who]["email"], "password": PASSWORD})
                assert r.status_code == 200, r.text
                tokens[who] = r.json()["access_token"]
            return await client.get(f"/api/v1{path}", headers={"Authorization": f"Bearer {tokens[who]}"})
        return loop.run_until_complete(go())

    ns = type("W", (), dict(tag=tag, people=people, get=staticmethod(get)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                await s.execute(text("DELETE FROM tokens WHERE user_id IN (SELECT id FROM users WHERE email LIKE :u)"), p)
                await s.execute(text("DELETE FROM attendances WHERE session_id IN (SELECT id FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c))"), p)
                await s.execute(text("DELETE FROM assignments WHERE title LIKE :t"), p)
                await s.execute(text("DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
                await s.execute(text("DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
                await s.execute(text("DELETE FROM batches WHERE batch_code LIKE :c"), p)
                await s.execute(text("DELETE FROM courses WHERE title LIKE :t"), p)
                await s.execute(text("DELETE FROM student_guardians WHERE guardian_id IN (SELECT id FROM users WHERE email LIKE :u)"), p)
                await s.execute(text("DELETE FROM manager_students WHERE manager_id IN (SELECT id FROM users WHERE username LIKE :u) OR student_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
                await s.execute(text("DELETE FROM organization_memberships WHERE organization_id IN (SELECT id FROM organizations WHERE name LIKE :t)"), p)
                await s.execute(text("DELETE FROM organization_managers WHERE organization_id IN (SELECT id FROM organizations WHERE name LIKE :t)"), p)
                await s.execute(text("DELETE FROM organizations WHERE name LIKE :t"), p)
                await s.execute(text("DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE email LIKE :u)"), p)
                await s.execute(text("DELETE FROM users WHERE email LIKE :u"), p)
        loop.run_until_complete(client.aclose())
        loop.run_until_complete(lifespan.__aexit__(None, None, None))
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def test_a_manager_sees_their_own_employees_and_nobody_else(world) -> None:
    r = world.get("boss", "/team")
    assert r.status_code == 200
    body = r.json()
    names = sorted(m["full_name"] for m in body["items"])
    # The outsider shares a batch; the colleague shares an *employer*. Before
    # the roster became a direct link the second one was visible, because a
    # manager saw every employee of every company they managed -- so this
    # list is the difference the change makes, in one assertion.
    assert names == [f"Emp1 {world.tag}", f"Emp2 {world.tag}"]
    assert body["people"] == 2


def test_the_person_who_needs_attention_is_flagged_and_first(world) -> None:
    items = world.get("boss", "/team").json()["items"]
    first = items[0]
    assert first["full_name"].startswith("Emp1") and first["needs_attention"]
    assert first["attendance_rate"] == 25.0 and first["sessions_recorded"] == 4 and first["assignments_overdue"] == 1
    assert any("Attendance" in reason for reason in first["attention_reasons"]) and any("overdue" in reason for reason in first["attention_reasons"])
    second = items[1]  # attends everything, but the same assignment is overdue for them too: flagged for that alone
    assert second["attendance_rate"] == 100.0 and second["attention_reasons"] == ["1 assignment overdue"]
    assert first["organization"] == f"{world.tag} Org" and first["department"] == "Ops" and first["employee_code"] == "EMP1"


def test_one_persons_detail_shows_their_batch_attendance_and_work(world) -> None:
    body = world.get("boss", f"/team/{world.people['emp1']['public_id']}").json()
    assert [e["batch_code"] for e in body["enrollments"]] == [f"{world.tag}-A"]
    assert body["enrollments"][0]["attendance"] == {"present": 1, "late": 0, "absent": 3, "excused": 0}
    assert [a["status"] for a in body["assignments"]] == ["OVERDUE"]
    assert len(body["recent_attendance"]) == 4


def test_somebody_outside_the_managers_people_is_a_404_not_a_403(world) -> None:
    assert world.get("boss", f"/team/{world.people['outsider']['public_id']}").status_code == 404
    assert world.get("boss", f"/team/{world.people['tutor']['public_id']}").status_code == 404


def test_the_view_never_carries_an_email_address(world) -> None:
    text_ = world.get("boss", "/team").text + world.get("boss", f"/team/{world.people['emp1']['public_id']}").text
    assert all(p["email"] not in text_ for k, p in world.people.items() if k != "boss")


def test_a_student_and_a_tutor_have_no_team_view(world) -> None:
    assert world.get("emp1", "/team").status_code == 403
    assert world.get("tutor", "/team").status_code == 403


def test_a_guardian_sees_only_their_ward_with_the_relationship(world) -> None:
    items = world.get("parent", "/team").json()["items"]
    assert [(m["full_name"], m["relationship"]) for m in items] == [(f"Emp2 {world.tag}", "Parent")]

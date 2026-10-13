"""A Corporate Manager sees the students linked to them, and nobody else.

The link used to be derived: manager -> `organization_managers` ->
`organization_memberships` -> every employee of that company. So a company
with four managers and two hundred employees gave each manager all two
hundred, and "these thirty are yours" could not be said at all. Visibility
was a side effect of the org chart.

`manager_students` is now the only thing that grants it, the same way
`student_guardians` is the only thing that grants a guardian their ward. The
company is still recorded -- who works where, their employee code, which
company sponsored an enrolment -- it simply no longer decides who reads whom.

Two properties carry the weight here, and they pull in opposite directions:

* **sharing an employer grants nothing.** The colleague in these tests is a
  real, active employee of the same company, and invisible to a manager who
  is not linked to them. That case did not exist before and is the whole
  change;
* **ending the employment still ends the access.** It used to happen by
  itself, because visibility was read from the membership row. Nothing would
  notice now, so the service deletes the links -- and a former employee
  staying on their old manager's dashboard is exactly the regression a
  change like this leaves behind.
"""

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
from backend.models.batch import Batch
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.organization import (
    ManagedStudent,
    Organization,
    OrganizationManager,
    OrganizationMembership,
)
from backend.security.password import hash_password
from backend.services.organization_service import OrganizationService
from backend.services.scope import ScopeResolver
from backend.utils.enums import (
    CourseStatus,
    EnrollmentStatus,
    OrganizationMembershipStatus,
    UserStatus,
)

PASSWORD = "ManagerLink!2026"


@pytest.fixture()
def world():
    tag = f"cml{random.randint(100000, 900000)}"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="manager-link-tests")
    people: dict[str, dict] = {}
    ids: dict[str, object] = {}
    tokens: dict[str, str] = {}

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}
        now = datetime.now(timezone.utc)

        def person(key: str, role: str) -> User:
            email = f"{tag}.{key}@t.test"
            people[key] = {"email": email}
            return User(
                username=email, slug=f"{tag}-{key}", email=email,
                first_name=key.title(), last_name=tag,
                hashed_password=hash_password(PASSWORD),
                status=UserStatus.ACTIVE, can_login=True, roles=[roles[role]],
            )

        u = {
            k: person(k, r)
            for k, r in [
                ("mine", "CORPORATE_MANAGER"),      # the manager under test
                ("other", "CORPORATE_MANAGER"),     # same company, different roster
                ("alice", "STUDENT"),               # linked to `mine`
                ("bob", "STUDENT"),                 # linked to `other`
                ("colleague", "STUDENT"),           # employed, linked to nobody
                ("stranger", "STUDENT"),            # no employment at all
                ("admin", "SUPER_ADMIN"),
            ]
        }
        org = Organization(name=f"{tag} Ltd", is_active=True)
        org.managers, org.memberships = [], []
        course = Course(title=f"{tag} Course", code=tag, status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([*u.values(), org, course])
        await s.flush()

        for key in ("mine", "other"):
            s.add(OrganizationManager(organization_id=org.id, user_id=u[key].id,
                                      is_active=True, invited_at=now))
        for key in ("alice", "bob", "colleague"):
            s.add(OrganizationMembership(
                organization_id=org.id, user_id=u[key].id,
                status=OrganizationMembershipStatus.ACTIVE,
                department="Ops", employee_code=key.upper(), invited_at=now,
            ))
        s.add(ManagedStudent(manager_id=u["mine"].id, student_id=u["alice"].id,
                             relationship_type="Line manager", created_at=now))
        s.add(ManagedStudent(manager_id=u["other"].id, student_id=u["bob"].id,
                             relationship_type="Line manager", created_at=now))

        batch = Batch(batch_code=f"{tag}-A", course_id=course.id, start_date=date.today(),
                      end_date=date.today() + timedelta(days=60), is_active=True, capacity=20)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        s.add(batch)
        await s.flush()
        for key in ("alice", "bob", "colleague", "stranger"):
            s.add(Enrollments(batch_id=batch.id, student_id=u[key].id,
                              enrollment_date=now, status=EnrollmentStatus.CONFIRMED))

        ids.update(
            {k: u[k].id for k in u},
            org=org.id,
            org_public=org.public_id,
            batch=batch.id,
        )
        await s.flush()
        memberships = {
            m.user_id: m.public_id
            for m in (
                await s.execute(
                    select(OrganizationMembership).where(
                        OrganizationMembership.organization_id == org.id
                    )
                )
            ).scalars()
        }
        ids["membership_alice"] = memberships[u["alice"].id]
        appointments = {
            a.user_id: a.public_id
            for a in (
                await s.execute(
                    select(OrganizationManager).where(
                        OrganizationManager.organization_id == org.id
                    )
                )
            ).scalars()
        }
        ids["appointment_mine"] = appointments[u["mine"].id]

    run(build)

    lifespan = app.router.lifespan_context(app)
    loop.run_until_complete(lifespan.__aenter__())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")

    def call(who: str, method: str, path: str, **kwargs):  # noqa: ANN202
        async def go():  # noqa: ANN202
            if who not in tokens:
                r = await client.post("/api/v1/auth/login",
                                      json={"identifier": people[who]["email"], "password": PASSWORD})
                assert r.status_code == 200, r.text[:200]
                tokens[who] = r.json()["access_token"]
            return await client.request(
                method, f"/api/v1{path}",
                headers={"Authorization": f"Bearer {tokens[who]}"}, **kwargs,
            )
        return loop.run_until_complete(go())

    def visible_students(who: str) -> set[int]:
        """Exactly what `ScopeResolver` hands every student-scoped query."""
        async def go(s):  # noqa: ANN001, ANN202
            actor = await s.get(User, ids[who])
            return (await ScopeResolver(s).enrollment_visibility(actor)).cared_for_student_ids
        return set(run(go))

    ns = type("W", (), dict(
        tag=tag, ids=ids, people=people, run=staticmethod(run),
        call=staticmethod(call), visible_students=staticmethod(visible_students),
    ))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                users = "(SELECT id FROM users WHERE username LIKE :u)"
                orgs = "(SELECT id FROM organizations WHERE name LIKE :t)"
                p = {"c": f"{tag}-%", "u": f"{tag}.%", "t": f"{tag}%"}
                for stmt in (
                    f"DELETE FROM notifications WHERE user_id IN {users}",
                    # `audit_logs` is append-only at the database level and
                    # carries no foreign key to `users` on purpose -- a record
                    # outlives the account it describes. So the rows this test
                    # wrote stay, and the users go.
                    f"DELETE FROM manager_students WHERE manager_id IN {users} OR student_id IN {users}",
                    "DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM batches WHERE batch_code LIKE :c",
                    "DELETE FROM courses WHERE title LIKE :t",
                    f"DELETE FROM organization_memberships WHERE organization_id IN {orgs}",
                    f"DELETE FROM organization_managers WHERE organization_id IN {orgs}",
                    "DELETE FROM organizations WHERE name LIKE :t",
                    f"DELETE FROM user_roles WHERE user_id IN {users}",
                    "DELETE FROM users WHERE username LIKE :u",
                ):
                    await s.execute(text(stmt), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(lifespan.__aexit__(None, None, None))
        loop.run_until_complete(client.aclose())
        loop.run_until_complete(db.dispose())
        loop.close()


# =============================================================================
# the rule itself
# =============================================================================


def test_a_manager_sees_the_students_linked_to_them(world) -> None:
    assert world.visible_students("mine") == {world.ids["mine"], world.ids["alice"]}


def test_sharing_an_employer_grants_nothing(world) -> None:
    """The change, in one assertion.

    `colleague` is an active employee of the same company, enrolled on the
    same batch. Under the derived model every manager of that company saw
    them. Under a direct link, nobody does until somebody says so.
    """
    assert world.ids["colleague"] not in world.visible_students("mine")
    assert world.ids["colleague"] not in world.visible_students("other")


def test_two_managers_at_one_company_have_different_rosters(world) -> None:
    # Impossible before: both managed the same organization, so both saw the
    # same people.
    assert world.visible_students("mine") != world.visible_students("other")
    assert world.ids["bob"] not in world.visible_students("mine")
    assert world.ids["alice"] not in world.visible_students("other")


def test_the_scope_reaches_the_endpoints_that_read_it(world) -> None:
    """`cared_for_student_ids` is not the product; the screens are.

    Enrollments is the shortest path to proving the resolver is actually
    consulted -- a scope that is correct and unread would pass every test
    above.
    """
    rows = world.call("mine", "GET", "/enrollments", params={"limit": 100}).json()["items"]
    names = " ".join(str(r) for r in rows)

    assert "alice" in names.lower()
    assert "colleague" not in names.lower()
    assert "bob" not in names.lower()


def test_a_student_with_no_employment_can_still_be_managed(world) -> None:
    """A link does not require a company, which is what makes it a
    relationship between two people rather than a view over an org chart."""
    link = world.call("admin", "POST", "/manager-links", json={
        "manager_id": str(_public(world, "mine")),
        "student_id": str(_public(world, "stranger")),
        "relationship_type": "Sponsor",
    })
    assert link.status_code == 201, link.text[:300]

    assert world.ids["stranger"] in world.visible_students("mine")


def _public(world, key: str):  # noqa: ANN001, ANN202
    async def go(s):  # noqa: ANN001, ANN202
        return (await s.get(User, world.ids[key])).public_id
    return world.run(go)


# =============================================================================
# who may create a link
# =============================================================================


def test_a_manager_cannot_add_somebody_to_their_own_roster(world) -> None:
    """Granting yourself access is an administrator's act, exactly as
    creating your own guardianship would be."""
    r = world.call("mine", "POST", "/manager-links", json={
        "manager_id": str(_public(world, "mine")),
        "student_id": str(_public(world, "colleague")),
    })
    assert r.status_code == 403, r.text[:200]
    assert world.ids["colleague"] not in world.visible_students("mine")


def test_a_manager_reads_their_own_roster(world) -> None:
    rows = world.call("mine", "GET", "/manager-links", params={"limit": 100}).json()["items"]

    assert len(rows) == 1
    assert rows[0]["student_name"] == f"Alice {world.tag}"
    # Not the other manager's link, even though it is the same company.
    assert rows[0]["manager_name"] == f"Mine {world.tag}"

    # A manager does not hold `user.view_contact`, so the username field
    # carries the display name rather than the email -- the same privacy
    # helper every other roster goes through. Asserted because a new route is
    # exactly where that gets forgotten.
    assert "@" not in rows[0]["student_username"]


def test_an_administrator_still_sees_the_address(world) -> None:
    rows = world.call("admin", "GET", "/manager-links", params={
        "manager_id": str(_public(world, "mine")), "limit": 10,
    }).json()["items"]

    assert rows[0]["student_username"] == world.people["alice"]["email"]


def test_a_link_to_somebody_who_is_not_a_manager_is_refused(world) -> None:
    r = world.call("admin", "POST", "/manager-links", json={
        "manager_id": str(_public(world, "alice")),
        "student_id": str(_public(world, "colleague")),
    })
    assert r.status_code in (400, 422), r.text[:200]


# =============================================================================
# the access that ends by itself
# =============================================================================


def test_leaving_the_company_ends_the_managers_access(world) -> None:
    """It used to happen on its own, and now it has to be done.

    Visibility was read from the membership row, so REMOVED stopped
    resolving. The roster is a separate table now and nothing would notice --
    a former employee would stay on their old manager's dashboard, with their
    current coursework, indefinitely.
    """
    assert world.ids["alice"] in world.visible_students("mine")

    async def remove(s):  # noqa: ANN001, ANN202
        admin = await s.get(User, world.ids["admin"])
        return await OrganizationService(s).set_member_status(
            world.ids["membership_alice"],
            OrganizationMembershipStatus.REMOVED,
            organization_public_id=world.ids["org_public"],
            actor=admin,
        )

    world.run(remove)

    assert world.ids["alice"] not in world.visible_students("mine")


def test_revoking_the_appointment_ends_it_too(world) -> None:
    """Same property from the other side: `is_active` was read on every
    resolution, so a revoked appointment ended access at once."""
    assert world.ids["alice"] in world.visible_students("mine")

    async def revoke(s):  # noqa: ANN001, ANN202
        admin = await s.get(User, world.ids["admin"])
        await OrganizationService(s).revoke_manager(
            world.ids["org_public"], world.ids["appointment_mine"], actor=admin
        )

    world.run(revoke)

    assert world.visible_students("mine") == {world.ids["mine"]}
    # The other manager's roster is untouched -- they were not the one revoked.
    assert world.ids["bob"] in world.visible_students("other")


def test_removing_a_link_ends_access_immediately(world) -> None:
    rows = world.call("admin", "GET", "/manager-links", params={
        "manager_id": str(_public(world, "mine")), "limit": 10,
    }).json()["items"]
    assert len(rows) == 1

    assert world.call("admin", "DELETE", f"/manager-links/{rows[0]['public_id']}").status_code == 204
    assert world.ids["alice"] not in world.visible_students("mine")


# =============================================================================
# the invite workflow
# =============================================================================


def test_a_manager_who_adds_an_employee_gets_that_one_person(world) -> None:
    """The dead end this avoids.

    `organization.invite` is a manager's power, and before the change adding
    an employee made them visible at once -- it was the same row. Dropping
    that entirely would leave a manager inviting somebody they then cannot
    see until an administrator steps in.
    """
    r = world.call("mine", "POST", f"/organizations/{world.ids['org_public']}/members", json={
        "user_id": str(_public(world, "stranger")),
        "activate_immediately": True,
    })
    assert r.status_code in (200, 201), r.text[:300]

    assert world.ids["stranger"] in world.visible_students("mine")
    # And nobody else at the company: the other manager was not the one who
    # brought them in, which is the whole difference from the old rule.
    assert world.ids["stranger"] not in world.visible_students("other")


def test_an_administrator_adding_an_employee_assigns_nobody(world) -> None:
    """An administrator is not the person who will be looking after them, so
    there is nobody to link -- the assignment is a separate, deliberate act."""
    r = world.call("admin", "POST", f"/organizations/{world.ids['org_public']}/members", json={
        "user_id": str(_public(world, "stranger")),
        "activate_immediately": True,
    })
    assert r.status_code in (200, 201), r.text[:300]

    assert world.ids["stranger"] not in world.visible_students("mine")
    assert world.ids["stranger"] not in world.visible_students("other")

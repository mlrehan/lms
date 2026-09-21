"""A corporate manager and their employees can write to each other.

`MailAudience` routed a manager (and a guardian) only to the *tutors* teaching the people in their care, never
to those people themselves. A manager whose employees are not yet enrolled anywhere therefore had an audience
of administrators and nobody else -- unable to write to the seven people they are responsible for, while being
able to read their grades.

Both directions are covered here. Without the return direction the Reply button is refused on a message the
platform has just delivered, which is the kind of half-fix that looks fine until somebody answers.
"""

from __future__ import annotations

import asyncio
import selectors
import uuid

import pytest
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.core.errors import AuthorizationError
from backend.db.manager import DatabaseManager
from backend.models.guardian import StudentGuardian
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.organization import (
    Organization,
    OrganizationManager,
    OrganizationMembership,
)
from backend.services.mail_audience import MailAudience
from backend.utils.enums import OrganizationMembershipStatus, UserStatus


@pytest.fixture()
def env():
    tag = "cc" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="care-circle-tests")

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s, *, employee_status=OrganizationMembershipStatus.ACTIVE):  # noqa: ANN001, ANN202
        roles = {
            n: (await s.execute(select(Role).where(Role.name == n))).scalar_one()
            for n in ("STUDENT", "GUARDIAN", "CORPORATE_MANAGER")
        }

        def user(kind: str, role: str, first: str) -> User:
            return User(
                username=f"{tag}.{kind}", slug=f"{tag}-{kind}", email=f"{tag}.{kind}@t.test",
                first_name=first, last_name="Person", hashed_password="x",
                status=UserStatus.ACTIVE, roles=[roles[role]],
            )

        manager = user("mgr", "CORPORATE_MANAGER", "Mia")
        employee = user("emp", "STUDENT", "Eli")
        outsider = user("out", "STUDENT", "Ola")
        guardian = user("gdn", "GUARDIAN", "Gia")
        ward = user("ward", "STUDENT", "Wes")
        org = Organization(name=f"{tag} Ltd")
        s.add_all([manager, employee, outsider, guardian, ward, org])
        await s.flush()

        s.add_all([
            OrganizationManager(organization_id=org.id, user_id=manager.id, is_active=True),
            OrganizationMembership(organization_id=org.id, user_id=employee.id, status=employee_status),
            StudentGuardian(guardian_id=guardian.id, student_id=ward.id, relationship_type="Parent"),
        ])
        await s.flush()
        return dict(manager=manager, employee=employee, outsider=outsider,
                    guardian=guardian, ward=ward, org=org)

    ns = type("Env", (), dict(tag=tag, run=staticmethod(run), build=staticmethod(build)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                users = "(SELECT id FROM users WHERE username LIKE :u)"
                orgs = "(SELECT id FROM organizations WHERE name LIKE :o)"
                p = {"u": f"{tag}.%", "o": f"{tag}%"}
                await s.execute(text(f"DELETE FROM student_guardians WHERE guardian_id IN {users} OR student_id IN {users}"), p)
                await s.execute(text(f"DELETE FROM organization_memberships WHERE organization_id IN {orgs}"), p)
                await s.execute(text(f"DELETE FROM organization_managers WHERE organization_id IN {orgs}"), p)
                await s.execute(text("DELETE FROM organizations WHERE name LIKE :o"), p)
                await s.execute(text("DELETE FROM users WHERE username LIKE :u"), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _audiences(env, *who: str, employee_status=OrganizationMembershipStatus.ACTIVE):  # noqa: ANN001, ANN202
    """Build the graph once and read several people's audiences from it.

    One build per test: the organization name and usernames are unique per tag, so building twice inside a
    single test collides rather than testing anything.
    """
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s, employee_status=employee_status)
            audience = MailAudience(s)
            return made, [await audience.allowed_ids(made[w]) for w in who]
        return go()
    return env.run(f)


def _audience(env, who: str, *, employee_status=OrganizationMembershipStatus.ACTIVE):  # noqa: ANN001, ANN202
    made, (ids,) = _audiences(env, who, employee_status=employee_status)
    return made, ids


def test_a_manager_may_write_to_their_own_employee(env) -> None:
    made, ids = _audience(env, "manager")
    assert made["employee"].id in ids
    # ...and still not to somebody else's.
    assert made["outsider"].id not in ids


def test_an_employee_may_write_back_to_their_manager(env) -> None:
    """Without this the Reply button is refused on a message that was just delivered."""
    made, ids = _audience(env, "employee")
    assert made["manager"].id in ids


def test_a_former_employee_is_out_of_reach_in_both_directions(env) -> None:
    """REMOVED means they left the company. The audience must follow the same line their data visibility does."""
    made, (mgr_sees, emp_sees) = _audiences(
        env, "manager", "employee", employee_status=OrganizationMembershipStatus.REMOVED
    )
    assert made["employee"].id not in mgr_sees
    assert made["manager"].id not in emp_sees


def test_a_guardian_and_their_ward_may_write_to_each_other(env) -> None:
    made, (gdn_sees, ward_sees) = _audiences(env, "guardian", "ward")
    assert made["ward"].id in gdn_sees
    assert made["guardian"].id in ward_sees


def test_resolving_a_stranger_is_still_refused(env) -> None:
    """The widening must not have opened the directory generally."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            made = await env.build(s)
            with pytest.raises(AuthorizationError):
                await MailAudience(s).resolve(made["manager"], [made["outsider"].public_id])
            # the employee, by contrast, resolves cleanly
            return await MailAudience(s).resolve(made["manager"], [made["employee"].public_id])
        return go()

    assert env.run(f)


def test_the_sender_is_never_in_their_own_audience(env) -> None:
    """A manager is an employee of nothing here, but a guardian who is also a ward -- or any self-link -- must
    not make the actor writable to themselves."""
    made, ids = _audience(env, "manager")
    assert made["manager"].id not in ids

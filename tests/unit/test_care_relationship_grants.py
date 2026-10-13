"""Nobody may grant themselves sight of somebody else's record.

Two relationships decide who, other than staff, may read a student's
attendance, marks and results: a guardian and their ward, and a corporate
manager and their student. Both are asserted *about* people who are not in
the room when it happens, so both are an administrator's act -- "I am this
child's guardian" and "these thirty are mine" are claims, and the institution
has to be the one making them.

The grant that would break that is a single line in the catalogue, and it
would read like a convenience: letting a manager add to their own roster
saves an administrator a job. It also lets them award themselves access to
anybody they can name.

A unit test rather than an API one on purpose. The running app resolves
permissions from `role_permissions` rows, so an API test proves what the
database happens to be seeded with -- editing the catalogue underneath it
changes nothing until somebody re-seeds. The decision lives here, so this is
where it is pinned.
"""

from __future__ import annotations

import pytest

from backend.core.permissions import (
    ALL_PERMISSIONS,
    ROLE_PERMISSIONS,
    Action,
    Module,
    perm,
)
from backend.utils.enums import Roles

#: The two relationship modules and the role each one exists to serve.
RELATIONSHIPS = [
    (Module.GUARDIAN, Roles.GUARDIAN.value),
    (Module.MANAGED_STUDENT, Roles.CORPORATE_MANAGER.value),
]


@pytest.mark.parametrize(("module", "role"), RELATIONSHIPS)
def test_the_beneficiary_may_read_their_own_links(module, role) -> None:
    assert perm(module, Action.READ) in ROLE_PERMISSIONS[role]


@pytest.mark.parametrize(("module", "role"), RELATIONSHIPS)
@pytest.mark.parametrize("action", [Action.CREATE, Action.UPDATE, Action.DELETE])
def test_the_beneficiary_may_not_write_their_own_links(module, role, action) -> None:
    """The whole point: reading your roster and choosing it are different
    acts, and only one of them is yours."""
    assert perm(module, action) not in ROLE_PERMISSIONS[role]


@pytest.mark.parametrize(("module", "_role"), RELATIONSHIPS)
def test_an_administrator_can_make_the_link(module, _role) -> None:
    # Otherwise the relationship could not be created at all, which is the
    # other way to get this wrong.
    for action in (Action.CREATE, Action.UPDATE, Action.DELETE):
        assert perm(module, action) in ROLE_PERMISSIONS[Roles.ADMIN.value]


@pytest.mark.parametrize(("module", "_role"), RELATIONSHIPS)
def test_the_module_is_registered(module, _role) -> None:
    # A permission that is granted but never registered is not checkable;
    # `require_permissions` validates names against the catalogue at import.
    assert perm(module, Action.READ) in ALL_PERMISSIONS


def test_a_students_own_roles_grant_nothing_over_anybody_else() -> None:
    """A student holds neither side of either relationship.

    Worth asserting because both tables name two users, and the natural
    mistake when wiring one up is to grant the module to everyone it
    mentions.
    """
    student = ROLE_PERMISSIONS[Roles.STUDENT.value]
    for module, _role in RELATIONSHIPS:
        assert not any(p.startswith(f"{module}.") for p in student)

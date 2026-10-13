"""Who the catalogue says may see what a course costs.

Asserted against the catalogue directly, not through the API, for the reason
this codebase has already learned once: the running app resolves permissions
from `role_permissions` rows, so an API test proves what the database happens
to be seeded with. Putting `course.view_pricing` back into a role here would
fail nothing over HTTP until somebody re-ran the seeder.

(Which is also why the seeder must be re-run after this change: it reconciles
grants, so it revokes the four that were withdrawn.)
"""

from __future__ import annotations

import pytest

from backend.core.permissions import ROLE_PERMISSIONS

PRICING = "course.view_pricing"


def test_only_the_super_admin_may_see_commercial_terms() -> None:
    holders = {role for role, granted in ROLE_PERMISSIONS.items() if PRICING in granted}
    assert holders == {"SUPER_ADMIN"}


@pytest.mark.parametrize("role", ["ADMIN", "TUTOR", "STUDENT", "GUARDIAN", "CORPORATE_MANAGER"])
def test_a_role_can_still_browse_the_catalogue_without_its_prices(role: str) -> None:
    """The two were granted together, and withdrawing the price must not take
    the catalogue with it -- a student who cannot see what is on offer cannot
    choose a course at all."""
    granted = ROLE_PERMISSIONS[role]
    assert "course.read" in granted
    assert PRICING not in granted

"""The permission ladder, tested without a database.

`ResourcePermissionLevel` was stored on every grant and read by nothing, so the
ordering it implies had never been exercised. These are pure-function tests of
that ordering; `tests/integration/test_resource_permissions.py` proves the
service actually consults it.
"""

from __future__ import annotations

import pytest

from backend.core.resource_access import LEVEL_RANK, at_least, highest
from backend.utils.enums import ResourcePermissionLevel as L


def test_the_ladder_is_strictly_ordered() -> None:
    """VIEW < DOWNLOAD < EDIT < MANAGE, with no ties.

    A tie would make `highest` non-deterministic and `at_least` ambiguous at the
    exact boundary every call site checks.
    """
    ranks = [LEVEL_RANK[level] for level in (L.VIEW, L.DOWNLOAD, L.EDIT, L.MANAGE)]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == 4


@pytest.mark.parametrize(
    ("actual", "required", "allowed"),
    [
        # The case the console was actually getting wrong: a viewer downloading.
        (L.VIEW, L.DOWNLOAD, False),
        (L.VIEW, L.VIEW, True),
        (L.DOWNLOAD, L.DOWNLOAD, True),
        (L.DOWNLOAD, L.EDIT, False),
        (L.EDIT, L.DOWNLOAD, True),
        (L.EDIT, L.MANAGE, False),
        (L.MANAGE, L.MANAGE, True),
        (L.MANAGE, L.VIEW, True),
        # No access at all is not the same as the lowest level.
        (None, L.VIEW, False),
    ],
)
def test_at_least(actual: L | None, required: L, allowed: bool) -> None:
    assert at_least(actual, required) is allowed


def test_the_most_capable_route_wins() -> None:
    """Reached through a course grant *and* a direct share, the better one applies.

    Refusing something the caller is entitled to by another path is the more
    surprising failure, and it is the one people report as a bug.
    """
    assert highest(L.VIEW, L.EDIT, None) is L.EDIT
    assert highest(None, L.DOWNLOAD) is L.DOWNLOAD
    assert highest(L.MANAGE, L.VIEW) is L.MANAGE


def test_no_routes_means_no_access() -> None:
    assert highest() is None
    assert highest(None, None) is None

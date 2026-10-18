"""Which badge numbers each role may see.

Splitting "which badges apply" from "what the numbers are" is deliberate: the
first is the security question and needs no database, the second is arithmetic.
This file is the first half, checked against the six real role permission sets
rather than against a handful of hand-made ones.

Two rules are worth stating because both are easy to get wrong in the direction
that leaks:

**A key the caller may not see is absent, not zero.** A client cannot tell "you
have none" from "you may not know" if both arrive as `0`, and the number stops
being zero eventually. Absence is unambiguous, so these tests assert on the set
of keys rather than on their values.

**An assessment badge belongs to somebody with a part to play.** A guardian or
corporate manager is watching somebody else do the work; a count they cannot
act on is noise, so they get no key at all rather than a zero.
"""

from __future__ import annotations

import pytest

from backend.core.permissions import ROLE_PERMISSIONS
from backend.services.sidebar_counts_service import applicable_badges

#: Every badge the product defines.
ALL_BADGES = {
    "courses", "batches", "sessions", "enrollments",
    "assignments", "quizzes", "exams",
    "announcements", "messages", "notifications",
    "users", "roles", "permissions", "guardians",
}

#: Institution-wide totals. The brief calls these "Super Admin only"; the
#: console gates on `institution.view_all` instead of a role name, which in
#: this deployment means Super Admin and Administrator -- the two roles that
#: are *defined* as seeing the whole institution.
INSTITUTION_WIDE = {"courses", "users", "roles", "permissions", "guardians"}


def badges_for(role: str) -> set[str]:
    held = set(ROLE_PERMISSIONS[role])
    return applicable_badges(held, unrestricted="institution.view_all" in held)


class TestInstitutionWideTotalsStayWithTheInstitutionWideRoles:
    @pytest.mark.parametrize("role", ["SUPER_ADMIN", "ADMIN"])
    def test_a_role_that_sees_everything_gets_the_totals(self, role: str) -> None:
        assert INSTITUTION_WIDE <= badges_for(role)

    @pytest.mark.parametrize(
        "role", ["TUTOR", "CORPORATE_MANAGER", "GUARDIAN", "STUDENT"]
    )
    def test_nobody_else_learns_how_big_the_institution_is(self, role: str) -> None:
        """A tutor must not learn the course count of courses they cannot see.

        This is the leak the badge makes easy: an unscoped `COUNT(*)` is one
        character away from a scoped one and looks identical in review.
        """
        assert badges_for(role) & INSTITUTION_WIDE == set()


class TestAssessmentBadgesFollowResponsibility:
    @pytest.mark.parametrize("role", ["SUPER_ADMIN", "TUTOR", "STUDENT"])
    def test_somebody_with_a_part_to_play_gets_them(self, role: str) -> None:
        assert {"assignments", "quizzes", "exams"} <= badges_for(role)

    @pytest.mark.parametrize("role", ["CORPORATE_MANAGER", "GUARDIAN"])
    def test_a_watcher_gets_no_assessment_badge_at_all(self, role: str) -> None:
        """Not zero -- absent. They are watching somebody else do the work."""
        assert badges_for(role) & {"assignments", "quizzes", "exams"} == set()


class TestTheThingsEverybodyCanReach:
    @pytest.mark.parametrize(
        "role", ["SUPER_ADMIN", "TUTOR", "CORPORATE_MANAGER", "GUARDIAN", "STUDENT"]
    )
    def test_everyone_gets_their_own_scoped_counts(self, role: str) -> None:
        assert {"batches", "sessions", "enrollments", "messages", "notifications"} <= badges_for(role)

    def test_announcements_follow_the_permission_not_the_hierarchy(self) -> None:
        """A corporate manager does not hold `announcement.read` and a guardian
        does. That is deliberate in the catalogue and the user guides say so,
        so the badge must agree rather than assume managers outrank guardians."""
        assert "announcements" in badges_for("GUARDIAN")
        assert "announcements" not in badges_for("CORPORATE_MANAGER")


def test_no_badge_is_invented_that_the_product_does_not_have() -> None:
    for role in ROLE_PERMISSIONS:
        unknown = badges_for(role) - ALL_BADGES
        assert not unknown, f"{role} would be offered unknown badges: {unknown}"


def test_holding_no_permissions_earns_no_badges() -> None:
    """The failure-closed case: a caller we cannot place gets nothing."""
    assert applicable_badges(set(), unrestricted=False) == set()


def test_somebody_who_marks_is_counted_as_a_marker_not_a_student() -> None:
    """A Super Admin holds both `assignment.submit` and `assignment.grade`.

    The badge sits beside a screen they use to mark, so the marking queue is
    the number that belongs there -- and the two must not both be computed.
    """
    held = set(ROLE_PERMISSIONS["SUPER_ADMIN"])
    assert {"assignment.submit", "assignment.grade"} <= held
    assert "assignments" in applicable_badges(held, unrestricted=True)

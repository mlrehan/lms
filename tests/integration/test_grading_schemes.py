"""Configuring how marks become grades.

Everything here changes other people's results, which is why each rule exists
and why each is tested with its opposite. The three that matter:

* **Activation refuses weights that do not total 100.** A scheme summing to 90
  would silently mark every student out of 90 and report it as a percentage.
* **Exactly one default.** Two would mean no code can say which scheme a course
  without an override is graded under — and the database permits only one, so
  the handover has to clear the old one first or be refused.
* **Bands must not overlap.** A mark of 80 falling into both "A" and "B" makes
  the grade depend on row order, which is not a decision anybody made.
"""

from __future__ import annotations

import asyncio
import selectors
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.core.errors import ConflictError, ValidationError
from backend.db.manager import DatabaseManager
from backend.models.identity.user import User
from backend.services.grading_scheme_service import GradingSchemeService
from backend.utils.enums import GradeComponentType as C

D = Decimal


@pytest.fixture()
def env():
    tag = "gs" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="scheme-tests")

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def actor(s):  # noqa: ANN001, ANN202
        return (
            await s.execute(select(User).where(User.username == "superadmin"))
        ).scalar_one()

    ns = type("Env", (), dict(tag=tag, run=staticmethod(run), actor=staticmethod(actor)))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"t": f"{tag}%"}
                inner = "(SELECT id FROM grading_schemes WHERE name LIKE :t)"
                await s.execute(text(f"UPDATE courses SET grading_scheme_id = NULL WHERE grading_scheme_id IN {inner}"), p)
                await s.execute(text(f"DELETE FROM grade_bands WHERE scheme_id IN {inner}"), p)
                await s.execute(text(f"DELETE FROM grading_scheme_components WHERE scheme_id IN {inner}"), p)
                await s.execute(text("DELETE FROM grading_schemes WHERE name LIKE :t"), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _with_scheme(env, fn, *, name_suffix: str = ""):
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            who = await env.actor(s)
            svc = GradingSchemeService(s)
            scheme = await svc.create(actor=who, name=f"{env.tag}{name_suffix} scheme")
            return await fn(svc, scheme, who, s)
        return go()
    return env.run(f)


# ------------------------------------------------------------- activation ---


def test_a_scheme_whose_weights_fall_short_cannot_be_activated(env) -> None:
    """90% would silently mark every student out of 90 and call it a
    percentage. The refusal names the gap, because "invalid" without a number
    sends somebody hunting."""
    async def fn(svc, scheme, who, s):  # noqa: ANN001, ANN202
        await svc.set_components(
            scheme.public_id,
            [
                {"component_type": C.ASSIGNMENT, "weight_percentage": D("50")},
                {"component_type": C.FINAL_EXAM, "weight_percentage": D("40")},
            ],
            actor=who,
        )
        with pytest.raises(ValidationError) as refused:
            await svc.activate(scheme.public_id, actor=who)
        return refused.value.details or {}

    details = _with_scheme(env, fn)
    assert details.get("total") == "90"
    assert details.get("short_by") == "10"


def test_a_scheme_that_totals_a_hundred_activates(env) -> None:
    """The counterpart: without it the refusal above could be passing because
    nothing ever activates."""
    async def fn(svc, scheme, who, s):  # noqa: ANN001, ANN202
        await svc.set_components(
            scheme.public_id,
            [
                {"component_type": C.ASSIGNMENT, "weight_percentage": D("60")},
                {"component_type": C.FINAL_EXAM, "weight_percentage": D("40")},
            ],
            actor=who,
        )
        return (await svc.activate(scheme.public_id, actor=who)).is_active

    assert _with_scheme(env, fn) is True


def test_thirds_are_tolerated(env) -> None:
    """33.33 x 3 is 99.99, which is a scheme built from thirds and not a
    mistake. Refusing it would send an operator hunting for a missing penny."""
    async def fn(svc, scheme, who, s):  # noqa: ANN001, ANN202
        await svc.set_components(
            scheme.public_id,
            [
                {"component_type": C.ASSIGNMENT, "weight_percentage": D("33.33")},
                {"component_type": C.QUIZ, "weight_percentage": D("33.33")},
                {"component_type": C.FINAL_EXAM, "weight_percentage": D("33.33")},
            ],
            actor=who,
        )
        return (await svc.activate(scheme.public_id, actor=who)).is_active

    assert _with_scheme(env, fn) is True


def test_an_empty_scheme_cannot_be_activated(env) -> None:
    """Every student would score nothing. The migration creates the
    institution default empty on purpose; this is what stops it being switched
    on before somebody has set the weights."""
    async def fn(svc, scheme, who, s):  # noqa: ANN001, ANN202
        with pytest.raises(ValidationError) as refused:
            await svc.activate(scheme.public_id, actor=who)
        return str(refused.value)

    assert "no components" in _with_scheme(env, fn).lower()


def test_a_component_cannot_be_weighted_twice(env) -> None:
    """Two ASSIGNMENT rows make the total ambiguous and the drill-down wrong."""
    async def fn(svc, scheme, who, s):  # noqa: ANN001, ANN202
        with pytest.raises(ValidationError):
            await svc.set_components(
                scheme.public_id,
                [
                    {"component_type": C.ASSIGNMENT, "weight_percentage": D("50")},
                    {"component_type": C.ASSIGNMENT, "weight_percentage": D("50")},
                ],
                actor=who,
            )
        return True

    assert _with_scheme(env, fn)


# ---------------------------------------------------------------- default ---


def test_an_inactive_scheme_cannot_become_the_default(env) -> None:
    """Otherwise every course without an override would be graded under a
    scheme nobody had finished configuring."""
    async def fn(svc, scheme, who, s):  # noqa: ANN001, ANN202
        with pytest.raises(ConflictError):
            await svc.make_default(scheme.public_id, actor=who)
        return True

    assert _with_scheme(env, fn)


def test_handing_over_the_default_leaves_exactly_one(env) -> None:
    """The database permits one, so the previous default has to be cleared in
    the same transaction -- setting the new one first would be refused."""
    def f(s):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            who = await env.actor(s)
            svc = GradingSchemeService(s)
            before = await svc.default_scheme()

            scheme = await svc.create(actor=who, name=f"{env.tag} takeover")
            await svc.set_components(
                scheme.public_id,
                [{"component_type": C.ASSIGNMENT, "weight_percentage": D("100")}],
                actor=who,
            )
            await svc.activate(scheme.public_id, actor=who)
            await svc.make_default(scheme.public_id, actor=who)
            await s.flush()

            count = (
                await s.execute(
                    text("SELECT count(*) FROM grading_schemes WHERE is_default")
                )
            ).scalar_one()
            now_default = await svc.default_scheme()
            # Put the institution's own default back: this test runs against
            # the shared development database, and leaving a test scheme as the
            # default would change how every other test grades.
            if before is not None:
                await svc.make_default(before.public_id, actor=who)
            return count, now_default.name
        return go()

    count, name = env.run(f)
    assert count == 1
    assert name == f"{env.tag} takeover"


# ------------------------------------------------------------------ bands ---


def test_overlapping_bands_are_refused(env) -> None:
    """80 falling into both "A" and "B" makes the grade depend on row order."""
    async def fn(svc, scheme, who, s):  # noqa: ANN001, ANN202
        with pytest.raises(ValidationError) as refused:
            await svc.set_bands(
                scheme.public_id,
                [
                    {"min_score": D("70"), "max_score": D("85"), "letter_grade": "B",
                     "gpa_points": D("3")},
                    {"min_score": D("80"), "max_score": D("100"), "letter_grade": "A",
                     "gpa_points": D("4")},
                ],
                actor=who,
            )
        return str(refused.value)

    assert "overlap" in _with_scheme(env, fn).lower()


def test_adjacent_bands_are_fine(env) -> None:
    """69.99 / 70 is the ordinary way to write a ladder, and must not be read
    as an overlap."""
    async def fn(svc, scheme, who, s):  # noqa: ANN001, ANN202
        row = await svc.set_bands(
            scheme.public_id,
            [
                {"min_score": D("70"), "max_score": D("100"), "letter_grade": "A",
                 "gpa_points": D("4")},
                {"min_score": D("0"), "max_score": D("69.99"), "letter_grade": "F",
                 "gpa_points": D("0"), "is_pass": False},
            ],
            actor=who,
        )
        return len(row.bands)

    assert _with_scheme(env, fn) == 2


# ---------------------------------------------------------------- defaults ---


def test_a_new_scheme_is_never_the_default_or_active(env) -> None:
    """A new scheme silently taking over every course would re-grade the
    institution by accident."""
    async def fn(svc, scheme, who, s):  # noqa: ANN001, ANN202
        return scheme.is_default, scheme.is_active

    is_default, _ = _with_scheme(env, fn)
    assert is_default is False

"""Which grading scheme a batch is graded under: its own, its course's, or the default.

The order is the whole feature, so each step is tested with the one above and
below it present -- a fixture with only one override cannot tell "batch wins"
from "course wins". Results (`PerformanceService`), the grade distribution and
the assignment routes all go through `GradingSchemeService.resolve`; the tests
read each of them, because a second copy of the rule is how they would drift.
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
from backend.services.grading_scheme_service import GradingSchemeService, SchemeSource
from backend.services.performance_service import PerformanceService
from backend.services.report_service import ReportService
from backend.utils.enums import GradeComponentType as C

D = Decimal


@pytest.fixture()
def env():
    tag = "gsa" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="scheme-assign-tests")

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def setup(s):  # noqa: ANN001, ANN202
        who = (await s.execute(select(User).where(User.username == "superadmin"))).scalar_one()
        svc = GradingSchemeService(s)

        async def scheme(suffix: str, letter: str, *, activate: bool = True):  # noqa: ANN202
            row = await svc.create(actor=who, name=f"{tag} {suffix}")
            await svc.set_components(
                row.public_id,
                [{"component_type": C.ASSIGNMENT, "weight_percentage": D("100")}],
                actor=who,
            )
            # A letter unique to each scheme, so a distribution says which one it used.
            await svc.set_bands(
                row.public_id,
                [{"min_score": D("0"), "max_score": D("100"), "letter_grade": letter,
                  "gpa_points": D("0"), "is_pass": True}],
                actor=who,
            )
            if activate:
                await svc.activate(row.public_id, actor=who)
            return row

        course_scheme = await scheme("course", "CC")
        batch_scheme = await scheme("batch", "BB")
        inactive = await scheme("inactive", "II", activate=False)
        course_id = (await s.execute(text(
            "INSERT INTO courses (title, public_id, status) VALUES (:t, :p, 'PUBLISHED') RETURNING id"),
            {"t": f"{tag} course", "p": uuid.uuid4()})).scalar_one()
        ids = []
        for code in ("A", "B"):
            ids.append((await s.execute(text(
                "INSERT INTO batches (batch_code, course_id, public_id) VALUES (:c, :cid, :p) RETURNING id, public_id"),
                {"c": f"{tag}-{code}", "cid": course_id, "p": uuid.uuid4()})).one())
        course_pid = (await s.execute(text("SELECT public_id FROM courses WHERE id = :i"), {"i": course_id})).scalar_one()
        return dict(
            course_id=course_id, course_pid=course_pid,
            a=ids[0][0], a_pid=ids[0][1], b=ids[1][0], b_pid=ids[1][1],
            course_scheme=course_scheme.public_id, batch_scheme=batch_scheme.public_id,
            inactive=inactive.public_id, inactive_id=inactive.id,
        )

    ns = type("Env", (), dict(tag=tag, run=staticmethod(run)))
    ns.ids = run(setup)
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"t": f"{tag}%"}
                inner = "(SELECT id FROM grading_schemes WHERE name LIKE :t)"
                await s.execute(text("DELETE FROM batches WHERE batch_code LIKE :t"), p)
                await s.execute(text("DELETE FROM courses WHERE title LIKE :t"), p)
                await s.execute(text(f"DELETE FROM grade_bands WHERE scheme_id IN {inner}"), p)
                await s.execute(text(f"DELETE FROM grading_scheme_components WHERE scheme_id IN {inner}"), p)
                await s.execute(text("DELETE FROM grading_schemes WHERE name LIKE :t"), p)
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


async def _who(s):  # noqa: ANN001, ANN202
    return (await s.execute(select(User).where(User.username == "superadmin"))).scalar_one()


def _names(env, s_fn):  # noqa: ANN001, ANN202
    """Resolve both batches and return (name, source) pairs."""
    i = env.ids

    async def fn(s):  # noqa: ANN001, ANN202
        await s_fn(s)
        svc = GradingSchemeService(s)
        out = []
        for bid in (i["a"], i["b"]):
            row, source = await svc.resolve(course_id=i["course_id"], batch_id=bid)
            out.append((row.name if row else None, source))
        return out
    return env.run(fn)


def test_a_batch_scheme_beats_its_course_and_the_course_beats_the_default(env) -> None:
    i, tag = env.ids, env.tag

    async def assign(s):  # noqa: ANN001, ANN202
        svc, who = GradingSchemeService(s), await _who(s)
        await svc.assign_to_course(i["course_pid"], i["course_scheme"], actor=who)
        await svc.assign_to_batch(i["a_pid"], i["batch_scheme"], actor=who)

    (a_name, a_src), (b_name, b_src) = _names(env, assign)
    assert (a_name, a_src) == (f"{tag} batch", SchemeSource.BATCH)
    assert (b_name, b_src) == (f"{tag} course", SchemeSource.COURSE)


def test_clearing_falls_back_one_level_at_a_time(env) -> None:
    i, tag = env.ids, env.tag

    async def assign_then_clear_batch(s):  # noqa: ANN001, ANN202
        svc, who = GradingSchemeService(s), await _who(s)
        await svc.assign_to_course(i["course_pid"], i["course_scheme"], actor=who)
        await svc.assign_to_batch(i["a_pid"], i["batch_scheme"], actor=who)
        await svc.assign_to_batch(i["a_pid"], None, actor=who)

    (a_name, a_src), _ = _names(env, assign_then_clear_batch)
    assert (a_name, a_src) == (f"{tag} course", SchemeSource.COURSE)

    async def clear_course(s):  # noqa: ANN001, ANN202
        await GradingSchemeService(s).assign_to_course(i["course_pid"], None, actor=await _who(s))

    (a_name, a_src), _ = _names(env, clear_course)
    assert a_src in (SchemeSource.DEFAULT, SchemeSource.NONE)
    assert a_name is None or not a_name.startswith(tag)


def test_an_inactive_scheme_cannot_be_assigned(env) -> None:
    i = env.ids

    async def fn(s):  # noqa: ANN001, ANN202
        svc, who = GradingSchemeService(s), await _who(s)
        for call in (
            lambda: svc.assign_to_course(i["course_pid"], i["inactive"], actor=who),
            lambda: svc.assign_to_batch(i["a_pid"], i["inactive"], actor=who),
        ):
            with pytest.raises(ConflictError):
                await call()
        return True

    assert env.run(fn)


def test_an_override_to_an_inactive_scheme_is_skipped(env) -> None:
    """A row written some other way (a script, a restore) must not grade anyone
    under weights that were never checked."""
    i, tag = env.ids, env.tag

    async def write_directly(s):  # noqa: ANN001, ANN202
        await GradingSchemeService(s).assign_to_course(i["course_pid"], i["course_scheme"], actor=await _who(s))
        await s.execute(text("UPDATE batches SET grading_scheme_id = :g WHERE id = :b"),
                        {"g": i["inactive_id"], "b": i["a"]})

    (a_name, a_src), _ = _names(env, write_directly)
    assert (a_name, a_src) == (f"{tag} course", SchemeSource.COURSE)


def test_results_are_computed_under_the_batch_scheme(env) -> None:
    """The engine, not just the resolver: a transcript records the scheme it was computed under."""
    i, tag = env.ids, env.tag

    async def fn(s):  # noqa: ANN001, ANN202
        svc, who = GradingSchemeService(s), await _who(s)
        await svc.assign_to_course(i["course_pid"], i["course_scheme"], actor=who)
        await svc.assign_to_batch(i["a_pid"], i["batch_scheme"], actor=who)
        perf = PerformanceService(s)
        a = await perf.for_transcript(student_id=who.id, batch_id=i["a"])
        b = await perf.for_transcript(student_id=who.id, batch_id=i["b"])
        return a.scheme_name, b.scheme_name

    assert env.run(fn) == (f"{tag} batch", f"{tag} course")


def test_a_distribution_uses_the_batch_scheme_and_refuses_a_mixed_course(env) -> None:
    i = env.ids

    async def fn(s):  # noqa: ANN001, ANN202
        svc, who = GradingSchemeService(s), await _who(s)
        await svc.assign_to_course(i["course_pid"], i["course_scheme"], actor=who)
        reports = ReportService(s)
        whole = await reports.distribution(actor=who, course_id=i["course_pid"])
        await svc.assign_to_batch(i["a_pid"], i["batch_scheme"], actor=who)
        a = await reports.distribution(actor=who, batch_id=i["a_pid"])
        b = await reports.distribution(actor=who, batch_id=i["b_pid"])
        with pytest.raises(ValidationError):
            await reports.distribution(actor=who, course_id=i["course_pid"])
        letters = lambda r: [row.key for row in r.rows if row.key != "UNASSESSED"]  # noqa: E731
        return letters(whole), letters(a), letters(b)

    whole, a, b = env.run(fn)
    assert whole == ["CC"]
    assert a == ["BB"]
    assert b == ["CC"]


def test_assigning_is_audited_with_what_it_replaced(env) -> None:
    i, tag = env.ids, env.tag

    async def fn(s):  # noqa: ANN001, ANN202
        svc, who = GradingSchemeService(s), await _who(s)
        await svc.assign_to_batch(i["a_pid"], i["batch_scheme"], actor=who)
        await svc.assign_to_batch(i["a_pid"], i["course_scheme"], actor=who)
        await s.flush()  # audit rows are staged; a text() query does not autoflush
        return (await s.execute(text(
            "SELECT details FROM audit_logs WHERE entity_type = 'batch' AND entity_id = :b"),
            {"b": i["a"]})).scalars().all()

    details = env.run(fn)
    assert {"grading_scheme": f"{tag} batch", "previous": None} in details
    assert {"grading_scheme": f"{tag} course", "previous": f"{tag} batch"} in details

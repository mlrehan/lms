"""Every notification type in the catalogue must have something that sends it.

A type in `notification_types.py` is not inert the way an unused constant is.
It is **listed on the preferences screen**, so a person is offered a switch
for "An examination result was published" and told they can turn it off --
when nothing in the system has ever sent one. That is a promise the product
does not keep, and it is invisible: no error, no failing request, nothing in a
log.

Three types shipped that way and went unnoticed until an audit counted
emitters: `grade_recorded`, `exam_result_published` and `guardian_linked`.
Quizzes and exams sent nothing at all.

This is the same shape as the stored-but-never-read column that keeps
appearing in this codebase -- a field that looks like a feature because
something renders it. The guard is cheap: scan the source for an emission of
each code.

**Deliberately a source scan, not a mock.** Driving every publish path
through a database would be a far better test of *behaviour*, and it is not
what this guards: the failure here is a type with no call site anywhere, which
only a whole-tree search can see.
"""

from __future__ import annotations

import ast
import pathlib

from backend.core.notification_types import ALL_TYPES

_ROOT = pathlib.Path(__file__).resolve().parents[2] / "backend"
# Where a notification may legitimately be raised from. The catalogue module
# itself is excluded: declaring a type is not sending one.
_EMITTER_DIRS = ("services", "api", "tasks", "workers")


def _emitted_attribute_names() -> set[str]:
    """`NotificationType.X` attribute names referenced anywhere in the backend.

    Parsed rather than grepped so that a mention inside a docstring or a
    comment cannot satisfy the guard -- the whole failure mode here is
    something that *looks* wired up.
    """
    names: set[str] = set()
    for directory in _EMITTER_DIRS:
        base = _ROOT / directory
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - a broken file fails elsewhere
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    if node.value.id == "NotificationType":
                        names.add(node.attr)
    return names


def _declared_codes_by_attribute() -> dict[str, str]:
    from backend.core.notification_types import NotificationType

    return {
        name: value
        for name, value in vars(NotificationType).items()
        if not name.startswith("_") and isinstance(value, str)
    }


def test_every_catalogue_type_has_an_emitter() -> None:
    declared = _declared_codes_by_attribute()
    emitted = _emitted_attribute_names()

    unsent = sorted(
        code for attr, code in declared.items() if attr not in emitted
    )
    assert not unsent, (
        "These notification types are offered on the preferences screen and "
        f"nothing sends them: {unsent}. Either emit them or remove them from "
        "the catalogue -- a switch for a notification that never arrives is "
        "worse than no switch."
    )


def test_the_scan_actually_finds_emitters() -> None:
    """A meta-test, because the scan above passes vacuously if it finds nothing.

    The first version of a guard like this is quite capable of searching the
    wrong directory and reporting a clean bill of health for every type at
    once.
    """
    emitted = _emitted_attribute_names()
    assert len(emitted) >= 10, (
        f"Only {len(emitted)} emitted type(s) found; the scan is probably "
        "looking in the wrong place."
    )
    assert "ASSIGNMENT_PUBLISHED" in emitted


def test_catalogue_describes_every_declared_code() -> None:
    """The import-time check, asserted rather than trusted to run."""
    declared = set(_declared_codes_by_attribute().values())
    assert declared == set(ALL_TYPES), sorted(declared ^ set(ALL_TYPES))

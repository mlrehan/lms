"""Which editor a course needs, and who is offered it.

The rule this file protects is **a course's own rows replace its category's,
they do not add to them**. Without that, "this course is in the SQL category
but needs no editor" is inexpressible: an empty override would read as "nothing
set" and the course would inherit the very thing it was overriding.

The resolution is exercised through `EditorService._editors_for` against fake
rows rather than a database, because the question here is the precedence rule
and not whether SQLAlchemy can run a join.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from backend.services.editor_service import EDITORS, EditorService


@dataclass
class _Result:
    """Stands in for a SQLAlchemy result: iterable of row tuples."""

    rows: list[tuple]

    def __iter__(self):  # noqa: ANN204
        return iter(self.rows)

    def scalars(self):  # noqa: ANN201
        return [r[0] for r in self.rows]


class _FakeSession:
    """Answers the two SELECTs `_editors_for` makes, in order."""

    def __init__(self, overrides: list[tuple[int, str]], inherited: list[tuple[int, str]]) -> None:
        self._answers = [_Result(overrides), _Result(inherited)]

    async def execute(self, *_args, **_kwargs):  # noqa: ANN202
        return self._answers.pop(0)


def resolve(course_ids: set[int], *, overrides: list[tuple[int, str]], inherited: list[tuple[int, str]]) -> set[str]:
    service = EditorService(_FakeSession(overrides, inherited))  # type: ignore[arg-type]
    return asyncio.run(service._editors_for(course_ids))


class TestPrecedence:
    def test_a_course_with_no_rows_inherits_its_category(self) -> None:
        assert resolve({1}, overrides=[], inherited=[(1, "python")]) == {"python"}

    def test_a_course_with_its_own_rows_ignores_its_category(self) -> None:
        """The SQL-category course that actually teaches Python."""
        assert resolve(
            {1}, overrides=[(1, "python")], inherited=[(1, "sql")]
        ) == {"python"}

    def test_a_course_can_state_that_it_needs_both(self) -> None:
        assert resolve(
            {1}, overrides=[(1, "sql"), (1, "python")], inherited=[(1, "sql")]
        ) == {"sql", "python"}

    def test_courses_are_resolved_independently(self) -> None:
        """One override must not suppress another course's inheritance."""
        assert resolve(
            {1, 2},
            overrides=[(1, "python")],
            inherited=[(1, "sql"), (2, "sql")],
        ) == {"python", "sql"}

    def test_an_uncategorised_course_with_no_override_needs_nothing(self) -> None:
        """Thirteen courses are in this state today. Silence, not a guess."""
        assert resolve({9}, overrides=[], inherited=[]) == set()


class TestTheVocabulary:
    def test_only_editors_this_build_can_open_are_offered(self) -> None:
        """The column's CHECK constraint names these two. A third key would be
        a menu item pointing nowhere."""
        assert set(EDITORS) == {"sql", "python"}

    @pytest.mark.parametrize("key", ["sql", "python"])
    def test_each_editor_has_a_label_and_an_https_address(self, key: str) -> None:
        assert EDITORS[key]["label"]
        assert EDITORS[key]["url"].startswith("https://")

    def test_the_two_editors_are_not_the_same_place(self) -> None:
        assert EDITORS["sql"]["url"] != EDITORS["python"]["url"]


class TestForUser:
    def test_unrestricted_admin_gets_all_editors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Platform administrators are always offered all platform developer tools."""
        service = EditorService(_FakeSession([], []))  # type: ignore[arg-type]

        async def _mock_unrestricted(_actor):  # noqa: ANN001, ANN202
            return None

        monkeypatch.setattr(service, "_working_course_ids", _mock_unrestricted)

        links = asyncio.run(service.for_user(actor=None))  # type: ignore[arg-type]
        assert [l.key for l in links] == ["sql", "python"]
        assert links[0].label == "SQL Editor"
        assert links[1].label == "Python Editor"

    def test_user_with_no_working_courses_gets_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        service = EditorService(_FakeSession([], []))  # type: ignore[arg-type]

        async def _mock_empty(_actor):  # noqa: ANN001, ANN202
            return set()

        monkeypatch.setattr(service, "_working_course_ids", _mock_empty)

        links = asyncio.run(service.for_user(actor=None))  # type: ignore[arg-type]
        assert links == []

    def test_student_gets_only_their_course_editor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        service = EditorService(_FakeSession([], [(1, "sql")]))  # type: ignore[arg-type]

        async def _mock_student(_actor):  # noqa: ANN001, ANN202
            return {1}

        monkeypatch.setattr(service, "_working_course_ids", _mock_student)

        links = asyncio.run(service.for_user(actor=None))  # type: ignore[arg-type]
        assert [l.key for l in links] == ["sql"]
        assert links[0].label == "SQL Editor"

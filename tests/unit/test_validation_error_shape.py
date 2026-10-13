"""A rejected field reaches the person who typed it.

The console reads `{"code", "message", "details"}` -- the envelope every
`AppError` already uses -- and FastAPI's own 422 is `{"detail": [...]}`. With
nothing bridging the two, `ApiError` found no `message` and fell back to its
status default, so **every** invalid form in the application said "The request
could not be completed." The reason was computed, serialised, and discarded at
the last step.

That mattered most for the link fields, whose whole purpose is to explain
*why* a link cannot be used, but it was never specific to them.
"""

from __future__ import annotations

import asyncio
import json

from fastapi.exceptions import RequestValidationError

from backend.main import validation_error_handler


def _handled(exc: RequestValidationError) -> dict:
    """Run the handler the way the application will, and read its body.

    The project has no pytest-asyncio; every other async test here drives a
    loop by hand, so this does the same rather than adding a plugin.
    """
    response = asyncio.run(validation_error_handler(None, exc))
    return json.loads(bytes(response.body).decode())


def test_a_rejected_field_is_named_and_explained() -> None:
    exc = RequestValidationError(
        [
            {
                "type": "value_error",
                "loc": ("body", "recording_link"),
                "msg": "Value error, Only links beginning http:// or https:// can be used.",
                "input": "javascript:alert(1)",
            }
        ]
    )
    body = _handled(exc)

    assert body["code"] == "VALIDATION_ERROR"
    # `Value error, ` is pydantic's prefix, not something to show a tutor.
    assert body["message"].startswith("Only links beginning")
    assert body["details"] == {
        "recording_link": "Only links beginning http:// or https:// can be used."
    }


def test_a_nested_field_keeps_a_path_a_form_can_match() -> None:
    exc = RequestValidationError(
        [
            {
                "type": "int_type",
                "loc": ("body", "entries", 0, "marks_obtained"),
                "msg": "Input should be a valid integer",
                "input": None,
            }
        ]
    )
    body = _handled(exc)
    assert "entries.0.marks_obtained" in body["details"]


def test_the_first_problem_becomes_the_headline() -> None:
    """A banner shows one sentence; the rest stay in `details` for the fields."""
    exc = RequestValidationError(
        [
            {"type": "missing", "loc": ("body", "title"), "msg": "Field required", "input": None},
            {"type": "missing", "loc": ("body", "due_date"), "msg": "Field required", "input": None},
        ]
    )
    body = _handled(exc)
    assert body["message"] == "Field required"
    assert set(body["details"]) == {"title", "due_date"}


def test_an_error_with_no_usable_message_still_says_something() -> None:
    exc = RequestValidationError([{"type": "x", "loc": ("body", "thing"), "msg": "", "input": None}])
    body = _handled(exc)
    assert body["details"]["thing"]
    assert body["message"]

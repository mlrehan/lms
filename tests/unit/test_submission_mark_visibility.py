"""A mark reaches a student only once it is released.

`_submission_response` used to return grade and feedback whatever the state,
so "Graded, not released" was a badge rather than a fact: a student re-marked
from 17 to 18 read the 18 before anybody released it, through the same
`/submissions` listing the console uses.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.api.v1.assignments import _submission_response
from backend.utils.enums import SubmissionState


def _row(state: SubmissionState) -> SimpleNamespace:
    person = SimpleNamespace(id=7, public_id=uuid.uuid4(), first_name="Liva", last_name="Student", username="liva", email="l@x.test")
    now = datetime.now(UTC)
    return SimpleNamespace(
        public_id=uuid.uuid4(), assignment=SimpleNamespace(public_id=uuid.uuid4(), title="Loops", due_date=None),
        student=person, grader=person, submitted_at=now, content="answer", grade=Decimal("18"),
        feedback="Good.", graded_at=now, state=state, attempt_number=1, raw_grade=Decimal("18"),
        late_penalty_applied=Decimal("0"), published_at=None, override_reason="second marker", overridden_at=now,
    )


@pytest.mark.parametrize("state", [SubmissionState.GRADED, SubmissionState.UNDER_REVIEW])
def test_an_unreleased_mark_is_withheld_from_a_student(state: SubmissionState) -> None:
    out = _submission_response(_row(state), staff=False)
    assert out.state == state  # that it is marked is not the secret
    assert (out.grade, out.feedback, out.raw_grade, out.graded_at, out.graded_by_username) == (None, None, None, None, None)
    assert out.override_reason is None


def test_a_released_mark_reaches_the_student_without_the_override_trail() -> None:
    out = _submission_response(_row(SubmissionState.PUBLISHED), staff=False)
    assert out.grade == Decimal("18") and out.feedback == "Good."
    assert out.override_reason is None and out.overridden_at is None


def test_a_marker_sees_an_unreleased_mark() -> None:
    out = _submission_response(_row(SubmissionState.GRADED), staff=True)
    assert out.grade == Decimal("18") and out.feedback == "Good." and out.override_reason == "second marker"

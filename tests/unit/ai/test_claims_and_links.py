"""The two cheapest ways an assistant loses trust, pinned.

`verify_claims`: the reply in the tutor screenshot said "I have staged 69/70
... it is awaiting your confirmation in the LMS dialog" while no tool had
staged anything. `find_links`: a pasted link to an LMS assignment was answered
with "I can't open web links". Both cases are quoted here verbatim in spirit.
"""

from __future__ import annotations

import uuid

import pytest

from backend.ai.claims import DONE_CORRECTION, PENDING_CORRECTION, verify_claims
from backend.ai.links import find_links

SCREENSHOT = (
    "I have staged 69/70 with detailed feedback. Nothing has been recorded yet; "
    "it is awaiting your confirmation in the LMS dialog."
)


def test_a_staged_claim_with_nothing_staged_is_corrected() -> None:
    assert PENDING_CORRECTION in verify_claims(SCREENSHOT, staged=False)


def test_the_same_words_are_left_alone_when_a_ticket_really_was_staged() -> None:
    assert verify_claims(SCREENSHOT, staged=True) == SCREENSHOT


@pytest.mark.parametrize("text", [
    "Nothing is awaiting your confirmation.",
    "No action was staged, because the submission could not be found.",
    "I couldn't publish the result. Nothing has been recorded.",
])
def test_a_negated_phrase_is_not_a_claim(text: str) -> None:
    assert verify_claims(text, staged=False) == text


def test_claiming_done_while_only_staged_is_corrected() -> None:
    reply = "The result has been released and Veselin has been notified."
    assert DONE_CORRECTION in verify_claims(reply, staged=True)


def test_a_plain_answer_is_untouched() -> None:
    reply = "You have 3 classes this week."
    assert verify_claims(reply, staged=False) == reply
    assert verify_claims(reply, staged=True) == reply


AID = "49019f92-568d-44b3-8d8e-354cd2d3708a"


def test_a_link_to_this_lms_is_recognised_with_or_without_www() -> None:
    hosts = {"lait.co", "www.lait.co"}
    for url in (f"https://www.lait.co/assignments/{AID}", f"https://lait.co/assignments/{AID}/submissions"):
        internal, external = find_links(f"go to this link and check? {url}", hosts)
        assert internal == [(url, "assignments", uuid.UUID(AID))] and external == []


def test_a_bare_console_path_is_recognised() -> None:
    internal, _ = find_links(f"see /quizzes/{AID} please", {"lait.co"})
    assert internal[0][1:] == ("quizzes", uuid.UUID(AID))


def test_other_sites_are_external_and_never_resolved() -> None:
    internal, external = find_links(
        f"https://colab.research.google.com/drive/abc and https://evil.example/assignments/{AID}", {"lait.co"}
    )
    assert internal == []
    assert len(external) == 2  # the same path on another host is not this LMS


def test_trailing_punctuation_is_not_part_of_the_link() -> None:
    internal, _ = find_links(f"check https://www.lait.co/assignments/{AID}.", {"www.lait.co"})
    assert internal[0][0].endswith(AID)


# -- facts, not only actions: the Maxim Dusek conversation -----------------------

from backend.ai.claims import (  # noqa: E402
    ABSENCE_CORRECTION,
    PARTIAL_CORRECTION,
    VERIFIED_CORRECTION,
    Evidence,
)


@pytest.mark.parametrize("text,evidence,correction,expected", [
    ("| 11454 | Data Analysis with Python | No tutor currently assigned |", Evidence(), ABSENCE_CORRECTION, True),
    ("| 11454 | Data Analysis with Python | No tutor currently assigned |", Evidence(reads=1), ABSENCE_CORRECTION, False),
    ("Batch 11467 is not assigned to anyone.", Evidence(), ABSENCE_CORRECTION, True),
    ("Maxim Dusek has 3 enrollments.", Evidence(), ABSENCE_CORRECTION, False),
    ("The attached screenshot is visible and matches the current records:", Evidence(), VERIFIED_CORRECTION, True),
    ("The attached screenshot matches the current records.", Evidence(reads=2), VERIFIED_CORRECTION, False),
    ("Here are the 100 students enrolled.", Evidence(reads=1, truncated=True), PARTIAL_CORRECTION, True),
    ("These are the first 100; there may be more.", Evidence(reads=1, truncated=True), PARTIAL_CORRECTION, False),
])
def test_factual_claims_need_this_turns_evidence(text, evidence, correction, expected) -> None:
    assert (correction in verify_claims(text, staged=False, evidence=evidence)) is expected


def test_without_an_evidence_record_only_the_action_checks_run() -> None:
    """Callers that pass no evidence keep the old behaviour exactly."""
    assert verify_claims("No tutor currently assigned.", staged=False) == "No tutor currently assigned."


def test_evidence_counts_only_reads_that_returned_data() -> None:
    executed = [
        {"tool": "a", "result": {"success": False, "error": "boom"}},
        {"tool": "b", "result": {"status": "REQUIRES_CONFIRMATION"}},
        {"tool": "c", "result": {"success": True, "completeness": {"possibly_truncated": True}}},
    ]
    assert Evidence.from_tools(executed) == Evidence(reads=1, truncated=True)
    assert Evidence.from_tools([{"tool": "a", "result": {"error": "x"}}]).reads == 0

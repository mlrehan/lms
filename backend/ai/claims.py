"""Checking what the assistant says it did against what actually happened.

The model writes the reply; the server knows the facts. A reply can say "I
have staged the mark -- it is awaiting your confirmation" when no tool staged
anything, or "the result has been released" when the release is only staged
and waiting for a click. Both happened live, and both are the worst kind of
error for an assistant people delegate work to: the person believes something
was done, or is pending, when it was not.

This compares two claims with the turn's own record and appends a plain
correction when they disagree. It never rewrites the model's text -- the
correction is visibly the system's -- and it errs towards silence: a phrase is
only treated as a claim when it is not negated ("nothing is awaiting your
confirmation" is not a claim that something is).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# "... awaiting your confirmation", "staged ... for confirmation", "confirm in the dialog"
_PENDING = re.compile(
    r"\b(?:awaiting|waiting for|pending)\s+(?:your\s+)?(?:confirmation|approval)\b"
    r"|\b(?:i(?:'ve| have)?\s+)?staged\b"
    r"|\bconfirm(?:ation)?\s+(?:it\s+)?in\s+the\s+(?:lms\s+)?(?:confirmation\s+)?dialog\b",
    re.IGNORECASE,
)
# "... has been released / was recorded / have been sent" -- done, in the past.
_DONE = re.compile(
    r"\b(?:has|have)\s+(?:now\s+)?been\s+(?:recorded|released|published|sent|saved|enrolled|posted|marked|updated|deleted)\b"
    r"|\b(?:successfully|now)\s+(?:recorded|released|published|sent|saved|enrolled|posted)\b",
    re.IGNORECASE,
)
_NEGATION = re.compile(r"\b(?:no|not|nothing|never|isn't|aren't|wasn't|hasn't|haven't)\b[^.!?\n]{0,40}$", re.IGNORECASE)

PENDING_CORRECTION = (
    "Correction from the system: nothing is awaiting your confirmation. No action was staged in this reply, "
    "so nothing will be saved or sent unless you ask again."
)
DONE_CORRECTION = (
    "Correction from the system: this has NOT been carried out yet. It is waiting for your confirmation in the "
    "dialog, and nothing changes until you confirm."
)


def _claims(pattern: re.Pattern[str], text: str) -> bool:
    for match in pattern.finditer(text):
        before = text[max(0, match.start() - 60):match.start()]
        sentence_start = max(before.rfind("."), before.rfind("!"), before.rfind("?"), before.rfind("\n"))
        if not _NEGATION.search(before[sentence_start + 1:]):
            return True
    return False


# Facts, not actions. The Maxim Dusek conversation produced all three of these:
# "No tutor currently assigned" from a join that simply found nothing, then
# "the attached screenshot ... matches the current records" with no lookup at
# all. A reply may say these things only when this turn read something.
_ABSENCE = re.compile(
    r"\b(?:no|without\s+(?:a|any))\s+(?:\w+\s+){0,2}(?:tutors?|teachers?|enrol?lments?|students?|submissions?|"
    r"sessions?|classes|records?|marks?|grades?)\s+(?:currently\s+|yet\s+)?(?:assigned|found|recorded|enrolled|scheduled)\b"
    r"|\b(?:is|are)\s+(?:currently\s+)?(?:unassigned|not\s+assigned)\b"
    r"|\bno\s+tutor\b"
    r"|\b(?:has|have)\s+no\s+(?:tutors?|enrol?lments?|submissions?|classes|sessions?|records?)\b",
    re.IGNORECASE,
)
_VERIFIED = re.compile(
    r"\bmatch(?:es|ing)?\s+(?:the\s+)?(?:current\s+)?(?:lms\s+|database\s+|platform\s+)?records\b"
    r"|\b(?:verified|confirmed|checked)\s+(?:it\s+)?(?:against|with|in)\s+(?:the\s+)?(?:current\s+)?"
    r"(?:lms|database|records|platform|system)\b"
    r"|\bconsistent\s+with\s+(?:the\s+)?(?:current\s+)?(?:lms|database|records)\b",
    re.IGNORECASE,
)
_ADMITS_PARTIAL = re.compile(
    r"\b(?:may be more|might be more|not (?:a )?complete|incomplete|partial|truncated|at least|first \d+|limit)\b",
    re.IGNORECASE,
)

ABSENCE_CORRECTION = (
    "Correction from the system: no record was read in this reply, so a statement that something is absent "
    "(\"no tutor\", \"not assigned\", \"none found\") is not verified. Ask again and it will be looked up."
)
VERIFIED_CORRECTION = (
    "Correction from the system: nothing was looked up in this reply, so it has NOT been checked against the "
    "current records. An attachment or an earlier answer is not a verification."
)
PARTIAL_CORRECTION = (
    "Correction from the system: a lookup in this reply hit its row limit, so the list or count above may be "
    "incomplete."
)


@dataclass(frozen=True)
class Evidence:
    """What this turn actually read. `reads` counts tool results that returned data."""

    reads: int = 0
    truncated: bool = False

    @classmethod
    def from_tools(cls, executed: list[dict[str, Any]]) -> "Evidence":
        reads, truncated = 0, False
        for call in executed:
            result = call.get("result")
            if not isinstance(result, dict):
                continue
            if result.get("status") == "REQUIRES_CONFIRMATION" or result.get("success") is False or result.get("error"):
                continue
            reads += 1
            completeness = result.get("completeness") or {}
            if completeness.get("possibly_truncated") or completeness.get("truncated"):
                truncated = True
        return cls(reads=reads, truncated=truncated)


def verify_claims(text: str, *, staged: bool, evidence: Evidence | None = None) -> str:
    """`text` with a correction appended when it misstates what this turn did.

    `staged` is whether a tool in this turn returned REQUIRES_CONFIRMATION;
    `evidence` is what the turn read (omitted: the factual checks are skipped).
    """
    if not text:
        return text
    if not staged and _claims(_PENDING, text):
        return f"{text}\n\n> {PENDING_CORRECTION}"
    if staged and _claims(_DONE, text):
        return f"{text}\n\n> {DONE_CORRECTION}"
    if evidence is None:
        return text
    notes = []
    if evidence.reads == 0 and _ABSENCE.search(text):
        notes.append(ABSENCE_CORRECTION)
    if evidence.reads == 0 and _VERIFIED.search(text):
        notes.append(VERIFIED_CORRECTION)
    if evidence.truncated and not _ADMITS_PARTIAL.search(text):
        notes.append(PARTIAL_CORRECTION)
    return text + "".join(f"\n\n> {n}" for n in notes)

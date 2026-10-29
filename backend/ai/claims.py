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


def verify_claims(text: str, *, staged: bool) -> str:
    """`text` with a correction appended when it misstates what this turn did.

    `staged` is whether a tool in this turn returned REQUIRES_CONFIRMATION.
    """
    if not text:
        return text
    if not staged and _claims(_PENDING, text):
        return f"{text}\n\n> {PENDING_CORRECTION}"
    if staged and _claims(_DONE, text):
        return f"{text}\n\n> {DONE_CORRECTION}"
    return text

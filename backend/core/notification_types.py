"""The catalogue of notification types (spec §21).

**Single source of truth, exactly like `permissions.py`.** A `type` string is
written by an emitter, stored on the row, listed by the preferences API and
matched by a user's opt-out — four places that must agree. Left as free text
they drift, and the failure is silent in the worst direction: an emitter
inventing `"grade_posted"` while the preferences screen offers
`"grade_recorded"` produces a notification nobody can turn off, and no error
anywhere.

:func:`assert_known` is called by the emitter at runtime and by the
preference validator, and the catalogue is checked for internal consistency
at import time — the same "fail at import, not in production" discipline
`require_permissions` uses.

**Some types are mandatory and cannot be switched off.** You do not get to
opt out of being told that your account was locked or that somebody ended
your sessions: those exist so a person notices a compromise, and a
notification the attacker can suppress by flipping a preference is worse than
none. Everything routine — a grade, a new assignment — is opt-out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class NotificationKind:
    code: str
    category: str
    description: str
    mandatory: bool = False


class NotificationType:
    """Codes an emitter may use. Referenced by name so a typo is an
    `AttributeError` at import rather than a string nobody matches."""

    MESSAGE_RECEIVED: Final = "message_received"
    ASSIGNMENT_PUBLISHED: Final = "assignment_published"
    SUBMISSION_GRADED: Final = "submission_graded"
    GRADE_RECORDED: Final = "grade_recorded"
    QUIZ_PUBLISHED: Final = "quiz_published"
    EXAM_SCHEDULED: Final = "exam_scheduled"
    EXAM_RESULT_PUBLISHED: Final = "exam_result_published"
    QUIZ_RESULT_PUBLISHED: Final = "quiz_result_published"
    ENROLLED_IN_BATCH: Final = "enrolled_in_batch"
    ENROLLMENT_STATUS_CHANGED: Final = "enrollment_status_changed"
    GUARDIAN_LINKED: Final = "guardian_linked"
    MANAGER_LINKED: Final = "manager_linked"
    # A guardian's own copies. Deliberately distinct codes rather than sending a student's type to their
    # guardian: every description below is written in the second person about its subject ("Your submission
    # was graded"), so reusing them would tell a parent that *their* work was marked, and would leave the two
    # audiences sharing one opt-out switch.
    WARD_SUBMISSION_GRADED: Final = "ward_submission_graded"
    WARD_ASSIGNMENT_PUBLISHED: Final = "ward_assignment_published"
    WARD_ENROLLED_IN_BATCH: Final = "ward_enrolled_in_batch"
    WARD_EXAM_RESULT_PUBLISHED: Final = "ward_exam_result_published"
    WARD_QUIZ_RESULT_PUBLISHED: Final = "ward_quiz_result_published"
    ACCOUNT_LOCKED: Final = "account_locked"
    ACCOUNT_UNLOCKED: Final = "account_unlocked"
    SESSIONS_REVOKED: Final = "sessions_revoked"
    PASSWORD_CHANGED: Final = "password_changed"


_KINDS: tuple[NotificationKind, ...] = (
    NotificationKind(
        NotificationType.MESSAGE_RECEIVED, "messages",
        "Somebody sent you a private message.",
    ),
    NotificationKind(
        NotificationType.ASSIGNMENT_PUBLISHED, "coursework",
        "A new assignment was set on one of your courses.",
    ),
    NotificationKind(
        NotificationType.SUBMISSION_GRADED, "coursework",
        "Your assignment submission was graded.",
    ),
    NotificationKind(
        NotificationType.GRADE_RECORDED, "grades",
        "A mark was recorded against your grade book.",
    ),
    NotificationKind(
        NotificationType.QUIZ_PUBLISHED, "coursework",
        "A quiz was opened on one of your courses.",
    ),
    NotificationKind(
        NotificationType.EXAM_SCHEDULED, "coursework",
        "An examination was scheduled on one of your courses.",
    ),
    NotificationKind(
        NotificationType.EXAM_RESULT_PUBLISHED, "grades",
        "An examination result was published.",
    ),
    NotificationKind(
        NotificationType.QUIZ_RESULT_PUBLISHED, "grades",
        "A quiz result was released.",
    ),
    NotificationKind(
        NotificationType.ENROLLED_IN_BATCH, "enrollment",
        "You were enrolled in a batch.",
    ),
    NotificationKind(
        NotificationType.ENROLLMENT_STATUS_CHANGED, "enrollment",
        "The status of one of your enrollments changed.",
    ),
    NotificationKind(
        NotificationType.GUARDIAN_LINKED, "enrollment",
        "A guardian was linked to your account, or you to a student.",
    ),
    NotificationKind(
        NotificationType.MANAGER_LINKED, "enrollment",
        "A corporate manager was linked to your account, or you to a student.",
    ),
    # --- guardians ----------------------------------------------------------
    # "Ward" matches the vocabulary the data model already uses: `User.wards` is the guardian side of
    # `student_guardians`. Each is separately opt-out because their volumes differ by an order of magnitude --
    # a parent may want every grade and no longer want every piece of homework.
    NotificationKind(
        NotificationType.WARD_SUBMISSION_GRADED, "guardian",
        "A student in your care had a submission graded.",
    ),
    NotificationKind(
        NotificationType.WARD_ASSIGNMENT_PUBLISHED, "guardian",
        "A student in your care was set new coursework.",
    ),
    NotificationKind(
        NotificationType.WARD_ENROLLED_IN_BATCH, "guardian",
        "A student in your care was enrolled in a batch.",
    ),
    NotificationKind(
        NotificationType.WARD_QUIZ_RESULT_PUBLISHED, "guardian",
        "A student in your care had a quiz result released.",
    ),
    NotificationKind(
        NotificationType.WARD_EXAM_RESULT_PUBLISHED, "guardian",
        "An examination result was published for a student in your care.",
    ),
    # --- security: mandatory ------------------------------------------------
    # Deliberately not opt-out. These exist so a person notices a compromise,
    # and a warning an attacker can silence by flipping a preference is worse
    # than no warning at all, because it is believed to be working.
    NotificationKind(
        NotificationType.ACCOUNT_LOCKED, "security",
        "Your account was locked after repeated failed sign-in attempts.",
        mandatory=True,
    ),
    NotificationKind(
        NotificationType.ACCOUNT_UNLOCKED, "security",
        "An administrator unlocked your account.",
        mandatory=True,
    ),
    NotificationKind(
        NotificationType.SESSIONS_REVOKED, "security",
        "Your sessions were ended by an administrator.",
        mandatory=True,
    ),
    NotificationKind(
        NotificationType.PASSWORD_CHANGED, "security",
        "Your password was changed.",
        mandatory=True,
    ),
)

ALL_TYPES: Final[dict[str, NotificationKind]] = {k.code: k for k in _KINDS}
OPTIONAL_TYPES: Final[tuple[str, ...]] = tuple(
    k.code for k in _KINDS if not k.mandatory
)
MANDATORY_TYPES: Final[frozenset[str]] = frozenset(
    k.code for k in _KINDS if k.mandatory
)
CATEGORIES: Final[tuple[str, ...]] = tuple(
    dict.fromkeys(k.category for k in _KINDS)
)


def _check_catalogue() -> None:
    """Import-time consistency, so a bad entry fails the build, not a request."""
    codes = [k.code for k in _KINDS]
    duplicates = {c for c in codes if codes.count(c) > 1}
    if duplicates:
        raise RuntimeError(f"Duplicate notification type(s): {sorted(duplicates)}")

    declared = {
        value
        for name, value in vars(NotificationType).items()
        if not name.startswith("_") and isinstance(value, str)
    }
    missing = declared - set(codes)
    if missing:
        raise RuntimeError(
            "NotificationType declares code(s) with no catalogue entry: "
            f"{sorted(missing)}. A type nobody can describe is a type nobody "
            "can opt out of."
        )


_check_catalogue()


def assert_known(code: str) -> NotificationKind:
    """Refuse an unregistered type at the point of emission.

    Raising is right even though it can fail a request that was otherwise
    fine: an unregistered type produces a notification that the preferences
    screen cannot list and the user therefore cannot turn off. Better to fail
    the emit loudly in development than to ship an un-silenceable one.
    """
    kind = ALL_TYPES.get(code)
    if kind is None:
        raise RuntimeError(
            f"Unknown notification type {code!r}. Register it in "
            "backend/core/notification_types.py so it can be described and "
            "opted out of."
        )
    return kind


def is_mandatory(code: str) -> bool:
    kind = ALL_TYPES.get(code)
    return kind.mandatory if kind else False

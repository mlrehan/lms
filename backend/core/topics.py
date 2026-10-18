"""Who, other than one person, needs to be told that something changed.

**In `core` rather than in `realtime`, for the same reason `core/events.py`
is.** This is vocabulary -- which tables belong to which topic, and which
permission admits a connection to one -- not transport. `realtime/bus.py`
imports the event model from here; putting the vocabulary in `realtime` makes
that import a cycle, which is the honest signal that the layering was the wrong
way round.

`core/events.py` addresses an event to a single user, and says why: fan-out
happens where recipients are already being resolved, under audience rules this
layer cannot evaluate. That is exactly right for "your grade was published".

It cannot express "the course list changed", which is what a sidebar badge and
a dashboard figure are counting. Nobody is notified when an administrator adds
a batch, so under the per-user rule alone those numbers can only correct
themselves on the next refetch -- which is the page refresh this module exists
to remove.

**A topic is still a hint, not a payload.** An event carries the topic name and
nothing else: no id, no title, no count. Every subscriber re-reads through the
ordinary endpoint, so `core/privacy.py` and every permission check still decide
what each of them actually sees. That is what makes a shared channel safe here
where a shared channel carrying content would not be.

**Subscription is decided by permission, at connect time, from the token --
never from anything in the request.** A caller who cannot read the directory is
not subscribed to `directory`, so the frames never reach them at all. The
narrowest useful permission is chosen for each topic, because a topic admits
somebody to a *hint* that a table changed, and the real gate is the endpoint
they then call.

**Topics are coarse on purpose.** Four of them, not forty. A finer vocabulary
would mean every new table needing a decision nobody remembers to make, and the
failure mode is a silent one: a badge that never updates. Coarse topics cost an
occasional refetch that finds nothing new, which costs one cached query.
"""

from __future__ import annotations

from typing import Final

from backend.core.permissions import Action, Module, perm

#: Accounts, roles, the permission catalogue, and the relationships that decide
#: who may see whom.
DIRECTORY: Final = "directory"
#: Courses, batches, sessions, enrolments, attendance -- the teaching timetable.
ACADEMIC: Final = "academic"
#: Assignments, quizzes, examinations, marks and transcripts.
ASSESSMENT: Final = "assessment"
#: Announcements, which every role can be shown.
ANNOUNCEMENTS: Final = "announcements"
#: Who is currently connected. Published by the stream itself rather than by a
#: database write, because presence is not stored in the database.
PRESENCE: Final = "presence"

ALL_TOPICS: Final[tuple[str, ...]] = (
    DIRECTORY,
    ACADEMIC,
    ASSESSMENT,
    ANNOUNCEMENTS,
    PRESENCE,
)

#: Which topic a table's rows belong to.
#:
#: Tables absent from this map raise no event at all, which is the correct
#: default: `audit_logs`, `tokens` and `sync_pipeline_jobs` change constantly
#: and no badge counts them. Announcing them would be pure noise multiplied by
#: the number of connected browsers.
#:
#: `notifications` and `mail_messages` are deliberately absent too -- those
#: already have precise per-user events, and a topic would tell everybody that
#: somebody, somewhere, got a message.
TABLE_TOPICS: Final[dict[str, str]] = {
    # -- directory ---------------------------------------------------------
    "users": DIRECTORY,
    "user_roles": DIRECTORY,
    "roles": DIRECTORY,
    "permissions": DIRECTORY,
    "role_permissions": DIRECTORY,
    "organizations": DIRECTORY,
    "organization_managers": DIRECTORY,
    "organization_memberships": DIRECTORY,
    "manager_students": DIRECTORY,
    "student_guardians": DIRECTORY,
    # -- academic ----------------------------------------------------------
    "courses": ACADEMIC,
    "batches": ACADEMIC,
    "batch_sessions": ACADEMIC,
    "enrollments": ACADEMIC,
    "attendances": ACADEMIC,
    "attendance_sheets": ACADEMIC,
    "academic_years": ACADEMIC,
    "semesters": ACADEMIC,
    "departments": ACADEMIC,
    # -- assessment --------------------------------------------------------
    "assignments": ASSESSMENT,
    "assignment_submissions": ASSESSMENT,
    "quizzes": ASSESSMENT,
    "quiz_attempts": ASSESSMENT,
    "exams": ASSESSMENT,
    "exam_results": ASSESSMENT,
    "gradebook_entries": ASSESSMENT,
    "class_performance_marks": ASSESSMENT,
    "transcripts": ASSESSMENT,
    "grading_schemes": ASSESSMENT,
    # -- announcements -----------------------------------------------------
    "announcements": ANNOUNCEMENTS,
}

#: The permission that admits a connection to each topic.
#:
#: Deliberately the *narrowest* one that makes the topic useful, because being
#: subscribed only ever means being told to look again -- what a subscriber can
#: actually see is decided by the endpoint they then call, under the same rules
#: as any other request.
#:
#: `presence` matches the gate on `GET /presence/active` exactly, including its
#: institution-wide scope: the screen is a list of who is signed in, and a role
#: that may not open it has no business being told when it changes.
TOPIC_PERMISSIONS: Final[dict[str, str]] = {
    DIRECTORY: perm(Module.USER, Action.READ),
    ACADEMIC: perm(Module.COURSE, Action.READ),
    ASSESSMENT: perm(Module.ASSIGNMENT, Action.READ),
    ANNOUNCEMENTS: perm(Module.ANNOUNCEMENT, Action.READ),
    PRESENCE: perm(Module.USER, Action.READ),
}

#: Topics that additionally require institution-wide visibility.
#:
#: Presence is a single list covering everybody; there is no per-scope version
#: of it to show a tutor, so a tutor is not subscribed rather than being sent
#: frames for a screen that will refuse them.
UNRESTRICTED_ONLY: Final[frozenset[str]] = frozenset({PRESENCE})


def topics_for(held: set[str], *, unrestricted: bool) -> tuple[str, ...]:
    """The topics one connection may subscribe to.

    Pure, and takes the already-resolved permission set rather than a `User`:
    the stream endpoint resolves permissions once, releases its database
    connection, and then holds nothing for the life of the stream.
    """
    return tuple(
        topic
        for topic in ALL_TOPICS
        if TOPIC_PERMISSIONS[topic] in held
        and (unrestricted or topic not in UNRESTRICTED_ONLY)
    )


def topic_for_table(table: str) -> str | None:
    """The topic a write to this table belongs to, or None to stay quiet."""
    return TABLE_TOPICS.get(table)

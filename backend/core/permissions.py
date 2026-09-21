"""The permission catalog and the role -> permission grants.

This module is the single source of truth for *what permissions exist*.
`backend/bootstrap/` seeds these rows into `permissions`/`roles`/
`role_permissions`; `backend/api/deps.py` checks against them at request
time. Both read the same constants here, so a permission cannot be enforced
that was never seeded, nor seeded under a name nothing checks.

Naming is `<module>.<action>`, which maps exactly onto the `Permission`
model's own `module` and `action` columns -- the name is derived from them
rather than typed twice.

`*.manage` is deliberately NOT magic: it does not imply the matching
create/read/update/delete permissions. A role that should be able to read
and update is granted both, explicitly. Implicit expansion means a reader
has to hold the whole rule set in their head to answer "can this role do X",
and that is exactly the question an authorization system exists to make
answerable by looking.
"""

from __future__ import annotations

from typing import Final

from backend.utils.enums import Roles


# =============================================================================
# MODULES
# =============================================================================

class Module:
    USER: Final = "user"
    ROLE: Final = "role"
    PERMISSION: Final = "permission"
    COURSE: Final = "course"
    BATCH: Final = "batch"
    SESSION: Final = "session"
    ENROLLMENT: Final = "enrollment"
    ATTENDANCE: Final = "attendance"
    RESOURCE: Final = "resource"
    ASSIGNMENT: Final = "assignment"
    QUIZ: Final = "quiz"
    EXAM: Final = "exam"
    GRADE: Final = "grade"
    ORGANIZATION: Final = "organization"
    GUARDIAN: Final = "guardian"
    ANNOUNCEMENT: Final = "announcement"
    MESSAGE: Final = "message"
    TEAM: Final = "team"
    DISCUSSION: Final = "discussion"
    NOTIFICATION: Final = "notification"
    ACADEMIC: Final = "academic"
    REPORT: Final = "report"
    AUDIT: Final = "audit"
    SECURITY: Final = "security"
    INTEGRATION: Final = "integration"
    GOOGLE: Final = "google"
    SETTING: Final = "setting"
    INSTITUTION: Final = "institution"


class Action:
    CREATE: Final = "create"
    READ: Final = "read"
    UPDATE: Final = "update"
    DELETE: Final = "delete"
    MANAGE: Final = "manage"
    # Domain-specific verbs, where CRUD genuinely doesn't describe the act.
    SUBMIT: Final = "submit"
    GRADE: Final = "grade"
    ATTEMPT: Final = "attempt"
    PUBLISH: Final = "publish"
    ENROLL: Final = "enroll"
    INVITE: Final = "invite"
    EXPORT: Final = "export"
    IMPERSONATE: Final = "impersonate"
    VIEW_ALL: Final = "view_all"
    APPOINT: Final = "appoint"
    SYNC: Final = "sync"
    ALLOW_LOGIN: Final = "allow_login"
    VIEW_CONTACT: Final = "view_contact"
    OVERRIDE: Final = "override"


def perm(module: str, action: str) -> str:
    """Build a permission name. Used by the catalog below, the seeder, and
    every `require_permission(...)` call, so all three cannot disagree."""
    return f"{module}.{action}"


# =============================================================================
# CATALOG
# =============================================================================
# (name, description) -- module/action are derived by splitting the name, so
# the three columns on the Permission model can never drift apart.

_CRUD = (Action.CREATE, Action.READ, Action.UPDATE, Action.DELETE)

_CATALOG: dict[str, str] = {}


def _register(module: str, actions: tuple[str, ...], noun: str) -> None:
    verb_phrasing = {
        Action.CREATE: f"Create {noun}",
        Action.READ: f"View {noun}",
        Action.UPDATE: f"Modify {noun}",
        Action.DELETE: f"Delete {noun}",
        Action.MANAGE: f"Full administrative control over {noun}",
        Action.SUBMIT: f"Submit {noun}",
        Action.GRADE: f"Grade {noun}",
        Action.ATTEMPT: f"Attempt {noun}",
        Action.PUBLISH: f"Publish {noun}",
        Action.ENROLL: f"Enroll students in {noun}",
        Action.INVITE: f"Invite people to {noun}",
        Action.EXPORT: f"Export {noun}",
        Action.IMPERSONATE: f"Impersonate {noun}",
        Action.VIEW_ALL: f"View {noun} across the whole institution",
        Action.APPOINT: f"Appoint managers to {noun}",
        Action.SYNC: f"Synchronise {noun} from the external LAIT system",
        Action.ALLOW_LOGIN: f"Allow or block sign-in for {noun}",
        Action.VIEW_CONTACT: f"See other people's email addresses, phone numbers and login names in {noun}",
        Action.OVERRIDE: f"Take or correct {noun} on behalf of the assigned tutor",
    }
    for action in actions:
        _CATALOG[perm(module, action)] = verb_phrasing[action]


# `view_contact` is held by the Super Admin alone (they hold the whole catalog by construction). Everyone
# else -- Administrators, tutors, students, guardians and managers -- sees other people's *names* only.
# `sync` and `allow_login` are separate from create/update on purpose.
# `sync` decides who may pull accounts in from LAIT in bulk; `allow_login` is
# the switch that turns a provisioned-but-closed account into one somebody can
# sign in to, which is the moment a shared default password becomes dangerous
# -- so it is held by fewer people than the ones who can edit a profile.
_register(
    Module.USER,
    _CRUD + (Action.IMPERSONATE, Action.SYNC, Action.ALLOW_LOGIN, Action.VIEW_CONTACT),
    "user accounts",
)
# `team.read` is the "people in my care" view: a manager's employees or a guardian's wards, with their progress. It is
# scoped to those people by the service (enrolment visibility), not by this name.
_register(Module.TEAM, (Action.READ,), "the progress of the people in your care")
_register(Module.ROLE, _CRUD, "roles")
_register(Module.PERMISSION, (Action.READ, Action.MANAGE), "permissions")
_register(Module.COURSE, _CRUD + (Action.PUBLISH, Action.SYNC), "courses")
_register(Module.BATCH, _CRUD, "batches")
_register(Module.SESSION, _CRUD, "class sessions")
_register(Module.ENROLLMENT, _CRUD, "enrollments")
# `override` lets somebody other than the session's assigned tutor take or correct its register (the assigned tutor is
# recorded alongside who actually did it). Super Admin only, by construction; an Administrator is deliberately without it.
_register(Module.ATTENDANCE, _CRUD + (Action.OVERRIDE,), "attendance records")
_register(Module.RESOURCE, _CRUD, "learning resources")
_register(Module.ASSIGNMENT, _CRUD + (Action.SUBMIT, Action.GRADE), "assignments")
_register(Module.QUIZ, _CRUD + (Action.ATTEMPT, Action.GRADE), "quizzes")
_register(Module.EXAM, _CRUD + (Action.PUBLISH,), "examinations")
_register(Module.GRADE, (Action.READ, Action.UPDATE, Action.PUBLISH), "grades and transcripts")
_register(
    Module.ORGANIZATION,
    _CRUD + (Action.INVITE, Action.ENROLL, Action.APPOINT),
    "corporate organizations",
)
_register(Module.GUARDIAN, _CRUD, "guardian relationships")
_register(Module.ANNOUNCEMENT, _CRUD, "announcements")
_register(Module.MESSAGE, (Action.CREATE, Action.READ, Action.DELETE), "messages")
_register(Module.DISCUSSION, _CRUD, "course discussions")
_register(Module.NOTIFICATION, (Action.READ, Action.UPDATE), "notifications")
_register(Module.ACADEMIC, _CRUD, "academic years, semesters, departments and categories")
_register(Module.REPORT, (Action.READ, Action.EXPORT), "reports")
_register(Module.AUDIT, (Action.READ, Action.EXPORT), "audit logs")
# Separate from `audit.*` on purpose. Reading the audit trail is reading the
# institution's entire change history -- who edited which course, what was in
# a message subject. Responding to a security incident is a narrower job:
# which accounts are locked out, which sessions are live, what failed to sign
# in overnight. Splitting them is what lets a future SECURITY_OFFICER or
# AUDITOR role exist with one and not the other, which the note above the
# INSTITUTION grant already anticipated.
_register(Module.SECURITY, (Action.READ, Action.MANAGE), "security events, lockouts and sessions")
# Registering an endpoint the *server* will connect out to is its own
# capability, not a setting: it decides where institution data is sent, and
# the target is chosen by a person rather than by the deployment. It gets its
# own module so it can be delegated without also handing over the settings
# store -- and withheld without taking the settings store away.
_register(Module.INTEGRATION, _CRUD, "outbound integrations and calendar feeds")
_register(Module.SETTING, (Action.READ, Action.UPDATE), "system settings")
# Connecting or disconnecting the organisation's Google account is `google.update`, held by
# the Super Admin only: it decides whose calendar the whole institution's schedule lives in.
# Reading the connection and pushing changes (`google.sync`) are ordinary operations.
_register(Module.GOOGLE, (Action.READ, Action.UPDATE, Action.SYNC), "the Google Calendar connection")

# The scope modifier. Every other permission answers "may this role do X at
# all"; this one answers "to which rows". Without it a caller sees only what
# they are connected to -- a Tutor their own batches' students, a Guardian
# their wards, a Corporate Manager their organization's employees. With it
# they see the whole institution.
#
# Deliberately a permission rather than a check on role name: an institution
# will eventually want a REGISTRAR or AUDITOR role with full visibility and
# few write rights, and `if role in (ADMIN, SUPER_ADMIN)` scattered through
# the service layer cannot express that without a code change.
_register(Module.INSTITUTION, (Action.VIEW_ALL,), "records")


ALL_PERMISSIONS: Final[dict[str, str]] = dict(_CATALOG)


# =============================================================================
# ROLE GRANTS
# =============================================================================
# Spec §2 defines what each role can and cannot do; this encodes it.
# Anything not listed is denied -- there is no implicit inheritance between
# roles, so ADMIN's grants are written out rather than "SUPER_ADMIN minus
# two things". A reader can answer "what can a Tutor do?" from one block.

def _all_for(*modules: str) -> set[str]:
    return {name for name in ALL_PERMISSIONS if name.split(".", 1)[0] in modules}


# --- Administrator ---------------------------------------------------------
# Spec §2: can run daily operations; explicitly CANNOT modify system
# settings or manage permissions.
_ADMIN: set[str] = (
    _all_for(
        Module.USER, Module.COURSE, Module.BATCH, Module.SESSION,
        Module.ENROLLMENT, Module.ATTENDANCE, Module.RESOURCE,
        Module.ASSIGNMENT, Module.QUIZ, Module.EXAM, Module.GRADE,
        Module.ORGANIZATION, Module.GUARDIAN, Module.ANNOUNCEMENT,
        Module.DISCUSSION, Module.ACADEMIC, Module.REPORT,
    )
    | {
        perm(Module.ROLE, Action.READ),
        perm(Module.PERMISSION, Action.READ),
        perm(Module.AUDIT, Action.READ),
        perm(Module.AUDIT, Action.EXPORT),
        # An Administrator can *read* and *export* the audit trail and can
        # never alter it -- that is enforced by a database trigger, not by
        # withholding a permission, because the log has to constrain the very
        # role that administers the system.
        perm(Module.SECURITY, Action.READ),
        perm(Module.SECURITY, Action.MANAGE),
        perm(Module.INTEGRATION, Action.CREATE),
        perm(Module.INTEGRATION, Action.READ),
        perm(Module.INTEGRATION, Action.UPDATE),
        perm(Module.INTEGRATION, Action.DELETE),
        perm(Module.GOOGLE, Action.READ),
        perm(Module.GOOGLE, Action.SYNC),
        # Operational health and database statistics are gated on
        # `setting.read` rather than a module of their own: "may this person
        # see how the system is configured" and "may they see how it is
        # behaving" have the same audience, and inventing a permission to
        # express a distinction nobody makes is catalogue growth for its own
        # sake.
        perm(Module.SETTING, Action.READ),
        # Institution-wide visibility. TUTOR, STUDENT, CORPORATE_MANAGER and
        # GUARDIAN deliberately do NOT hold this -- it is the single grant
        # that turns "my students" into "every student".
        perm(Module.INSTITUTION, Action.VIEW_ALL),
        perm(Module.MESSAGE, Action.CREATE),
        perm(Module.MESSAGE, Action.READ),
        perm(Module.MESSAGE, Action.DELETE),
        perm(Module.NOTIFICATION, Action.READ),
        perm(Module.NOTIFICATION, Action.UPDATE),
    }
) - {
    # Impersonation is a Super Admin capability: it defeats the audit trail's
    # ability to say who really acted, so it stays with the smallest group.
    perm(Module.USER, Action.IMPERSONATE),
    # Opening a synced account to sign-in is a Super Admin decision. An
    # Administrator can sync accounts in and edit them, but cannot decide who
    # among them gets to authenticate.
    perm(Module.USER, Action.ALLOW_LOGIN),
    # Other people's email addresses, phone numbers and login names (which are often the email). Super Admin only;
    # an Administrator works from names.
    perm(Module.USER, Action.VIEW_CONTACT),
    # Taking attendance for a tutor is a Super Admin act: it puts words in the assigned tutor's mouth, and is audited.
    perm(Module.ATTENDANCE, Action.OVERRIDE),
}


# --- Tutor -----------------------------------------------------------------
# Row-level scoping ("only my own courses/batches") is NOT expressible as a
# permission name and is enforced in the service layer against enrollment /
# tutor_courses / batch_sessions rows. These grants say what a tutor may do
# at all; the service says which rows they may do it to.
_TUTOR: set[str] = {
    perm(Module.COURSE, Action.READ),
    perm(Module.BATCH, Action.READ),
    perm(Module.SESSION, Action.READ),
    perm(Module.SESSION, Action.UPDATE),
    perm(Module.ENROLLMENT, Action.READ),
    perm(Module.ATTENDANCE, Action.CREATE),
    perm(Module.ATTENDANCE, Action.READ),
    perm(Module.ATTENDANCE, Action.UPDATE),
    perm(Module.RESOURCE, Action.CREATE),
    perm(Module.RESOURCE, Action.READ),
    perm(Module.RESOURCE, Action.UPDATE),
    perm(Module.RESOURCE, Action.DELETE),
    perm(Module.ASSIGNMENT, Action.CREATE),
    perm(Module.ASSIGNMENT, Action.READ),
    perm(Module.ASSIGNMENT, Action.UPDATE),
    perm(Module.ASSIGNMENT, Action.DELETE),
    perm(Module.ASSIGNMENT, Action.GRADE),
    perm(Module.QUIZ, Action.CREATE),
    perm(Module.QUIZ, Action.READ),
    perm(Module.QUIZ, Action.UPDATE),
    perm(Module.QUIZ, Action.DELETE),
    perm(Module.QUIZ, Action.GRADE),
    perm(Module.EXAM, Action.READ),
    perm(Module.GRADE, Action.READ),
    perm(Module.GRADE, Action.UPDATE),
    perm(Module.ANNOUNCEMENT, Action.CREATE),
    perm(Module.ANNOUNCEMENT, Action.READ),
    # A tutor who can post an announcement but can never correct or withdraw
    # it is worse off than one who cannot post at all -- the mistake is
    # permanent and only an administrator can clear it. Both grants are
    # scoped in the service to announcements the tutor authored.
    perm(Module.ANNOUNCEMENT, Action.UPDATE),
    perm(Module.ANNOUNCEMENT, Action.DELETE),
    perm(Module.DISCUSSION, Action.CREATE),
    perm(Module.DISCUSSION, Action.READ),
    perm(Module.DISCUSSION, Action.UPDATE),
    perm(Module.DISCUSSION, Action.DELETE),
    perm(Module.MESSAGE, Action.CREATE),
    perm(Module.MESSAGE, Action.READ),
    perm(Module.MESSAGE, Action.DELETE),
    perm(Module.NOTIFICATION, Action.READ),
    perm(Module.NOTIFICATION, Action.UPDATE),
    # Reference data, not records. Departments, categories, tags and the
    # academic calendar are the vocabulary the course catalogue is described
    # in -- a student filtering by "Engineering" or a tutor picking a
    # semester needs to be able to list them. Withholding the read would not
    # protect anything (the names are already embedded in every course
    # response) and would only make the catalogue unfilterable. Writing them
    # stays with the administration.
    perm(Module.ACADEMIC, Action.READ),
    perm(Module.USER, Action.READ),
    perm(Module.REPORT, Action.READ),
}


# --- Student ---------------------------------------------------------------
_STUDENT: set[str] = {
    perm(Module.COURSE, Action.READ),
    perm(Module.BATCH, Action.READ),
    perm(Module.SESSION, Action.READ),
    perm(Module.ENROLLMENT, Action.READ),
    perm(Module.ATTENDANCE, Action.READ),
    perm(Module.RESOURCE, Action.READ),
    perm(Module.ASSIGNMENT, Action.READ),
    perm(Module.ASSIGNMENT, Action.SUBMIT),
    perm(Module.QUIZ, Action.READ),
    perm(Module.QUIZ, Action.ATTEMPT),
    perm(Module.EXAM, Action.READ),
    perm(Module.GRADE, Action.READ),
    perm(Module.ANNOUNCEMENT, Action.READ),
    perm(Module.DISCUSSION, Action.CREATE),
    perm(Module.DISCUSSION, Action.READ),
    # Editing and withdrawing *their own* posts, scoped in the service. A
    # forum where the only way to fix a typo is to ask an administrator is a
    # forum nobody uses; moderation of other people's posts (pinning,
    # locking, deleting) is a separate check inside the service, not a
    # separate permission, because it depends on which course it is.
    perm(Module.DISCUSSION, Action.UPDATE),
    perm(Module.DISCUSSION, Action.DELETE),
    perm(Module.ACADEMIC, Action.READ),
    perm(Module.MESSAGE, Action.CREATE),
    perm(Module.MESSAGE, Action.READ),
    perm(Module.MESSAGE, Action.DELETE),
    perm(Module.NOTIFICATION, Action.READ),
    perm(Module.NOTIFICATION, Action.UPDATE),
}


# --- Corporate Manager -----------------------------------------------------
# Scoped in the service layer to their own organization's employees, via
# organization_managers -> organization_memberships. The grants below say
# "may do this at all"; the org join says "to these people".
_CORPORATE_MANAGER: set[str] = {
    perm(Module.TEAM, Action.READ),
    perm(Module.ORGANIZATION, Action.READ),
    perm(Module.ORGANIZATION, Action.UPDATE),
    perm(Module.ORGANIZATION, Action.INVITE),
    perm(Module.ORGANIZATION, Action.ENROLL),
    perm(Module.USER, Action.READ),
    perm(Module.COURSE, Action.READ),
    perm(Module.BATCH, Action.READ),
    # Attendance records reference a session, so without `session.read` a
    # manager could see that an employee missed a class but not look the
    # class up -- an inconsistency rather than a safeguard, the same one
    # `batch.read` fixed for guardians.
    perm(Module.SESSION, Action.READ),
    perm(Module.ENROLLMENT, Action.CREATE),
    perm(Module.ENROLLMENT, Action.READ),
    perm(Module.ATTENDANCE, Action.READ),
    perm(Module.GRADE, Action.READ),
    perm(Module.REPORT, Action.READ),
    perm(Module.REPORT, Action.EXPORT),
    perm(Module.NOTIFICATION, Action.READ),
    perm(Module.NOTIFICATION, Action.UPDATE),
    perm(Module.ACADEMIC, Action.READ),
    perm(Module.MESSAGE, Action.CREATE),
    perm(Module.MESSAGE, Action.READ),
    perm(Module.MESSAGE, Action.DELETE),
}


# --- Guardian --------------------------------------------------------------
# Read-only, and scoped in the service layer to their linked students via
# student_guardians.
_GUARDIAN: set[str] = {
    perm(Module.TEAM, Action.READ),
    perm(Module.USER, Action.READ),
    perm(Module.COURSE, Action.READ),
    # A guardian can already see which batch their ward is in via the
    # enrollment record; without `batch.read` they could see the batch's name
    # but not open it, which is an inconsistency rather than a safeguard.
    perm(Module.BATCH, Action.READ),
    perm(Module.SESSION, Action.READ),
    perm(Module.ENROLLMENT, Action.READ),
    perm(Module.ATTENDANCE, Action.READ),
    perm(Module.GRADE, Action.READ),
    perm(Module.ASSIGNMENT, Action.READ),
    perm(Module.EXAM, Action.READ),
    perm(Module.ANNOUNCEMENT, Action.READ),
    # Read-only, and scoped to their own links. Creating a guardianship is
    # deliberately NOT granted: a self-service "I am this child's guardian"
    # is a claim, not a fact, and the institution has to be the one asserting
    # it.
    perm(Module.GUARDIAN, Action.READ),
    perm(Module.NOTIFICATION, Action.READ),
    perm(Module.NOTIFICATION, Action.UPDATE),
    perm(Module.ACADEMIC, Action.READ),
    perm(Module.MESSAGE, Action.CREATE),
    perm(Module.MESSAGE, Action.READ),
    perm(Module.MESSAGE, Action.DELETE),
}


ROLE_PERMISSIONS: Final[dict[str, set[str]]] = {
    # Super Admin holds the whole catalog by construction, so a permission
    # added later is automatically theirs -- the one place where implicit
    # breadth is correct, since "there exists a role that can do everything"
    # is the property being asserted.
    Roles.SUPER_ADMIN.value: set(ALL_PERMISSIONS),
    Roles.ADMIN.value: _ADMIN,
    Roles.TUTOR.value: _TUTOR,
    Roles.STUDENT.value: _STUDENT,
    Roles.CORPORATE_MANAGER.value: _CORPORATE_MANAGER,
    Roles.GUARDIAN.value: _GUARDIAN,
}


ROLE_DESCRIPTIONS: Final[dict[str, str]] = {
    Roles.SUPER_ADMIN.value: "Full system access, including settings, permissions and audit.",
    Roles.ADMIN.value: "Day-to-day operations. Cannot modify system settings or manage permissions.",
    Roles.TUTOR.value: "Teaches assigned courses and batches; grades work and records attendance.",
    Roles.STUDENT.value: "Enrolled learner.",
    Roles.CORPORATE_MANAGER.value: "Manages a corporate organization's employees and their enrollments.",
    Roles.GUARDIAN.value: "Views the progress of linked students.",
}

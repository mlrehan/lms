"""What changed in a published assessment, and who was told.

One recorder for assignments, quizzes and exams, called from each service's
``update`` *after* the new values are set. It does three things, and only for
an assessment that was already published before the edit and still is:

1. writes an `AssessmentRevision` with each changed field's old and new value
   -- the audit log keeps only field *names*, which cannot answer "the
   deadline was moved after I submitted";
2. decides whether the change is **material**: it alters what a student must
   do or by when (deadline, marks, brief, sitting time). Fixing a typo in a
   title is a revision, not news;
3. for a material change, notifies the students the assessment is set for --
   the same eligibility rule that decided who was told it was published -- in
   the same transaction as the edit, so nobody is told about a change that
   rolled back.

A draft is edited freely and silently: nobody has been told it exists.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.notification_types import NotificationType
from backend.models.assessment_links import KIND_COLUMN, AssessmentRevision
from backend.services.assessment_scope import AssessmentScopeResolver, AssessmentTarget, kind_of
from backend.services.notification_service import NotificationService

#: Fields whose change alters what a student must do, or by when.
MATERIAL_FIELDS: dict[str, frozenset[str]] = {
    "assignment": frozenset({
        "due_date", "max_score", "description", "submission_type", "available_from",
        "allow_late_submissions", "late_penalty_percent_per_day", "passing_score", "rubric",
        "allowed_file_types", "max_upload_mb",
    }),
    "quiz": frozenset({
        "available_from", "available_until", "duration_minutes", "attempts_allowed",
        "passing_score", "total_marks", "instructions",
    }),
    "exam": frozenset({
        "scheduled_at", "duration_minutes", "venue_or_link", "total_marks", "passing_marks",
        "instructions",
    }),
}

#: Never revisions: publication has its own announcement and audit entry.
_IGNORED = frozenset({"state", "is_published", "publish_at"})

_LABELS = {
    "due_date": "deadline", "scheduled_at": "date and time", "max_score": "marks",
    "total_marks": "marks", "passing_score": "pass mark", "passing_marks": "pass mark",
    "description": "brief", "instructions": "instructions", "duration_minutes": "duration",
    "venue_or_link": "venue", "available_from": "opening time", "available_until": "closing time",
    "attempts_allowed": "attempts allowed", "submission_type": "submission type",
    "allow_late_submissions": "late submissions", "late_penalty_percent_per_day": "late penalty",
    "rubric": "rubric", "allowed_file_types": "file types", "max_upload_mb": "upload size",
}

_NOUN = {"assignment": "assignment", "quiz": "quiz", "exam": "examination"}
_LINK = {"assignment": "assignment_id", "quiz": "quiz_id", "exam": "exam_id"}


def _plain(value: Any) -> Any:
    """A JSON-safe copy of a column value."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "value") and not isinstance(value, (int, float, str, bool)):
        return value.value
    return value


def snapshot(row: Any, fields: Any) -> dict[str, Any]:
    """The current value of each field, taken before an edit."""
    return {f: getattr(row, f, None) for f in fields}


async def record_revision(
    session: AsyncSession,
    row: Any,
    before: Mapping[str, Any],
    *,
    actor_id: int,
    was_published: bool,
    is_published: bool,
) -> AssessmentRevision | None:
    """Record (and, if material, announce) an edit. Returns the revision written, if any."""
    if not (was_published and is_published):
        return None
    changes = {
        field: {"from": _plain(old), "to": _plain(getattr(row, field, None))}
        for field, old in before.items()
        if field not in _IGNORED and _plain(old) != _plain(getattr(row, field, None))
    }
    if not changes:
        return None

    kind = kind_of(row)
    column = getattr(AssessmentRevision, KIND_COLUMN[kind])
    last = (
        await session.execute(select(func.max(AssessmentRevision.revision_no)).where(column == row.id))
    ).scalar_one_or_none()
    material = sorted(set(changes) & MATERIAL_FIELDS[kind])
    revision = AssessmentRevision(
        **{KIND_COLUMN[kind]: row.id},
        revision_no=(last or 0) + 1,
        changed_by=actor_id,
        changes=changes,
        material=bool(material),
        notified=0,
    )
    session.add(revision)

    if material:
        roster = sorted(
            await AssessmentScopeResolver(session).eligible_student_ids(AssessmentTarget.of(row))
        )
        what = ", ".join(dict.fromkeys(_LABELS.get(f, f.replace("_", " ")) for f in material))
        revision.notified = await NotificationService(session).notify_many(
            roster,
            type_=NotificationType.ASSESSMENT_UPDATED,
            title=f"Updated {_NOUN[kind]}: {row.title}",
            body=f"The {what} changed. Open it to see the current version.",
            meta={
                _LINK[kind]: str(row.public_id),
                "revision": revision.revision_no,
                "changed": material,
            },
        )
    await session.flush()
    return revision


async def notify_markers(
    session: AsyncSession, row: Any, *, student: Any, submitted_at: datetime,
    late: bool, link: Mapping[str, str], replaced: bool = False,
) -> int:
    """Tell the tutors responsible for `row` that `student` handed it in.

    Who is responsible is `AssessmentAccess.markers_for`: the author, plus the
    tutors teaching the student's batch unless the author is a tutor whose
    work colleagues cannot see. In the submission's own transaction, so a
    notice can never point at work that was not saved. Returns how many were
    told.
    """
    from backend.services.assessment_access import AssessmentAccess

    markers = await AssessmentAccess(session).markers_for(row, student.id)
    kind = kind_of(row)
    when = submitted_at.strftime("%d %b %Y %H:%M UTC")
    verb = "resubmitted" if replaced else "submitted"
    # First and last name only: `full_name` falls back to the login name,
    # which here is usually an email address the tutor may not see.
    name = " ".join(p for p in (student.first_name, student.last_name) if p) or "A student"
    return await NotificationService(session).notify_many(
        markers,
        type_=NotificationType.SUBMISSION_RECEIVED,
        title=f"{name} {verb} {row.title}",
        body=f"{_NOUN[kind].capitalize()} {verb} {when}" + (" (late)." if late else "."),
        meta={_LINK[kind]: str(row.public_id), **link, "late": late},
    )

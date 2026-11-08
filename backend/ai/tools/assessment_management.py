"""Editing and reusing assessments from the chat, through the console's own services.

Two confirmed tools:

* ``update_assessment`` -- change an assignment, quiz or examination. The
  preview lists every field as *from -> to* and says whether the students it
  is set for will be told (they are, for a material change to published work,
  by the same recorder the console uses -- see `assessment_revisions`).
* ``reuse_assessment`` -- copy one to other batches and/or named students,
  through `AssessmentReuseService`, which calls each kind's own ``create``.
  So the copy obeys every rule a hand-made assessment does: the tutor must
  teach the target class, named students must be in a class they teach, a
  draft tells nobody and a published copy tells only its own students.

Changes are a **sparse object of what was asked for**. A schema of a dozen
optional numbers invites a model to fill the ones nobody mentioned (this
codebase has watched it invent zeros); here an unmentioned field is simply
absent, and the preview shows exactly what will be stored.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select

from backend.ai.security import RiskLevel, SecurityPolicyEngine, ToolPolicy
from backend.ai.tools.registry import BOUND_PREFIX, ConfirmationPreview, ToolDefinition, ToolExecutionContext
from backend.core.errors import AuthorizationError, NotFoundError, ValidationError
from backend.utils.enums import AssessmentScope, AssessmentState, Roles

_STAFF = (Roles.TUTOR.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value)

#: Which fields each kind accepts from the chat, and how to read them.
_FIELDS: dict[str, dict[str, str]] = {
    "assignment": {
        "title": "text", "description": "text", "due_date": "datetime", "max_score": "number",
        "passing_score": "number", "available_from": "datetime", "allow_late_submissions": "bool",
    },
    "quiz": {
        "title": "text", "instructions": "text", "duration_minutes": "int", "attempts_allowed": "int",
        "passing_score": "number", "total_marks": "number", "available_from": "datetime",
        "available_until": "datetime",
    },
    "examination": {
        "title": "text", "instructions": "text", "scheduled_at": "datetime", "duration_minutes": "int",
        "venue_or_link": "text", "total_marks": "number", "passing_marks": "number",
    },
}
_PERMISSION = {"assignment": "assignment.update", "quiz": "quiz.update", "examination": "exam.update"}
_CREATE = {"assignment": "assignment.create", "quiz": "quiz.create", "examination": "exam.create"}


def _kind(arguments: dict[str, Any]) -> str:
    raw = str(arguments.get("assessment_type", "")).strip().lower()
    kind = "examination" if raw in ("exam", "examination") else raw
    if kind not in _FIELDS:
        raise ValidationError("assessment_type must be assignment, quiz or examination.")
    return kind


def _bound(arguments: dict[str, Any], key: str) -> Any:
    return arguments.get(f"{BOUND_PREFIX}{key}")


def _service(kind: str, session: Any) -> Any:
    if kind == "assignment":
        from backend.services.assignment_service import AssignmentService

        return AssignmentService(session)
    if kind == "quiz":
        from backend.services.quiz_service import QuizService

        return QuizService(session)
    from backend.services.exam_service import ExamService

    return ExamService(session)


async def _load(kind: str, arguments: dict[str, Any], context: ToolExecutionContext) -> Any:
    """By id or exact title, then through the kind's own `get` (its visibility rules)."""
    from backend.ai.tools.academic_tools import _resolve_for_publish
    from backend.models.assignment import Assignment
    from backend.models.exam import Exam
    from backend.models.quiz import Quiz

    identifier = arguments.get("assessment_id")
    if not identifier:
        raise ValidationError("assessment_id (its id or exact title) is required.")
    model = {"assignment": Assignment, "quiz": Quiz, "examination": Exam}[kind]
    row = await _resolve_for_publish(context.session, model, str(identifier))
    if row is None:
        raise NotFoundError(f"No {kind} called '{identifier}' was found.")
    return await _service(kind, context.session).get(row.public_id, actor=context.user)


def _parse(kind: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or not raw:
        raise ValidationError("Say what to change, e.g. {\"due_date\": \"2026-12-01T17:00:00Z\"}.")
    allowed = _FIELDS[kind]
    out: dict[str, Any] = {}
    for field, value in raw.items():
        how = allowed.get(field)
        if how is None:
            raise ValidationError(
                f"'{field}' cannot be changed here. A {kind} accepts: {', '.join(sorted(allowed))}."
            )
        try:
            if how == "datetime":
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValidationError(f"{field} needs a time zone, e.g. 2026-12-01T17:00:00Z.")
                out[field] = parsed.isoformat()
            elif how == "number":
                out[field] = str(Decimal(str(value)))
            elif how == "int":
                out[field] = int(value)
            elif how == "bool":
                out[field] = bool(value)
            else:
                out[field] = str(value)
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValidationError(f"'{value}' is not a valid {field}.") from exc
    return out


def _request(kind: str, changes: dict[str, Any]) -> Any:
    if kind == "assignment":
        from backend.schemas.assignment import AssignmentUpdateRequest

        return AssignmentUpdateRequest(**changes)
    if kind == "quiz":
        from backend.schemas.quiz import QuizUpdateRequest

        return QuizUpdateRequest(**changes)
    from backend.schemas.exam import ExamUpdateRequest

    return ExamUpdateRequest(**changes)


def _is_published(row: Any) -> bool:
    state = getattr(row, "state", None)
    return state is AssessmentState.PUBLISHED if state is not None else bool(getattr(row, "is_published", False))


def _show(value: Any) -> str:
    if value is None or value == "":
        return "(none)"
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y %H:%M UTC")
    text = str(value)
    return text if len(text) <= 60 else text[:57] + "..."


# -- update_assessment -----------------------------------------------------------


async def preview_update_assessment(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    from backend.services.assessment_revisions import MATERIAL_FIELDS

    kind = _kind(arguments)
    if _PERMISSION[kind] not in SecurityPolicyEngine.caller_permissions(context.user):
        raise AuthorizationError(f"You do not have permission to change a {kind}.")
    row = await _load(kind, arguments, context)
    from backend.services.assessment_access import AssessmentAccess

    if not AssessmentAccess.may_manage(row, context.user):
        raise AuthorizationError("Only the tutor who set it (or a Super Admin) can change it.")
    changes = _parse(kind, arguments.get("changes"))
    _request(kind, changes)  # the schema's own rules, before anything is offered for confirmation
    lines = []
    for field, new in changes.items():
        old = getattr(row, field, None)
        shown_new = datetime.fromisoformat(new) if _FIELDS[kind][field] == "datetime" else new
        lines.append(f"{field.replace('_', ' ')}: {_show(old)} -> {_show(shown_new)}")
    material = set(changes) & MATERIAL_FIELDS["exam" if kind == "examination" else kind]
    if _is_published(row) and material:
        tail = "It is published, so the students it is set for will be told what changed."
    elif _is_published(row):
        tail = "It is published; these changes are recorded but nobody is notified."
    else:
        tail = "It is a draft, so nobody is notified."
    return ConfirmationPreview(
        summary=f"Change the {kind} '{row.title}':\n- " + "\n- ".join(lines) + f"\n{tail}",
        bound_parameters={"assessment_public_id": str(row.public_id), "changes": changes},
    )


async def handle_update_assessment(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    kind = _kind(arguments)
    row = await _load(kind, arguments, context)
    if str(row.public_id) != str(_bound(arguments, "assessment_public_id")):
        raise ValidationError("The assessment no longer matches the one confirmed; ask again.")
    changes = _bound(arguments, "changes") or {}
    updated = await _service(kind, context.session).update(
        row.public_id, _request(kind, changes), actor=context.user
    )
    from backend.models.assessment_links import KIND_COLUMN, AssessmentRevision

    column = getattr(AssessmentRevision, KIND_COLUMN["exam" if kind == "examination" else kind])
    revision = (await context.session.execute(
        select(AssessmentRevision).where(column == updated.id)
        .order_by(AssessmentRevision.revision_no.desc()).limit(1)
    )).scalar_one_or_none()
    return {
        "success": True,
        "assessment_type": kind,
        "assessment_id": str(updated.public_id),
        "title": updated.title,
        "changed": sorted(changes),
        "revision": revision.revision_no if revision else None,
        "students_notified": revision.notified if revision else 0,
    }


update_assessment_tool = ToolDefinition(
    name="update_assessment",
    description=(
        "Change an assignment, quiz or examination the caller set: title, brief/instructions, deadline or "
        "sitting time, marks, pass mark, duration, opening/closing time, venue. Pass ONLY the fields the "
        "user asked to change, as the `changes` object. A published assessment keeps every submission; a "
        "material change (deadline, marks, brief, time) is recorded as a revision and the students it is set "
        "for are notified. A quiz that already has attempts cannot be changed. Requires confirmation."
    ),
    policy=ToolPolicy(
        name="update_assessment",
        description="Edit an assessment",
        required_permissions=("course.read",),
        allowed_roles=_STAFF,
        risk_level=RiskLevel.HIGH,
        requires_confirmation=True,
        audit_action="UPDATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "assessment_type": {"type": "string", "enum": ["assignment", "quiz", "examination"]},
            "assessment_id": {"type": "string", "description": "Its id, or its exact title."},
            "changes": {
                "type": "object",
                "description": (
                    "Only what the user asked to change. Dates are ISO 8601 with a time zone. "
                    "assignment: title, description, due_date, max_score, passing_score, available_from, "
                    "allow_late_submissions. quiz: title, instructions, duration_minutes, attempts_allowed, "
                    "passing_score, total_marks, available_from, available_until. examination: title, "
                    "instructions, scheduled_at, duration_minutes, venue_or_link, total_marks, passing_marks."
                ),
            },
        },
        "required": ["assessment_type", "assessment_id", "changes"],
    },
    handler=handle_update_assessment,
    preview=preview_update_assessment,
)


# -- reuse_assessment -------------------------------------------------------------


async def _batches(codes: list[str], context: ToolExecutionContext) -> list[Any]:
    from backend.models.batch import Batch
    from backend.services.scope import ScopeResolver

    if not codes:
        return []
    scope = await ScopeResolver(context.session).visible_batch_ids(context.user)
    stmt = select(Batch).where(Batch.batch_code.in_([c.strip() for c in codes]))
    if not scope.unrestricted:
        stmt = stmt.where(Batch.id.in_(scope.ids or [-1]))
    found = {b.batch_code: b for b in (await context.session.execute(stmt)).scalars()}
    missing = [c for c in codes if c.strip() not in found]
    if missing:
        # One answer for "does not exist" and "not yours": either way it is not offered.
        raise ValidationError(f"No class you can see is called {', '.join(missing)}. Nothing was copied.")
    return [found[c.strip()] for c in codes]


async def _students(names: list[str], course_id: int, context: ToolExecutionContext) -> list[Any]:
    from backend.ai.tools.teaching_actions import _pick_people
    from backend.models.batch import Batch
    from backend.models.enrollment import Enrollments
    from backend.models.identity.user import User
    from backend.repositories.enrollment import ACTIVE_STATUSES
    from backend.services.scope import ScopeResolver

    if not names:
        return []
    # Ids first: `users` has JSON columns, which DISTINCT cannot compare.
    ids = (
        select(Enrollments.student_id)
        .join(Batch, Batch.id == Enrollments.batch_id)
        .where(Batch.course_id == course_id, Enrollments.status.in_(ACTIVE_STATUSES))
    )
    if not ScopeResolver.is_unrestricted(context.user):
        taught = (await ScopeResolver(context.session).enrollment_visibility(context.user)).taught_batch_ids
        ids = ids.where(Batch.id.in_(taught or {-1}))
    candidates = list((await context.session.execute(select(User).where(User.id.in_(ids)))).scalars())
    return _pick_people(candidates, names, "the classes you teach on this course")


async def preview_reuse_assessment(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    kind = _kind(arguments)
    if _CREATE[kind] not in SecurityPolicyEngine.caller_permissions(context.user):
        raise AuthorizationError(f"You do not have permission to set a {kind}.")
    row = await _load(kind, arguments, context)
    batches = await _batches([str(c) for c in arguments.get("batch_codes") or []], context)
    students = await _students([str(n) for n in arguments.get("student_names") or []], row.course_id, context)
    if not batches and not students:
        raise ValidationError("Name the classes (batch codes) and/or the students to set it for.")
    publish = bool(arguments.get("publish", False))
    new_time = arguments.get("due_date") if kind == "assignment" else arguments.get("scheduled_at")
    if new_time:
        new_time = _parse(kind, {"due_date" if kind == "assignment" else "scheduled_at": new_time}).popitem()[1]
    targets = [{"scope": "BATCH", "batch_id": str(b.public_id), "label": b.batch_code} for b in batches]
    if students:
        targets.append({
            "scope": "STUDENTS", "student_ids": [str(s.public_id) for s in students],
            "label": ", ".join(" ".join(p for p in (s.first_name, s.last_name) if p) for s in students),
        })
    lines = [f"- {t['label']}" for t in targets]
    tail = (
        "Each copy is published and only its own students are notified."
        if publish else "Each copy is saved as a draft; nobody is notified until you publish it."
    )
    when = f" with a new {'deadline' if kind == 'assignment' else 'time'} {_show(datetime.fromisoformat(new_time))}" if new_time else ""
    return ConfirmationPreview(
        summary=f"Reuse the {kind} '{row.title}' as {len(targets)} separate copies{when}:\n"
        + "\n".join(lines) + f"\n{tail} The original and its submissions are unchanged.",
        affected_records_count=len(targets),
        bound_parameters={
            "assessment_public_id": str(row.public_id),
            "targets": [{k: v for k, v in t.items() if k != "label"} for t in targets],
            "publish": publish,
            "new_time": new_time,
        },
    )


async def handle_reuse_assessment(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    import uuid

    from backend.services.assessment_reuse import AssessmentReuseService, CopyTarget

    kind = _kind(arguments)
    row = await _load(kind, arguments, context)
    if str(row.public_id) != str(_bound(arguments, "assessment_public_id")):
        raise ValidationError("The assessment no longer matches the one confirmed; ask again.")
    targets = [
        CopyTarget(
            scope=AssessmentScope(t["scope"]),
            batch_id=uuid.UUID(t["batch_id"]) if t.get("batch_id") else None,
            student_ids=[uuid.UUID(s) for s in t.get("student_ids") or []] or None,
        )
        for t in _bound(arguments, "targets") or []
    ]
    publish = bool(_bound(arguments, "publish"))
    new_time = _bound(arguments, "new_time")
    when = datetime.fromisoformat(new_time) if new_time else None
    reuse = AssessmentReuseService(context.session)
    if kind == "assignment":
        rows = await reuse.copy_assignment(row.public_id, targets, actor=context.user, due_date=when, publish=publish)
    elif kind == "quiz":
        rows = await reuse.copy_quiz(row.public_id, targets, actor=context.user, publish=publish)
    else:
        rows = await reuse.copy_exam(row.public_id, targets, actor=context.user, scheduled_at=when, publish=publish)
    return {
        "success": True,
        "assessment_type": kind,
        "copies": [
            {"assessment_id": str(r.public_id), "scope": r.scope.value, "published": _is_published(r)}
            for r in rows
        ],
    }


reuse_assessment_tool = ToolDefinition(
    name="reuse_assessment",
    description=(
        "Reuse an assignment, quiz or examination for other classes and/or chosen students: each becomes its "
        "own copy with its own deadline, submissions and marks (a quiz keeps its questions and answer key). "
        "Give batch_codes for whole classes and student_names for named students (who must be in a class you "
        "teach on that course). Drafts unless publish=true. Requires confirmation."
    ),
    policy=ToolPolicy(
        name="reuse_assessment",
        description="Copy an assessment to other classes or students",
        required_permissions=("course.read",),
        allowed_roles=_STAFF,
        risk_level=RiskLevel.HIGH,
        requires_confirmation=True,
        audit_action="CREATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "assessment_type": {"type": "string", "enum": ["assignment", "quiz", "examination"]},
            "assessment_id": {"type": "string", "description": "Its id, or its exact title."},
            "batch_codes": {"type": "array", "items": {"type": "string"}},
            "student_names": {"type": "array", "items": {"type": "string"}},
            "due_date": {"type": "string", "description": "Assignments only: new deadline, ISO 8601 with zone."},
            "scheduled_at": {"type": "string", "description": "Examinations only: new sitting time."},
            "publish": {"type": "boolean", "default": False},
        },
        "required": ["assessment_type", "assessment_id"],
    },
    handler=handle_reuse_assessment,
    preview=preview_reuse_assessment,
)

ASSESSMENT_MANAGEMENT_TOOLS = (update_assessment_tool, reuse_assessment_tool)

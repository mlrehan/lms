"""The rest of a tutor's week, as confirmed actions.

Five things the console lets a tutor do that the assistant could only describe:
hand work back for resubmission, record an absence or an exemption, enter the
class performance grid, publish a class recording, and share files with a class.
Each one calls the service the console's own screen calls, as the tutor, so the
rules are the screen's rules -- who may act, on which class, and what happens
next -- and none of them is re-derived here.

Every tool is HIGH risk with a confirmation: the preview resolves names to the
exact records (a submission, a register of people, a file) and binds them into
the ticket, so the thing confirmed is the thing done. People are matched by
name **within the class or audience in question only**: a tutor cannot see
email addresses, and matching across the whole directory could pick a namesake
in somebody else's class. A name that matches nobody, or more than one person,
refuses the whole request rather than being skipped.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from backend.ai.security import RiskLevel, SecurityPolicyEngine, ToolPolicy
from backend.ai.tools.marking_tools import _match_title, _name, _uuid
from backend.ai.tools.registry import BOUND_PREFIX, ConfirmationPreview, ToolDefinition, ToolExecutionContext
from backend.core.errors import AuthorizationError, NotFoundError, ValidationError
from backend.utils.enums import Roles

_STAFF = (Roles.TUTOR.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value)


def _bound(arguments: dict[str, Any], key: str) -> Any:
    return arguments.get(f"{BOUND_PREFIX}{key}")


def _require(context: ToolExecutionContext, permission: str, what: str) -> None:
    if permission not in SecurityPolicyEngine.caller_permissions(context.user):
        raise AuthorizationError(f"You do not have permission to {what}.")


def _pick_people(candidates: list[Any], names: list[str], what: str, *, label=_name) -> list[Any]:  # noqa: ANN001
    """Each name to exactly one candidate, or a refusal naming the problem."""
    chosen: list[Any] = []
    for raw in names:
        wanted = " ".join(str(raw).split()).lower()
        if not wanted:
            continue
        exact = [c for c in candidates if label(c).lower() == wanted]
        hits = exact or [c for c in candidates if wanted in label(c).lower()]
        if not hits:
            raise ValidationError(f"Nobody called '{raw}' is in {what}. Nothing was done.")
        if len(hits) > 1:
            names_found = ", ".join(sorted(label(c) for c in hits))
            raise ValidationError(f"'{raw}' matches more than one person in {what} ({names_found}). Say which one.")
        if hits[0] not in chosen:
            chosen.append(hits[0])
    return chosen


# =============================================================================
# Assignments: resubmission, absence, exemption
# =============================================================================


async def _find_submission(arguments: dict[str, Any], context: ToolExecutionContext) -> Any:
    """One submission: by id, or by the assignment's title and the student's name."""
    from backend.schemas.base import PageParams
    from backend.services.assignment_service import AssignmentService

    service = AssignmentService(context.session)
    if arguments.get("submission_id"):
        return await service.get_submission(_uuid(arguments.get("submission_id"), "submission_id"), actor=context.user)

    title = (arguments.get("assignment_title") or "").strip()
    student = (arguments.get("student_name") or "").strip()
    if len(title) < 3 or not student:
        raise ValidationError("Give the assignment's title and the student's name (or the submission_id).")
    found, _ = await service.list_assignments(PageParams(limit=20, offset=0), actor=context.user, query=title)
    matches = _match_title(list(found), title)
    if not matches:
        raise NotFoundError("No assignment with that title on a course you can see.")
    if len(matches) > 1:
        raise ValidationError("More than one assignment matches: "
                              + "; ".join(a.title for a in matches[:6]) + ". Say which one.")
    subs, _ = await service.list_submissions(
        PageParams(limit=200, offset=0), actor=context.user, assignment_public_id=matches[0].public_id,
    )
    if not subs:
        raise ValidationError(f"Nobody has submitted '{matches[0].title}' yet.")
    try:
        (row,) = _pick_people(list(subs), [student], f"the submissions to '{matches[0].title}'",
                              label=lambda s: _name(s.student))
    except ValidationError as exc:
        if "Nobody called" in str(exc):
            raise ValidationError(
                f"{student} has no submission on '{matches[0].title}'. The LMS records absence and exemption on a "
                "submission, so it cannot be set for work never handed in; tell the tutor and suggest they ask the "
                "student to submit, or an administrator to record it."
            ) from exc
        raise
    return await service.get_submission(row.public_id, actor=context.user)


async def preview_request_resubmission(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    sub = await _find_submission(arguments, context)
    reason = " ".join(str(arguments.get("reason") or "").split())[:1000]
    if len(reason) < 5:
        raise ValidationError("Say what the student must change (the reason is sent to them).")
    if not sub.assignment.allow_resubmission:
        raise ValidationError(f"'{sub.assignment.title}' does not allow resubmission; it is set on the assignment.")
    summary = (f"Ask {_name(sub.student)} to resubmit '{sub.assignment.title}'. They are notified with this reason: "
               f"\"{reason}\".")
    if sub.grade is not None:
        summary += f" Their current mark ({sub.grade}) is hidden from them until the new work is marked and released."
    return ConfirmationPreview(summary=summary, bound_parameters={"submission_id": str(sub.public_id), "reason": reason})


async def handle_request_resubmission(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.services.assignment_service import AssignmentService

    sub = await _find_submission(arguments, context)
    reason = " ".join(str(arguments.get("reason") or "").split())[:1000]
    if str(sub.public_id) != _bound(arguments, "submission_id") or reason != _bound(arguments, "reason"):
        raise ValidationError("The request no longer matches what was confirmed; ask again.")
    row = await AssignmentService(context.session).request_resubmission(sub.public_id, actor=context.user, reason=reason)
    return {"success": True, "state": row.state.value,
            "message": f"{_name(sub.student)} has been asked to resubmit and notified."}


request_resubmission_tool = ToolDefinition(
    name="request_resubmission",
    description=(
        "Hand an assignment submission back to the student for another attempt, with the reason they must act on "
        "(they are notified). Name the assignment by title and the student by name, or pass submission_id. Only "
        "for assignments that allow resubmission. The tutor confirms first."
    ),
    policy=ToolPolicy(
        name="request_resubmission", description="Ask a student to resubmit",
        required_permissions=("assignment.grade",), allowed_roles=_STAFF,
        risk_level=RiskLevel.HIGH, requires_confirmation=True, audit_action="UPDATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "assignment_title": {"type": "string"},
            "student_name": {"type": "string"},
            "submission_id": {"type": "string"},
            "reason": {"type": "string", "description": "What the student must change; sent to them"},
        },
        "required": ["reason"],
    },
    handler=handle_request_resubmission,
    preview=preview_request_resubmission,
)


_STATUSES = {"ABSENT": "absent (counts as a nil result)", "EXEMPTED": "exempt (left out of their weighted total)"}


async def preview_set_submission_status(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    status = str(arguments.get("status") or "").strip().upper()
    if status not in _STATUSES:
        raise ValidationError("status must be ABSENT or EXEMPTED.")
    reason = " ".join(str(arguments.get("reason") or "").split())[:1000] or None
    if status == "EXEMPTED" and not reason:
        raise ValidationError("An exemption needs a reason (it is kept against the record).")
    sub = await _find_submission(arguments, context)
    summary = f"Mark {_name(sub.student)} as {_STATUSES[status]} on '{sub.assignment.title}'."
    if sub.grade is not None:
        summary += f" They currently have a mark of {sub.grade}; it stops counting."
    if reason:
        summary += f" Reason: {reason}."
    return ConfirmationPreview(summary=summary, bound_parameters={
        "submission_id": str(sub.public_id), "status": status, "reason": reason})


async def handle_set_submission_status(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.services.assignment_service import AssignmentService
    from backend.utils.enums import SubmissionState

    sub = await _find_submission(arguments, context)
    status = str(arguments.get("status") or "").strip().upper()
    reason = " ".join(str(arguments.get("reason") or "").split())[:1000] or None
    if (str(sub.public_id), status, reason) != (
        _bound(arguments, "submission_id"), _bound(arguments, "status"), _bound(arguments, "reason")
    ):
        raise ValidationError("The request no longer matches what was confirmed; ask again.")
    row = await AssignmentService(context.session).set_submission_state(
        sub.public_id, actor=context.user, state=SubmissionState(status), reason=reason)
    return {"success": True, "state": row.state.value,
            "message": f"{_name(sub.student)} is recorded as {_STATUSES[status]}."}


set_submission_status_tool = ToolDefinition(
    name="set_submission_status",
    description=(
        "Record that a student was ABSENT for an assignment (a nil result) or is EXEMPTED from it (left out of "
        "their total; needs a reason). Works on a submission that exists -- name the assignment and the student. "
        "The tutor confirms first."
    ),
    policy=ToolPolicy(
        name="set_submission_status", description="Record an absence or exemption",
        required_permissions=("assignment.grade",), allowed_roles=_STAFF,
        risk_level=RiskLevel.HIGH, requires_confirmation=True, audit_action="UPDATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "assignment_title": {"type": "string"},
            "student_name": {"type": "string"},
            "submission_id": {"type": "string"},
            "status": {"type": "string", "enum": ["ABSENT", "EXEMPTED"]},
            "reason": {"type": "string"},
        },
        "required": ["status"],
    },
    handler=handle_set_submission_status,
    preview=preview_set_submission_status,
)


# =============================================================================
# Which class
# =============================================================================


async def _find_class(arguments: dict[str, Any], context: ToolExecutionContext) -> Any:
    """One class session: by id, or a batch's class on a date, or its latest class that has started.

    Read through `SessionService.get`, so a class the caller cannot see is the
    same "not found" as one that does not exist. Never a future class: marks
    and recordings belong to a class that has happened.
    """
    from sqlalchemy import func, select

    from backend.models.batch import Batch, BatchSession
    from backend.services.session_service import SessionService

    service = SessionService(context.session)
    if arguments.get("session_id"):
        return await service.get(_uuid(arguments.get("session_id"), "session_id"), actor=context.user)
    code = (arguments.get("batch_code") or "").strip()
    if not code:
        raise ValidationError("Name the batch (batch_code), optionally with the class date, or give session_id.")
    stmt = (
        select(BatchSession.public_id)
        .join(Batch, Batch.id == BatchSession.batch_id)
        .where(func.lower(Batch.batch_code) == code.lower(), BatchSession.cancelled_at.is_(None))
    )
    when = arguments.get("date")
    if when:
        try:
            day = date.fromisoformat(str(when)[:10])
        except ValueError as exc:
            raise ValidationError("date must be YYYY-MM-DD.") from exc
        start = datetime(day.year, day.month, day.day, tzinfo=UTC) - timedelta(hours=14)
        stmt = stmt.where(BatchSession.session_start_time >= start,
                          BatchSession.session_start_time < start + timedelta(hours=38))
    stmt = stmt.where(BatchSession.session_start_time <= datetime.now(UTC) + timedelta(hours=1))
    found = (await context.session.execute(stmt.order_by(BatchSession.session_start_time.desc()))).scalars().all()
    if not found:
        raise NotFoundError("No class of that batch has taken place" + (" on that date." if when else " yet."))
    if when and len(found) > 1:
        raise ValidationError("That batch had more than one class that day; give session_id.")
    return await service.get(found[0], actor=context.user)


def _class_label(row: Any) -> str:
    when = row.session_start_time.strftime("%d %b %Y %H:%M UTC") if row.session_start_time else "unscheduled"
    code = getattr(getattr(row, "batch", None), "batch_code", None) or "the batch"
    return f"{code} class on {when}"


# =============================================================================
# Class performance
# =============================================================================

_CRITERIA = ("participation", "interaction", "preparation", "practical", "presentation", "teamwork",
             "communication", "professionalism")


def _score(value: Any, field: str, top: Decimal) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        mark = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"{field} must be a number.") from exc
    if mark < 0 or mark > top:
        raise ValidationError(f"{field} must be between 0 and {top}.")
    return mark


async def _resolve_class_marks(arguments: dict[str, Any], context: ToolExecutionContext) -> tuple[Any, list[dict[str, Any]], list[str], Decimal]:
    from backend.services.class_performance_service import ClassPerformanceService

    _require(context, "class_performance.create", "record class performance marks")
    klass = await _find_class(arguments, context)
    service = ClassPerformanceService(context.session)
    _, roster, _, may_record = await service.sheet(klass.public_id, actor=context.user)
    if not may_record:
        raise AuthorizationError("Only the class's assigned tutor can record its class performance marks.")
    top = _score(arguments.get("max_score"), "max_score", Decimal("1000")) or Decimal("10")
    rows = arguments.get("entries") or []
    if not isinstance(rows, list) or not rows:
        raise ValidationError("Give at least one student with their marks.")

    entries, lines = [], []
    for item in rows:
        if not isinstance(item, dict):
            raise ValidationError("Each entry is {student_name, overall_score or criteria, comment}.")
        (person,) = _pick_people(roster, [item.get("student_name") or ""], "this class's register")
        entry: dict[str, Any] = {"student_id": str(person.public_id)}
        named = item.get("criteria") or {}
        if not isinstance(named, dict):
            raise ValidationError("criteria is {criterion: score}, e.g. {\"participation\": 9}.")
        unknown = sorted(set(named) - set(_CRITERIA))
        if unknown:
            raise ValidationError(f"Unknown criteria: {', '.join(unknown)}. Use: {', '.join(_CRITERIA)}.")
        for field in _CRITERIA:
            entry[field] = _score(named.get(field, item.get(field)), field, top)
        entry["overall_score"] = _score(item.get("overall_score"), "overall_score", top)
        # A model asked for "Liva 8/10" sent all eight criteria as 0 next to the 8.
        # Every criterion at exactly zero beside a non-zero overall is padding, not
        # eight observations of "nothing" -- stored, it would read as a student who
        # failed every criterion. A tutor who means zeros says so per criterion.
        if entry["overall_score"] and all(entry[f] == 0 for f in _CRITERIA):
            for f in _CRITERIA:
                entry[f] = None
        if entry["overall_score"] is None and all(entry[f] is None for f in _CRITERIA):
            raise ValidationError(f"No mark given for {_name(person)}: give overall_score or criteria scores.")
        comment = " ".join(str(item.get("comment") or "").split())[:2000] or None
        entry["comment"] = comment
        if any(e["student_id"] == entry["student_id"] for e in entries):
            raise ValidationError(f"{_name(person)} appears twice.")
        entries.append(entry)
        # Everything that will be stored is shown -- an overall figure must not hide
        # criteria saved beside it.
        given = [f"{f} {entry[f]}" for f in _CRITERIA if entry[f] is not None]
        if entry["overall_score"] is not None:
            given.insert(0, f"overall {entry['overall_score']}")
        figure = ", ".join(given)
        lines.append(f"{_name(person)}: {figure}" + (f" ({comment[:80]})" if comment else ""))
    return klass, entries, lines, top


def _jsonable(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: (str(v) if isinstance(v, Decimal) else v) for k, v in e.items()} for e in entries]


async def preview_record_class_performance(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    klass, entries, lines, top = await _resolve_class_marks(arguments, context)
    summary = (f"Record class performance (out of {top}) for the {_class_label(klass)}: " + "; ".join(lines)
               + ". Saved as a draft: students do not see these until the marks are released.")
    return ConfirmationPreview(summary=summary, affected_records_count=len(entries), bound_parameters={
        "session_id": str(klass.public_id), "entries": _jsonable(entries), "max_score": str(top)})


async def handle_record_class_performance(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.services.class_performance_service import ClassPerformanceService

    klass, entries, lines, top = await _resolve_class_marks(arguments, context)
    if (str(klass.public_id), _jsonable(entries), str(top)) != (
        _bound(arguments, "session_id"), _bound(arguments, "entries"), _bound(arguments, "max_score")
    ):
        raise ValidationError("The marks no longer match what was confirmed; ask again.")
    for e in entries:
        e["student_id"] = uuid.UUID(e["student_id"])
    saved = await ClassPerformanceService(context.session).save(klass.public_id, entries, actor=context.user, max_score=top)
    return {"success": True, "saved": len(saved), "lines": lines,
            "message": f"Recorded class performance for {len(saved)} student(s) as a draft (not yet released)."}


record_class_performance_tool = ToolDefinition(
    name="record_class_performance",
    description=(
        "Record class performance marks for students in a class the tutor taught. For each student give EITHER "
        "an overall_score alone (enough on its own -- do not ask for criteria) OR any of the eight criteria "
        "(participation, interaction, preparation, practical, presentation, teamwork, communication, "
        "professionalism) that the tutor mentioned, plus their remark as the comment. Pick the class by batch_code "
        "(+ date, default the latest class held) or session_id. Marks are out of max_score (default 10) and saved "
        "as a draft. The tutor confirms first."
    ),
    policy=ToolPolicy(
        name="record_class_performance", description="Record class performance marks",
        required_permissions=("class_performance.create",), allowed_roles=_STAFF,
        risk_level=RiskLevel.HIGH, requires_confirmation=True, audit_action="UPDATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "batch_code": {"type": "string"},
            "date": {"type": "string", "description": "Class date YYYY-MM-DD; default the latest class held"},
            "session_id": {"type": "string"},
            "max_score": {"type": "number", "description": "What each mark is out of (default 10)"},
            "entries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "student_name": {"type": "string"},
                        "overall_score": {"type": "number"},
                        # One object holding only what the tutor mentioned. Eight
                        # separate number fields were filled in by the model with
                        # zeros for every criterion nobody had marked.
                        "criteria": {
                            "type": "object",
                            "description": "Only criteria the tutor actually gave, e.g. {\"participation\": 9}. "
                                           "Allowed: " + ", ".join(_CRITERIA) + ". Never fill in the others.",
                            "additionalProperties": {"type": "number"},
                        },
                        "comment": {"type": "string"},
                    },
                    "required": ["student_name"],
                },
            },
        },
        "required": ["entries"],
    },
    handler=handle_record_class_performance,
    preview=preview_record_class_performance,
)


# =============================================================================
# Class recordings
# =============================================================================


async def _find_file(context: ToolExecutionContext, name: str) -> Any:
    from backend.schemas.base import PageParams
    from backend.services.resource_service import ResourceService

    wanted = " ".join(name.split())
    if len(wanted) < 3:
        raise ValidationError("Give the file's name (at least 3 characters).")
    rows, _ = await ResourceService(context.session).list_resources(
        PageParams(limit=20, offset=0), actor=context.user, query=wanted)
    rows = list(rows)
    exact = [r for r in rows if (r.name or "").strip().lower() == wanted.lower()]
    hits = exact or rows
    if not hits:
        raise NotFoundError(f"No file called '{wanted}' in the library you can see.")
    if len(hits) > 1:
        raise ValidationError(f"'{wanted}' matches several files: " + "; ".join(r.name for r in hits[:8])
                              + ". Say which one.")
    return hits[0]


async def _resolve_recording(arguments: dict[str, Any], context: ToolExecutionContext) -> tuple[Any, str, str]:
    """(class, 'link'|'file', value). The link is validated as the console validates it."""
    from backend.core.video_links import VideoLinkError, validate_video_url

    _require(context, "session.update", "publish class recordings")
    klass = await _find_class(arguments, context)
    link, file_name = (arguments.get("link") or "").strip(), (arguments.get("file_name") or "").strip()
    if bool(link) == bool(file_name):
        raise ValidationError("Give either the recording's link or the name of a video file in the library.")
    if link:
        try:
            return klass, "link", validate_video_url(link)
        except (VideoLinkError, ValueError) as exc:
            raise ValidationError(f"That link cannot be used as a recording: {exc}") from exc
    from backend.services.resource_service import ResourceService
    from backend.utils.enums import ResourcePermissionLevel

    resource = await _find_file(context, file_name)
    await ResourceService(context.session).require_level(resource, context.user, ResourcePermissionLevel.EDIT)
    return klass, "file", str(resource.public_id)


async def preview_publish_class_recording(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    klass, kind, value = await _resolve_recording(arguments, context)
    what = ("the link you gave (watched through the LMS; the provider's own player is shown)" if kind == "link"
            else f"the library file '{(await _find_file(context, arguments.get('file_name') or '')).name}' "
                 "(streamed by the LMS, no download button)")
    replacing = " It replaces the recording already published." if (klass.recording_link or klass.recording_resource_id) else ""
    summary = (f"Publish {what} as the recording of the {_class_label(klass)}. Everyone in that class, their "
               f"guardians and corporate managers can watch it.{replacing}")
    return ConfirmationPreview(summary=summary, bound_parameters={
        "session_id": str(klass.public_id), "kind": kind, "value": value})


async def handle_publish_class_recording(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.schemas.session import SessionUpdateRequest
    from backend.services.session_service import SessionService

    klass, kind, value = await _resolve_recording(arguments, context)
    if (str(klass.public_id), kind, value) != (
        _bound(arguments, "session_id"), _bound(arguments, "kind"), _bound(arguments, "value")
    ):
        raise ValidationError("The recording no longer matches what was confirmed; ask again.")
    service = SessionService(context.session)
    if kind == "link":
        await service.update(klass.public_id, SessionUpdateRequest(recording_link=value), actor=context.user)
    else:
        await service.attach_recording(klass.public_id, resource_public_id=uuid.UUID(value), actor=context.user)
    return {"success": True, "message": f"Published the recording of the {_class_label(klass)}."}


publish_class_recording_tool = ToolDefinition(
    name="publish_class_recording",
    description=(
        "Publish a class recording so the class can watch it: either a link (Zoom cloud, YouTube, Vimeo, Google "
        "Drive) or the name of a video file already uploaded to the library. Pick the class by batch_code (+ date) "
        "or session_id. The tutor confirms first."
    ),
    policy=ToolPolicy(
        name="publish_class_recording", description="Publish a class recording",
        required_permissions=("session.update",), allowed_roles=_STAFF,
        risk_level=RiskLevel.HIGH, requires_confirmation=True, audit_action="UPDATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "batch_code": {"type": "string"},
            "date": {"type": "string", "description": "Class date YYYY-MM-DD; default the latest class held"},
            "session_id": {"type": "string"},
            "link": {"type": "string", "description": "The recording's URL"},
            "file_name": {"type": "string", "description": "A video file in the library"},
        },
    },
    handler=handle_publish_class_recording,
    preview=preview_publish_class_recording,
)


# =============================================================================
# Sharing files
# =============================================================================


async def _resolve_share(arguments: dict[str, Any], context: ToolExecutionContext) -> tuple[list[Any], list[Any], str]:
    from backend.services.resource_audience import ResourceShareAudience

    _require(context, "resource.update", "share files")
    names = [str(n) for n in (arguments.get("file_names") or []) if str(n).strip()]
    if not names:
        raise ValidationError("Name at least one file to share.")
    files = []
    for n in names:
        f = await _find_file(context, n)
        if f not in files:
            files.append(f)

    level = str(arguments.get("level") or "VIEW").strip().upper()
    if level not in {"VIEW", "DOWNLOAD"}:
        raise ValidationError("level must be VIEW (watch/read only) or DOWNLOAD.")

    audience = ResourceShareAudience(context.session)
    candidates = await audience.search(context.user, limit=500)
    people: list[Any] = []
    batch = (arguments.get("batch_code") or "").strip().lower()
    if batch:
        in_batch = [c for c in candidates if c.role == "Student"
                    and any((p.batch_code or "").lower() == batch for p in c.placements)]
        if arguments.get("include_guardians"):
            in_batch += [c for c in candidates if c.role == "Guardian"
                         and any((p.batch_code or "").lower() == batch for p in c.placements)]
        if not in_batch:
            raise ValidationError(f"Nobody in batch '{arguments.get('batch_code')}' is someone you can share with.")
        people.extend(in_batch)
    people.extend(c for c in _pick_people(candidates, [str(n) for n in (arguments.get("people") or [])],
                                          "the people you can share with", label=lambda c: c.name)
                  if c not in people)
    if not people:
        raise ValidationError("Say who to share with: a batch_code, or people by name.")
    # The service is the gate: it refuses anybody outside the caller's audience
    # and any file the caller may not manage. Resolved here only to show names.
    await audience.resolve(context.user, [p.public_id for p in people])
    return files, people, level


async def preview_share_files(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    files, people, level = await _resolve_share(arguments, context)
    who = ", ".join(sorted(p.name for p in people)[:12]) + (" ..." if len(people) > 12 else "")
    how = "view only (no download)" if level == "VIEW" else "view and download"
    summary = (f"Share {len(files)} file(s) -- " + ", ".join(f.name for f in files) + f" -- with {len(people)} "
               f"person(s), {how}: {who}. They will find them under Shared with me.")
    return ConfirmationPreview(summary=summary, affected_records_count=len(people), bound_parameters={
        "resource_ids": sorted(str(f.public_id) for f in files),
        "user_ids": sorted(str(p.public_id) for p in people), "level": level})


async def handle_share_files(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.services.resource_service import ResourceService
    from backend.utils.enums import ResourcePermissionLevel

    files, people, level = await _resolve_share(arguments, context)
    if (sorted(str(f.public_id) for f in files), sorted(str(p.public_id) for p in people), level) != (
        _bound(arguments, "resource_ids"), _bound(arguments, "user_ids"), _bound(arguments, "level")
    ):
        raise ValidationError("The files or people no longer match what was confirmed; ask again.")
    await ResourceService(context.session).share_many(
        [f.public_id for f in files], [p.public_id for p in people], actor=context.user,
        level=ResourcePermissionLevel(level))
    return {"success": True, "message": f"Shared {len(files)} file(s) with {len(people)} person(s)."}


share_files_tool = ToolDefinition(
    name="share_files",
    description=(
        "Share files from the library with a whole batch (batch_code; include_guardians to add their guardians) "
        "and/or named people, as VIEW (read/watch only, default) or DOWNLOAD. Only people the tutor may share with "
        "(their students, those students' guardians, administrators). The tutor confirms first."
    ),
    policy=ToolPolicy(
        name="share_files", description="Share library files",
        required_permissions=("resource.update",), allowed_roles=_STAFF,
        risk_level=RiskLevel.HIGH, requires_confirmation=True, audit_action="UPDATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "file_names": {"type": "array", "items": {"type": "string"}},
            "batch_code": {"type": "string"},
            "include_guardians": {"type": "boolean"},
            "people": {"type": "array", "items": {"type": "string"}, "description": "Names"},
            "level": {"type": "string", "enum": ["VIEW", "DOWNLOAD"]},
        },
        "required": ["file_names"],
    },
    handler=handle_share_files,
    preview=preview_share_files,
)


TEACHING_ACTION_TOOLS = (
    request_resubmission_tool,
    set_submission_status_tool,
    record_class_performance_tool,
    publish_class_recording_tool,
    share_files_tool,
)

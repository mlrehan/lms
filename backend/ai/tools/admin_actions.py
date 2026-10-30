"""The academic office's work, as confirmed actions.

What a Super Admin (or an Administrator, where the role holds the permission)
could do on the console and the assistant could only describe: rebuild a
batch's grade book, issue and certify transcripts, link a guardian or a
corporate manager to a student, and set up a course, a batch and its tutors.

Each tool calls the service the console's own route calls, as the person
asking, and requires the permission that route requires -- so the assistant
can never do more than the same person could by clicking. All are HIGH risk
with a confirmation whose summary is written here, from the records resolved,
and whose targets are bound into the ticket.

Two rules worth not re-litigating:

* **A link between people is an access grant.** A guardian or corporate
  manager linked to a student reads that student's grades, attendance and
  work from then on. The preview says so in those words, because "link Gwen
  to Liva" undersells what is being confirmed.
* **Certifying is per person, and refused ones are named.** Finalising a
  batch's transcripts certifies each student separately; a transcript with no
  final percentage cannot be certified, and the preview lists those students
  by name instead of quietly skipping them.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select

from backend.ai.security import RiskLevel, SecurityPolicyEngine, ToolPolicy
from backend.ai.tools.admin_tools import _display_name, _require_super_admin
from backend.ai.tools.registry import BOUND_PREFIX, ConfirmationPreview, ToolDefinition, ToolExecutionContext
from backend.ai.tools.superadmin_tools import _find_user
from backend.core.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from backend.utils.enums import Roles

# Super Admin only: `_find_user` matches on email address, which only a holder of
# `user.view_contact` may confirm exists -- offered to an Administrator it would be an
# address checker.
_OFFICE = (Roles.SUPER_ADMIN.value,)


def _bound(arguments: dict[str, Any], key: str) -> Any:
    return arguments.get(f"{BOUND_PREFIX}{key}")


def _require(context: ToolExecutionContext, permission: str, what: str) -> None:
    # The role too, not only the permission: a Tutor holds `grade.update` to mark
    # work, and the registry's role list is the only other thing between a tutor
    # and rebuilding any batch's grade book.
    _require_super_admin(context.user, what)
    if permission not in SecurityPolicyEngine.caller_permissions(context.user):
        raise AuthorizationError(f"You do not have permission to {what}.")


def _same(arguments: dict[str, Any], **now: Any) -> None:
    """The handler re-resolves; what it found must be what was confirmed."""
    for key, value in now.items():
        if value != _bound(arguments, key):
            raise ValidationError("This no longer matches what was confirmed; ask again.")


async def _batch(context: ToolExecutionContext, code: Any) -> Any:
    """A batch by its code, read through the scoped service like the batch screen."""
    from backend.models.batch import Batch
    from backend.services.batch_service import BatchService

    text = str(code or "").strip()
    if not text:
        raise ValidationError("Name the batch by its code.")
    public_id = (await context.session.execute(
        select(Batch.public_id).where(func.lower(Batch.batch_code) == text.lower()))).scalar_one_or_none()
    if public_id is None:
        raise NotFoundError(f"Batch '{text}' not found.")
    return await BatchService(context.session).get(public_id, actor=context.user)


async def _course(context: ToolExecutionContext, ident: Any) -> Any:
    """A course by its code or exact title, through the scoped service."""
    from backend.models.course import Course
    from backend.services.course_service import CourseService

    text = " ".join(str(ident or "").split())
    if len(text) < 2:
        raise ValidationError("Name the course by its code or title.")
    rows = (await context.session.execute(select(Course.public_id, Course.title).where(
        Course.deleted_at.is_(None),
        (func.lower(Course.code) == text.lower()) | (func.lower(Course.title) == text.lower()),
    ))).all()
    if not rows:
        rows = (await context.session.execute(select(Course.public_id, Course.title).where(
            Course.deleted_at.is_(None), func.lower(Course.title).like(f"%{text.lower()}%")).limit(6))).all()
    if not rows:
        raise NotFoundError(f"No course matches '{text}'.")
    if len(rows) > 1:
        raise ValidationError("More than one course matches: " + "; ".join(r.title for r in rows) + ". Say which one.")
    return await CourseService(context.session).get(rows[0].public_id, actor=context.user)


def _has_role(user: Any, role: Roles) -> bool:
    return role.value in {r.name for r in (user.roles or [])}


# =============================================================================
# Grade book
# =============================================================================


async def preview_sync_gradebook(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    _require(context, "grade.update", "rebuild a grade book")
    batch = await _batch(context, arguments.get("batch_code"))
    summary = (f"Rebuild the grade book for batch {batch.batch_code} from its marked assignments, completed quizzes, "
               "recorded exam results and attendance. Existing derived entries are corrected, not duplicated; "
               "manual entries are left alone; unmarked work stays out (it is never counted as zero).")
    return ConfirmationPreview(summary=summary, bound_parameters={"batch_id": str(batch.public_id)})


async def handle_sync_gradebook(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.services.gradebook_service import GradeBookService

    _require(context, "grade.update", "rebuild a grade book")
    batch = await _batch(context, arguments.get("batch_code"))
    _same(arguments, batch_id=str(batch.public_id))
    result = await GradeBookService(context.session).sync_batch(batch.public_id, actor=context.user)
    return {"success": True, "batch": batch.batch_code, "result": result,
            "message": f"Grade book for {batch.batch_code} rebuilt: {result}."}


sync_gradebook_tool = ToolDefinition(
    name="sync_gradebook",
    description=(
        "Rebuild one batch's grade book from its marked work, quiz attempts, exam results and attendance "
        "(idempotent: running it twice changes nothing the second time). Name the batch by code. Confirmed first."
    ),
    policy=ToolPolicy(
        name="sync_gradebook", description="Rebuild a batch's grade book",
        required_permissions=("grade.update",), allowed_roles=_OFFICE,
        risk_level=RiskLevel.HIGH, requires_confirmation=True, audit_action="UPDATE",
    ),
    parameters_schema={"type": "object", "properties": {"batch_code": {"type": "string"}}, "required": ["batch_code"]},
    handler=handle_sync_gradebook,
    preview=preview_sync_gradebook,
)


# =============================================================================
# Transcripts
# =============================================================================


async def preview_generate_transcripts(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    _require(context, "transcript.generate", "generate transcripts")
    batch = await _batch(context, arguments.get("batch_code"))
    summary = (f"Generate (or recompute) a provisional transcript for every enrolled student in batch "
               f"{batch.batch_code}. Provisional transcripts are visible to staff only; already-finalised ones are "
               "left unchanged. Students and their guardians see a transcript only once it is finalised.")
    return ConfirmationPreview(summary=summary, bound_parameters={"batch_id": str(batch.public_id)})


async def handle_generate_transcripts(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.services.transcript_service import TranscriptService

    _require(context, "transcript.generate", "generate transcripts")
    batch = await _batch(context, arguments.get("batch_code"))
    _same(arguments, batch_id=str(batch.public_id))
    result = await TranscriptService(context.session).generate_for_batch(batch_id=batch.id, actor=context.user)
    return {"success": True, "batch": batch.batch_code, "result": result,
            "message": f"Transcripts for {batch.batch_code}: {result}."}


generate_transcripts_tool = ToolDefinition(
    name="generate_transcripts",
    description=(
        "Generate provisional transcripts for every enrolled student of a batch (staff-only until finalised). "
        "Computed from the released marks themselves: sync_gradebook is NOT needed first. Confirmed first; "
        "finalising is a separate step (finalise_transcripts) after this one is confirmed."
    ),
    policy=ToolPolicy(
        name="generate_transcripts", description="Generate a batch's transcripts",
        required_permissions=("transcript.generate",), allowed_roles=_OFFICE,
        risk_level=RiskLevel.HIGH, requires_confirmation=True, audit_action="UPDATE",
    ),
    parameters_schema={"type": "object", "properties": {"batch_code": {"type": "string"}}, "required": ["batch_code"]},
    handler=handle_generate_transcripts,
    preview=preview_generate_transcripts,
)


async def _finalisable(arguments: dict[str, Any], context: ToolExecutionContext) -> tuple[Any, list[Any], list[str]]:
    from backend.services.transcript_service import TranscriptService

    _require(context, "grade.publish", "finalise transcripts")
    batch = await _batch(context, arguments.get("batch_code"))
    rows = list(await TranscriptService(context.session).list_for_batch(batch_id=batch.id, actor=context.user))
    names = [" ".join(str(n).split()).lower() for n in (arguments.get("student_names") or []) if str(n).strip()]
    if names:
        chosen = []
        for wanted in names:
            hits = [t for t in rows if wanted in _display_name(t.student).lower()]
            if len(hits) != 1:
                raise ValidationError(f"'{wanted}' matches {len(hits)} transcripts in {batch.batch_code}; say exactly who.")
            chosen.append(hits[0])
        rows = chosen
    if not rows:
        raise ValidationError(f"Batch {batch.batch_code} has no transcripts yet; generate them first.")
    ready = [t for t in rows if not t.is_final and t.final_percentage is not None]
    refused = [f"{_display_name(t.student)} (no final percentage: a weighted component is not assessed yet)"
               for t in rows if not t.is_final and t.final_percentage is None]
    refused += [f"{_display_name(t.student)} (already finalised)" for t in rows if t.is_final]
    return batch, ready, refused


async def preview_finalise_transcripts(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    batch, ready, refused = await _finalisable(arguments, context)
    if not ready:
        raise ValidationError(f"Nothing in {batch.batch_code} can be finalised: " + "; ".join(refused) + ".")
    who = ", ".join(f"{_display_name(t.student)} ({t.final_percentage}%)" for t in ready)
    summary = (f"Finalise {len(ready)} transcript(s) in {batch.batch_code}: {who}. Finalising certifies them, freezes "
               "the figures and makes each visible to the student, their guardians and corporate managers.")
    if refused:
        summary += " Not included: " + "; ".join(refused) + "."
    return ConfirmationPreview(summary=summary, affected_records_count=len(ready), bound_parameters={
        "transcript_ids": sorted(str(t.public_id) for t in ready)})


async def handle_finalise_transcripts(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.services.transcript_service import TranscriptService

    batch, ready, _ = await _finalisable(arguments, context)
    _same(arguments, transcript_ids=sorted(str(t.public_id) for t in ready))
    service = TranscriptService(context.session)
    for t in ready:
        await service.finalise(t.public_id, actor=context.user)
    return {"success": True, "finalised": len(ready),
            "message": f"Finalised {len(ready)} transcript(s) in {batch.batch_code}; students can now see them."}


finalise_transcripts_tool = ToolDefinition(
    name="finalise_transcripts",
    description=(
        "Certify (finalise) a batch's provisional transcripts, all of them or named students only. Finalised "
        "transcripts are frozen and become visible to students, guardians and managers. Transcripts with no final "
        "percentage cannot be finalised and are listed. Confirmed first."
    ),
    policy=ToolPolicy(
        name="finalise_transcripts", description="Finalise transcripts",
        required_permissions=("grade.publish",), allowed_roles=_OFFICE,
        risk_level=RiskLevel.HIGH, requires_confirmation=True, audit_action="UPDATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "batch_code": {"type": "string"},
            "student_names": {"type": "array", "items": {"type": "string"}, "description": "Only these students"},
        },
        "required": ["batch_code"],
    },
    handler=handle_finalise_transcripts,
    preview=preview_finalise_transcripts,
)


# =============================================================================
# Guardian and manager links
# =============================================================================

_LINKS = {
    "guardian": ("guardian", Roles.GUARDIAN, "guardian", "student_guardians", "guardian_id"),
    "manager": ("managed_student", Roles.CORPORATE_MANAGER, "corporate manager", "manager_students", "manager_id"),
}


async def _link_change(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    kind = str(arguments.get("kind") or "").strip().lower()
    if kind not in _LINKS:
        raise ValidationError("kind must be guardian or manager.")
    module, role, label, table, column = _LINKS[kind]
    unlink = bool(arguments.get("unlink"))
    _require(context, f"{module}.{'delete' if unlink else 'create'}", f"{'remove' if unlink else 'create'} {label} links")

    person = await _find_user(context, arguments.get("person"))
    student = await _find_user(context, arguments.get("student"))
    if not _has_role(person, role):
        raise ValidationError(f"{_display_name(person)} does not hold the {role.value} role.")
    if not _has_role(student, Roles.STUDENT):
        raise ValidationError(f"{_display_name(student)} is not a student.")

    from sqlalchemy import text

    existing = (await context.session.execute(text(
        f"SELECT public_id FROM {table} WHERE {column} = :p AND student_id = :s"),  # noqa: S608 -- fixed names
        {"p": person.id, "s": student.id})).scalar_one_or_none()
    if unlink and existing is None:
        raise ConflictError(f"{_display_name(person)} is not linked to {_display_name(student)}.")
    if not unlink and existing is not None:
        raise ConflictError(f"{_display_name(person)} is already linked to {_display_name(student)}.")
    return {"kind": kind, "unlink": unlink, "person": person, "student": student, "link_id": existing,
            "relationship": " ".join(str(arguments.get("relationship") or "").split())[:50] or None,
            "is_primary": bool(arguments.get("is_primary")), "label": label}


async def preview_link_person(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    c = await _link_change(arguments, context)
    p, s = _display_name(c["person"]), _display_name(c["student"])
    if c["unlink"]:
        summary = (f"Remove {p} as {c['label']} of {s}. {p} immediately stops seeing {s}'s grades, attendance and "
                   "work.")
    else:
        summary = (f"Link {p} as {c['label']} of {s}" + (f" ({c['relationship']})" if c["relationship"] else "")
                   + f". From then on {p} can read {s}'s grades, attendance, submissions and transcripts, and both "
                   "are notified.")
    return ConfirmationPreview(summary=summary, bound_parameters={
        "kind": c["kind"], "unlink": c["unlink"], "person_id": str(c["person"].public_id),
        "student_id": str(c["student"].public_id)})


async def handle_link_person(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    c = await _link_change(arguments, context)
    _same(arguments, kind=c["kind"], unlink=c["unlink"], person_id=str(c["person"].public_id),
          student_id=str(c["student"].public_id))
    if c["kind"] == "guardian":
        from backend.schemas.guardian import CreateGuardianLinkRequest
        from backend.services.guardian_service import GuardianService

        service: Any = GuardianService(context.session)
        payload: Any = None if c["unlink"] else CreateGuardianLinkRequest(
            guardian_id=c["person"].public_id, student_id=c["student"].public_id,
            relationship_type=c["relationship"], is_primary=c["is_primary"])
    else:
        from backend.schemas.managed_student import CreateManagedStudentRequest
        from backend.services.managed_student_service import ManagedStudentService

        service = ManagedStudentService(context.session)
        payload = None if c["unlink"] else CreateManagedStudentRequest(
            manager_id=c["person"].public_id, student_id=c["student"].public_id,
            relationship_type=c["relationship"], is_primary=c["is_primary"])
    if c["unlink"]:
        await service.delete(c["link_id"], actor=context.user)
    else:
        await service.create(payload, actor=context.user)
    verb = "removed" if c["unlink"] else "linked"
    return {"success": True, "message": f"{_display_name(c['person'])} {verb} as {c['label']} of "
                                        f"{_display_name(c['student'])}."}


link_person_tool = ToolDefinition(
    name="link_person",
    description=(
        "Link (or with unlink=true, remove) a guardian (kind=guardian) or corporate manager (kind=manager) to a "
        "student. Linking gives them read access to that student's records. Name people by full name, email or "
        "username. Confirmed first."
    ),
    policy=ToolPolicy(
        name="link_person", description="Link a guardian or manager to a student",
        allowed_roles=_OFFICE, risk_level=RiskLevel.HIGH, requires_confirmation=True, audit_action="UPDATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["guardian", "manager"]},
            "person": {"type": "string", "description": "The guardian or manager"},
            "student": {"type": "string"},
            "relationship": {"type": "string", "description": "e.g. Mother, Line manager"},
            "is_primary": {"type": "boolean"},
            "unlink": {"type": "boolean"},
        },
        "required": ["kind", "person", "student"],
    },
    handler=handle_link_person,
    preview=preview_link_person,
)


# =============================================================================
# Courses, batches, tutors
# =============================================================================


def _course_request(arguments: dict[str, Any]) -> Any:
    from pydantic import ValidationError as PydanticError

    from backend.schemas.course import CourseCreateRequest

    fields = {k: arguments.get(k) for k in ("title", "code", "description", "duration_hours", "prerequisites",
                                            "price", "course_link") if arguments.get(k) not in (None, "")}
    if arguments.get("level"):
        fields["level"] = str(arguments["level"]).upper()
    try:
        return CourseCreateRequest(**fields)
    except PydanticError as exc:
        raise ValidationError("; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())) from exc


async def preview_create_course(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    from backend.services.course_service import CourseService

    _require(context, "course.create", "create courses")
    req = _course_request(arguments)
    service = CourseService(context.session)
    await service._assert_title_free(req.title)  # noqa: SLF001 -- refuse before asking, not after
    code = req.code or await service.suggest_code(req.title)
    await service._assert_code_free(code)  # noqa: SLF001
    bits = [f"level {req.level.value.title()}"]
    if req.price is not None:
        bits.append(f"price {req.price}")
    if req.duration_hours:
        bits.append(f"{req.duration_hours} hours")
    summary = (f"Create course '{req.title}' with code {code} ({', '.join(bits)}). It starts as a DRAFT, hidden from "
               "students until published.")
    return ConfirmationPreview(summary=summary, bound_parameters={"title": req.title, "code": code})


async def handle_create_course(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.services.course_service import CourseService

    _require(context, "course.create", "create courses")
    req = _course_request(arguments)
    _same(arguments, title=req.title)
    req = req.model_copy(update={"code": _bound(arguments, "code")})
    course = await CourseService(context.session).create(req, actor=context.user)
    return {"success": True, "course_id": str(course.public_id), "code": course.code,
            "message": f"Created course '{course.title}' ({course.code}) as a draft."}


create_course_tool = ToolDefinition(
    name="create_course",
    description=(
        "Create a course (starts as a DRAFT): title, optional code (suggested when omitted), level "
        "(BEGINNER/INTERMEDIATE/ADVANCED), description, duration_hours, prerequisites, price, course_link. "
        "Confirmed first."
    ),
    policy=ToolPolicy(
        name="create_course", description="Create a course",
        required_permissions=("course.create",), allowed_roles=_OFFICE,
        risk_level=RiskLevel.HIGH, requires_confirmation=True, audit_action="CREATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"}, "code": {"type": "string"},
            "level": {"type": "string", "enum": ["BEGINNER", "INTERMEDIATE", "ADVANCED"]},
            "description": {"type": "string"}, "duration_hours": {"type": "integer"},
            "prerequisites": {"type": "string"}, "price": {"type": "number"}, "course_link": {"type": "string"},
        },
        "required": ["title"],
    },
    handler=handle_create_course,
    preview=preview_create_course,
)


def _batch_request(arguments: dict[str, Any]) -> Any:
    from pydantic import ValidationError as PydanticError

    from backend.schemas.batch import BatchCreateRequest

    fields: dict[str, Any] = {"batch_code": " ".join(str(arguments.get("batch_code") or "").split())}
    for key in ("capacity", "number_of_sessions", "duration_hours", "notes"):
        if arguments.get(key) not in (None, ""):
            fields[key] = arguments[key]
    for key in ("start_date", "end_date"):
        if arguments.get(key):
            try:
                fields[key] = date.fromisoformat(str(arguments[key])[:10])
            except ValueError as exc:
                raise ValidationError(f"{key} must be YYYY-MM-DD.") from exc
    try:
        return BatchCreateRequest(**fields)
    except PydanticError as exc:
        raise ValidationError("; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())) from exc


async def preview_create_batch(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    from backend.models.batch import Batch

    _require(context, "batch.create", "create batches")
    course = await _course(context, arguments.get("course"))
    req = _batch_request(arguments)
    if (await context.session.execute(select(Batch.id).where(func.lower(Batch.batch_code) == req.batch_code.lower()))).first():
        raise ConflictError(f"A batch with code {req.batch_code} already exists.")
    if req.start_date and req.end_date and req.end_date < req.start_date:
        raise ValidationError("end_date is before start_date.")
    bits = [f"capacity {req.capacity}" if req.capacity else "no capacity limit"]
    if req.start_date:
        bits.append(f"{req.start_date} to {req.end_date or '?'}")
    summary = (f"Create batch {req.batch_code} on course '{course.title}' ({', '.join(bits)}). No classes are "
               "scheduled and nobody is enrolled yet.")
    return ConfirmationPreview(summary=summary, bound_parameters={
        "course_id": str(course.public_id), "batch_code": req.batch_code})


async def handle_create_batch(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.services.batch_service import BatchService

    _require(context, "batch.create", "create batches")
    course = await _course(context, arguments.get("course"))
    req = _batch_request(arguments)
    _same(arguments, course_id=str(course.public_id), batch_code=req.batch_code)
    batch = await BatchService(context.session).create(course.public_id, req, actor=context.user)
    return {"success": True, "batch_id": str(batch.public_id),
            "message": f"Created batch {batch.batch_code} on '{course.title}'."}


create_batch_tool = ToolDefinition(
    name="create_batch",
    description=(
        "Create a batch on a course (course by code or title). Only course and batch_code are required; capacity, "
        "start_date/end_date (YYYY-MM-DD), number_of_sessions and notes are optional -- never ask for them, use what "
        "was given. Classes are scheduled separately. Confirmed first."
    ),
    policy=ToolPolicy(
        name="create_batch", description="Create a batch",
        required_permissions=("batch.create",), allowed_roles=_OFFICE,
        risk_level=RiskLevel.HIGH, requires_confirmation=True, audit_action="CREATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "course": {"type": "string"}, "batch_code": {"type": "string"}, "capacity": {"type": "integer"},
            "start_date": {"type": "string"}, "end_date": {"type": "string"},
            "number_of_sessions": {"type": "integer"}, "notes": {"type": "string"},
        },
        "required": ["course", "batch_code"],
    },
    handler=handle_create_batch,
    preview=preview_create_batch,
)


async def _tutor_change(arguments: dict[str, Any], context: ToolExecutionContext) -> tuple[Any, list[Any], list[Any], list[Any]]:
    _require(context, "course.update", "assign tutors")
    course = await _course(context, arguments.get("course"))
    current = list(course.tutors or [])
    add = [await _find_user(context, n) for n in (arguments.get("add") or []) if str(n).strip()]
    remove = [await _find_user(context, n) for n in (arguments.get("remove") or []) if str(n).strip()]
    if not add and not remove:
        raise ValidationError("Say which tutors to add or remove.")
    for t in add:
        if not _has_role(t, Roles.TUTOR):
            raise ValidationError(f"{_display_name(t)} does not hold the TUTOR role.")
    final = [t for t in current if t.id not in {r.id for r in remove}]
    final += [t for t in add if t.id not in {f.id for f in final}]
    return course, final, add, remove


async def preview_assign_course_tutors(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    course, final, add, remove = await _tutor_change(arguments, context)
    parts = []
    if add:
        parts.append("add " + ", ".join(_display_name(t) for t in add))
    if remove:
        parts.append("remove " + ", ".join(_display_name(t) for t in remove))
    summary = (f"On course '{course.title}': {'; '.join(parts)}. Tutors of the course see its batches and the "
               f"students in them. Tutors afterwards: {', '.join(_display_name(t) for t in final) or 'none'}.")
    return ConfirmationPreview(summary=summary, bound_parameters={
        "course_id": str(course.public_id), "tutor_ids": sorted(str(t.public_id) for t in final)})


async def handle_assign_course_tutors(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.services.course_service import CourseService

    course, final, _, _ = await _tutor_change(arguments, context)
    _same(arguments, course_id=str(course.public_id), tutor_ids=sorted(str(t.public_id) for t in final))
    await CourseService(context.session).set_tutors(course.public_id, [t.public_id for t in final], actor=context.user)
    return {"success": True, "message": f"Tutors of '{course.title}' are now: "
                                        f"{', '.join(_display_name(t) for t in final) or 'none'}."}


assign_course_tutors_tool = ToolDefinition(
    name="assign_course_tutors",
    description=(
        "Add or remove tutors on a course (course by code or title; tutors by full name, email or username). "
        "Tutors of a course see its batches and students. Confirmed first."
    ),
    policy=ToolPolicy(
        name="assign_course_tutors", description="Assign course tutors",
        required_permissions=("course.update",), allowed_roles=_OFFICE,
        risk_level=RiskLevel.HIGH, requires_confirmation=True, audit_action="UPDATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "course": {"type": "string"},
            "add": {"type": "array", "items": {"type": "string"}},
            "remove": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["course"],
    },
    handler=handle_assign_course_tutors,
    preview=preview_assign_course_tutors,
)


ADMIN_ACTION_TOOLS = (
    sync_gradebook_tool,
    generate_transcripts_tool,
    finalise_transcripts_tool,
    link_person_tool,
    create_course_tool,
    create_batch_tool,
    assign_course_tutors_tool,
)

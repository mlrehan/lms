"""Grade book tools: reading a batch's grade book, entering exam marks.

Both go through the services the console uses, so the scope rules are theirs:
the grade book listing is narrowed by `enrollment_visibility` (a tutor sees
the batches they teach, a guardian their ward, a student themselves), and a
mark sheet is held to the exam's own eligibility rule.

**Marks are entered only after confirmation, and the preview lists every
mark.** Students are named in conversation, and two students can share a
name; a mark written against the wrong person is a grade somebody appeals.
So names are matched only against the candidates eligible for that exam, any
ambiguity refuses the whole sheet, and the person confirms the exact list --
which is then bound into the ticket by student id.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select

from backend.ai.security import RiskLevel, ToolPolicy
from backend.ai.tools.registry import BOUND_PREFIX, ConfirmationPreview, ToolDefinition, ToolExecutionContext
from backend.core.errors import NotFoundError, ValidationError
from backend.models.batch import Batch
from backend.models.exam import Exam
from backend.models.identity.user import User
from backend.utils.enums import Roles

_MAX_ROWS = 200
_MAX_MARKS = 500


def _name(person: User) -> str:
    return f"{person.first_name or ''} {person.last_name or ''}".strip() or "Unnamed account"


# =============================================================================
# 1. BATCH GRADE BOOK
# =============================================================================


async def handle_get_batch_gradebook(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    """The grade book entries for one batch, as the caller may see them."""
    from backend.schemas.base import PageParams
    from backend.services.gradebook_service import GradeBookService
    from backend.utils.enums import GradeComponentType

    batch_code = str(arguments.get("batch_code") or "").strip()
    if not batch_code:
        raise ValidationError("batch_code is required.")
    batch = (await context.session.execute(select(Batch).where(Batch.batch_code == batch_code))).scalar_one_or_none()
    if batch is None:
        raise NotFoundError(f"Batch '{batch_code}' not found.")

    component = None
    raw_component = str(arguments.get("component_type") or "").strip().upper()
    if raw_component:
        try:
            component = GradeComponentType(raw_component)
        except ValueError:
            raise ValidationError(f"Unknown grade component '{raw_component}'.") from None

    # `get` inside list_entries applies batch visibility (404 outside scope),
    # and the rows are narrowed by the caller's enrollment visibility.
    entries, total = await GradeBookService(context.session).list_entries(
        PageParams(limit=_MAX_ROWS, offset=0),
        actor=context.user,
        batch_public_id=batch.public_id,
        component_type=component,
    )
    rows = []
    for entry in entries:
        score, maximum = Decimal(str(entry.score)), Decimal(str(entry.max_score))
        rows.append({
            "student": _name(entry.student),
            "component": entry.component_type.value,
            "score": float(score),
            "max_score": float(maximum),
            # Computed here, deterministically, rather than left to the model.
            "percentage": float(round(score / maximum * 100, 2)) if maximum else None,
        })
    return {
        "success": True,
        "batch_code": batch.batch_code,
        "entries": rows,
        "total": total,
        "truncated": total > len(rows),
        "message": f"{total} grade book entr{'y' if total == 1 else 'ies'} for batch {batch.batch_code}.",
    }


get_batch_gradebook_tool = ToolDefinition(
    name="get_batch_gradebook",
    description="Read the grade book for a batch: each student's recorded marks by component, with percentages.",
    policy=ToolPolicy(
        name="get_batch_gradebook",
        description="Read a batch grade book",
        required_permissions=("grade.read",),
        risk_level=RiskLevel.LOW,
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "batch_code": {"type": "string", "description": "Batch code, e.g. '11405'"},
            "component_type": {
                "type": "string",
                "enum": ["ASSIGNMENT", "QUIZ", "ATTENDANCE", "PRACTICAL", "FINAL_EXAM"],
                "description": "Optionally restrict to one component",
            },
        },
        "required": ["batch_code"],
    },
    handler=handle_get_batch_gradebook,
)


# =============================================================================
# 2. RECORD EXAM MARKS
# =============================================================================


async def _resolve_mark_sheet(
    arguments: dict[str, Any], context: ToolExecutionContext
) -> tuple[Exam, list[tuple[User, Decimal, str | None]]]:
    """Resolve the exam and every named student against its eligible candidates."""
    from backend.services.exam_service import ExamService

    session = context.session
    ident = str(arguments.get("exam_id") or "").strip()
    if not ident:
        raise ValidationError("exam_id is required.")
    try:
        exam_row = (await session.execute(select(Exam).where(Exam.public_id == uuid.UUID(ident)))).scalar_one_or_none()
    except ValueError:
        rows = (
            await session.execute(select(Exam).where(func.lower(Exam.title) == ident.lower()).limit(2))
        ).scalars().all()
        if len(rows) > 1:
            raise ValidationError(f"More than one exam is titled '{ident}'. Give its id instead.") from None
        exam_row = rows[0] if rows else None
    if exam_row is None:
        raise NotFoundError(f"Exam '{ident}' not found.")

    service = ExamService(session)
    exam = await service.get(exam_row.public_id, actor=context.user)  # scope: 404 if not visible
    eligible_ids = await service._eligible_student_ids(exam)
    candidates = list(
        (await session.execute(select(User).where(User.id.in_(eligible_ids or {-1})))).scalars().unique()
    )

    marks = arguments.get("marks") or []
    if not marks:
        raise ValidationError("Give at least one student's mark.")
    if len(marks) > _MAX_MARKS:
        raise ValidationError(f"At most {_MAX_MARKS} marks can be entered at once.")

    total = Decimal(str(exam.total_marks)) if getattr(exam, "total_marks", None) is not None else None
    sheet: list[tuple[User, Decimal, str | None]] = []
    problems: list[str] = []
    seen: set[int] = set()
    for item in marks:
        who = str(item.get("student") or "").strip()
        try:
            mark = Decimal(str(item.get("marks_obtained")))
        except (InvalidOperation, TypeError):
            problems.append(f"'{who}': the mark is not a number")
            continue
        pid = None
        try:
            pid = uuid.UUID(who)
        except ValueError:
            pass
        matches = [c for c in candidates if (c.public_id == pid if pid else _name(c).lower() == who.lower())]
        if len(matches) != 1:
            problems.append(
                f"'{who}' is not a candidate for this exam" if not matches else f"'{who}' matches more than one candidate"
            )
            continue
        student = matches[0]
        if student.id in seen:
            problems.append(f"'{who}' appears twice")
            continue
        if mark < 0 or (total is not None and mark > total):
            problems.append(f"'{who}': {mark} is outside 0-{total}")
            continue
        seen.add(student.id)
        remarks = item.get("remarks")
        sheet.append((student, mark, str(remarks) if remarks else None))

    # The whole sheet or nothing: a sheet that silently drops a name is worse
    # than one that fails visibly, because nobody notices the gap.
    if problems:
        raise ValidationError("No marks were recorded: " + "; ".join(problems) + ".")
    return exam, sheet


async def preview_record_exam_marks(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    exam, sheet = await _resolve_mark_sheet(arguments, context)
    out_of = f" (out of {exam.total_marks})" if getattr(exam, "total_marks", None) is not None else ""
    listing = ", ".join(f"{_name(s)} {m}" for s, m, _ in sheet)
    return ConfirmationPreview(
        summary=f"Record marks for '{exam.title}'{out_of}: {listing}?",
        affected_records_count=len(sheet),
        bound_parameters={
            "exam_public_id": str(exam.public_id),
            "entries": [[str(s.public_id), str(m)] for s, m, _ in sheet],
        },
    )


async def handle_record_exam_marks(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    """Record the confirmed mark sheet through ExamService.record_results."""
    from backend.schemas.exam import ExamResultEntry
    from backend.services.exam_service import ExamService

    exam, sheet = await _resolve_mark_sheet(arguments, context)
    resolved = [[str(s.public_id), str(m)] for s, m, _ in sheet]
    if (
        str(exam.public_id) != str(arguments.get(f"{BOUND_PREFIX}exam_public_id"))
        or resolved != arguments.get(f"{BOUND_PREFIX}entries")
    ):
        raise ValidationError("The marks no longer match what was confirmed; ask again.")

    results = await ExamService(context.session).record_results(
        exam.public_id,
        [ExamResultEntry(student_id=s.public_id, marks_obtained=m, remarks=r) for s, m, r in sheet],
        actor=context.user,
    )
    return {
        "success": True,
        "exam_id": str(exam.public_id),
        "recorded": len(results),
        "message": (
            f"{len(sheet)} mark(s) recorded for '{exam.title}'. "
            "They are not visible to students until the results are published."
        ),
    }


record_exam_marks_tool = ToolDefinition(
    name="record_exam_marks",
    description=(
        "Enter or correct marks for an exam's candidates. Students are named exactly; "
        "the user confirms the full list before anything is recorded."
    ),
    policy=ToolPolicy(
        name="record_exam_marks",
        description="Record exam marks",
        required_permissions=("exam.grade",),
        allowed_roles=(Roles.TUTOR.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value),
        risk_level=RiskLevel.HIGH,
        requires_confirmation=True,
        audit_action="UPDATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "exam_id": {"type": "string", "description": "Exam UUID or exact title"},
            "marks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "student": {"type": "string", "description": "Student's full name or id"},
                        "marks_obtained": {"type": "number"},
                        "remarks": {"type": "string"},
                    },
                    "required": ["student", "marks_obtained"],
                },
            },
        },
        "required": ["exam_id", "marks"],
    },
    handler=handle_record_exam_marks,
    preview=preview_record_exam_marks,
)

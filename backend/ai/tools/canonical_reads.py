"""Canonical reads: the questions people actually ask, answered from one source each.

"How many enrolments does Maxim have, and who are his tutors?" had no tool. The
model wrote SQL, joined `tutor_courses` (course-level access, empty for every
batch the LAIT sync creates), and reported "no tutor currently assigned" for
batches whose every class had one. These tools answer from the same rules the
console uses, and label every figure with where it came from and how complete
it is, so an absence can never be read as a fact:

* the batch tutor comes from `services/batch_tutors.py` -- the Batches page's
  own rule -- with every source listed and a status;
* enrolments are filtered by `EnrollmentVisibility`, the enrolment screen's
  rule: a tutor sees the batches they teach and nothing else of a student's
  record, a guardian or manager sees their own people's whole record;
* every list carries a ``completeness`` block: how many matched, how many are
  returned, whether anything was left out.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select

from backend.ai.security import RiskLevel, SecurityPolicyEngine, ToolPolicy
from backend.ai.tools.registry import ToolDefinition, ToolExecutionContext
from backend.core.errors import NotFoundError, ValidationError

_MAX_ROWS = 50


def _name(user: Any) -> str:
    return f"{user.first_name or ''} {user.last_name or ''}".strip() or "Unnamed account"


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


async def _find_student(context: ToolExecutionContext, ident: Any) -> Any:
    """One student the caller may see, by full name -- or by email/username for a
    holder of `user.view_contact`, the only people who may confirm an address exists."""
    from backend.models.identity.user import User
    from backend.services.scope import ScopeResolver
    from backend.utils.enums import UserStatus

    text = " ".join(str(ident or "").split())
    if len(text) < 2:
        raise ValidationError("Name the student (their full name).")
    visible = await ScopeResolver(context.session).visible_student_ids(context.user)
    live = (User.deleted_at.is_(None), User.status != UserStatus.DELETED)
    full = func.lower(func.concat_ws(" ", User.first_name, User.last_name))
    match = [full == text.lower()]
    if "user.view_contact" in SecurityPolicyEngine.caller_permissions(context.user):
        match += [func.lower(User.email) == text.lower(), func.lower(User.username) == text.lower()]
    stmt = visible.apply(select(User).where(*live, or_(*match)), User.id)
    found = list((await context.session.execute(stmt.limit(6))).scalars().unique())
    if not found:
        partial = visible.apply(select(User).where(*live, full.like(f"%{text.lower()}%")), User.id)
        found = list((await context.session.execute(partial.limit(6))).scalars().unique())
    if not found:
        raise NotFoundError(f"No student called '{text}' among the people you can see.")
    if len(found) > 1:
        names = "; ".join(_name(u) for u in found[:5])
        raise ValidationError(f"'{text}' matches more than one person ({names}). Ask which one.")
    return found[0]


async def handle_get_student_enrollments(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.models.batch import Batch
    from backend.models.course import Course
    from backend.models.enrollment import Enrollments
    from backend.services.batch_tutors import tutors_for_batches
    from backend.services.scope import ScopeResolver

    student = await _find_student(context, arguments.get("student"))
    visibility = await ScopeResolver(context.session).enrollment_visibility(context.user)
    base = (
        select(Enrollments, Batch, Course)
        .join(Batch, Batch.id == Enrollments.batch_id)
        .join(Course, Course.id == Batch.course_id)
        .where(Enrollments.student_id == student.id)
    )
    status_filter = str(arguments.get("status") or "").strip().upper()
    if status_filter:
        from backend.utils.enums import EnrollmentStatus

        if status_filter not in EnrollmentStatus.__members__:
            raise ValidationError(f"Unknown status {status_filter}.")
        base = base.where(Enrollments.status == EnrollmentStatus[status_filter])
    scoped = visibility.apply(base, batch_column=Enrollments.batch_id, student_column=Enrollments.student_id)
    rows = (await context.session.execute(scoped.order_by(Enrollments.enrollment_date.desc()).limit(_MAX_ROWS + 1))).all()
    truncated = len(rows) > _MAX_ROWS
    rows = rows[:_MAX_ROWS]
    tutors = await tutors_for_batches(context.session, [b.id for _, b, _ in rows])

    items = []
    for enr, batch, course in rows:
        items.append({
            "batch_code": batch.batch_code,
            "course": course.title,
            "enrollment_status": enr.status.value,
            "enrolled_on": _iso(enr.enrollment_date),
            "batch_dates": {"start": _iso(batch.start_date), "end": _iso(batch.end_date)},
            "tutors": tutors[batch.id].as_dict(),
        })
    return {
        "success": True,
        "student": _name(student),
        "enrollments": items,
        "completeness": {
            "returned": len(items),
            "truncated": truncated,
            "scope": "every enrolment" if visibility.unrestricted else
                     "only the enrolments you may see (the batches you teach, or the people in your care)",
            "status_filter": status_filter or None,
        },
        "note": (
            "Each batch's tutor is 'batch_tutor' (who teaches most of its classes, as on the Batches page). "
            "'course_level_tutors' is course access, not who teaches the batch. Only status UNASSIGNED means no "
            "tutor; NOT_APPLICABLE means no classes are scheduled yet. Report every enrolment listed. When "
            "'scope' is limited, say the count is of the enrolments you can see (e.g. 'in the batches you teach'), "
            "never that it is the student's total."
        ),
    }


get_student_enrollments_tool = ToolDefinition(
    name="get_student_enrollments",
    description=(
        "A student's enrolments, found by their full name: for each one the batch, course, status, enrolment date "
        "and the batch's tutor (the same rule as the Batches page, with every tutor source labelled). Use for "
        "'how many enrolments does X have', 'which batches is X in', 'who teaches X'. Answers within what you may see."
    ),
    policy=ToolPolicy(
        name="get_student_enrollments", description="Read a student's enrolments and their tutors",
        required_permissions=("enrollment.read",), risk_level=RiskLevel.LOW,
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "student": {"type": "string", "description": "The student's full name"},
            "status": {"type": "string", "description": "Optional: CONFIRMED, PENDING, DROPPED, COMPLETED, CANCELLED"},
        },
        "required": ["student"],
    },
    handler=handle_get_student_enrollments,
)


async def handle_get_batch_overview(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.models.batch import Batch, BatchSession
    from backend.models.enrollment import Enrollments
    from backend.services.batch_service import BatchService
    from backend.services.batch_tutors import tutors_for_batches
    from backend.utils.enums import EnrollmentStatus

    code = " ".join(str(arguments.get("batch_code") or "").split())
    if not code:
        raise ValidationError("Name the batch by its code.")
    public_id = (await context.session.execute(
        select(Batch.public_id).where(func.lower(Batch.batch_code) == code.lower()))).scalar_one_or_none()
    if public_id is None:
        raise NotFoundError(f"Batch '{code}' not found.")
    batch = await BatchService(context.session).get(public_id, actor=context.user)  # scoped: 404 if not yours

    now = datetime.now(UTC)
    live = (BatchSession.batch_id == batch.id, BatchSession.cancelled_at.is_(None))
    held, upcoming = (await context.session.execute(
        select(func.count().filter(BatchSession.session_start_time < now), func.min(BatchSession.session_start_time)
               .filter(BatchSession.session_start_time >= now)).where(*live))).one()
    # Counted from enrolments, never the cached `total_enrollments` counter, which lags.
    by_status = dict((await context.session.execute(
        select(Enrollments.status, func.count()).where(Enrollments.batch_id == batch.id).group_by(Enrollments.status))).all())
    active = sum(n for s, n in by_status.items() if s in (EnrollmentStatus.CONFIRMED, EnrollmentStatus.PENDING))
    tutors = (await tutors_for_batches(context.session, [batch.id]))[batch.id]
    return {
        "success": True,
        "batch_code": batch.batch_code,
        "course": batch.course.title if batch.course else None,
        "is_active": batch.is_active,
        "dates": {"start": _iso(batch.start_date), "end": _iso(batch.end_date)},
        "capacity": batch.capacity,
        "enrolled_active": active,
        "enrollments_by_status": {s.value: n for s, n in by_status.items()},
        "classes": {"total": tutors.classes_total, "held": int(held or 0), "next": _iso(upcoming)},
        "tutors": tutors.as_dict(),
    }


get_batch_overview_tool = ToolDefinition(
    name="get_batch_overview",
    description=(
        "One batch by its code: course, dates, capacity, enrolments counted live by status, classes held and next, "
        "and its tutor (the Batches page's rule, every source labelled). Use for 'who teaches batch X', "
        "'how many are in batch X'."
    ),
    policy=ToolPolicy(
        name="get_batch_overview", description="Read a batch's overview",
        required_permissions=("batch.read",), risk_level=RiskLevel.LOW,
    ),
    parameters_schema={"type": "object", "properties": {"batch_code": {"type": "string"}}, "required": ["batch_code"]},
    handler=handle_get_batch_overview,
)


async def handle_get_my_tasks(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    """What is waiting for this person -- each list from the screen that owns it.

    Registers from the Attendance queue (classes assigned to them that have
    started and are not finalised), marking from the scoped submissions list,
    results marked but not released, and their next classes. Each section
    gives a total alongside the few items shown, so "3 shown of 12" is said.
    """
    from datetime import timedelta

    from backend.models.batch import Batch, BatchSession
    from backend.schemas.base import PageParams
    from backend.services.assignment_service import AssignmentService
    from backend.services.attendance_sheet_service import AttendanceSheetService
    from backend.services.scope import ScopeResolver
    from backend.utils.enums import SubmissionState

    show = 5
    page = PageParams(limit=show, offset=0)
    unrestricted = ScopeResolver.is_unrestricted(context.user)

    registers, registers_total = await AttendanceSheetService(context.session).queue(
        context.user, page, batch_public_id=None, tutor_public_id=context.user.public_id, state="PENDING",
        starts_from=None, starts_to=None,
    )
    assignments = AssignmentService(context.session)
    to_mark, to_mark_total = await assignments.list_submissions(page, actor=context.user, graded=False)
    unreleased, unreleased_total = await assignments.list_submissions(page, actor=context.user, state=SubmissionState.GRADED)

    now = datetime.now(UTC)
    upcoming_q = (
        select(BatchSession, Batch).join(Batch, Batch.id == BatchSession.batch_id)
        .where(BatchSession.tutor_id == context.user.id, BatchSession.cancelled_at.is_(None),
               BatchSession.session_start_time >= now, BatchSession.session_start_time < now + timedelta(days=7))
        .order_by(BatchSession.session_start_time)
    )
    upcoming = (await context.session.execute(upcoming_q.limit(show))).all()

    def subs(rows: Any) -> list[dict[str, Any]]:
        return [{"submission_id": str(s.public_id), "assignment": s.assignment.title, "student": _name(s.student),
                 "submitted_at": _iso(s.submitted_at), "grade": float(s.grade) if s.grade is not None else None}
                for s in rows]

    return {
        "success": True,
        "scope": "the whole institution" if unrestricted else "your own classes and the courses you teach",
        "registers_to_take": {
            "total": registers_total,
            "items": [{"session_id": str(r.session_id), "batch_code": r.batch_code, "course": r.course_title,
                       "starts": _iso(r.start_time), "state": r.state.value} for r in registers],
        },
        "submissions_to_mark": {"total": to_mark_total, "items": subs(to_mark)},
        "marked_not_released": {"total": unreleased_total, "items": subs(unreleased)},
        "next_classes_7_days": [{"session_id": str(bs.public_id), "batch_code": b.batch_code,
                                 "starts": _iso(bs.session_start_time)} for bs, b in upcoming],
        "note": f"Each section shows at most {show} items; 'total' is the full count. Say '{show} of N' when N is larger.",
    }


get_my_tasks_tool = ToolDefinition(
    name="get_my_tasks",
    description=(
        "What is waiting for me: registers to take for classes that have started, submissions to mark, marks "
        "recorded but not released, and my classes in the next 7 days -- each with a full total. Use for 'what do I "
        "need to do?', 'anything pending?', 'what's on my plate?'."
    ),
    policy=ToolPolicy(
        name="get_my_tasks", description="Read your pending teaching work",
        required_permissions=("assignment.grade",),
        allowed_roles=("TUTOR", "ADMIN", "SUPER_ADMIN"), risk_level=RiskLevel.LOW,
    ),
    parameters_schema={"type": "object", "properties": {}},
    handler=handle_get_my_tasks,
)


CANONICAL_READ_TOOLS = (get_student_enrollments_tool, get_batch_overview_tool, get_my_tasks_tool)

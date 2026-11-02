"""The assistant's half of the new rules: own assessments, the video library, grading schemes.

Every tool calls the service the console's own route calls, as the person
asking, so the assistant can never do more than that person could by clicking:

* **Assessments.** A tutor sees, publishes, unpublishes and withdraws only the
  assessments they created; a Super Admin any. That rule lives in the
  services (`services/assessment_access.py`), not here.
* **Videos.** Anybody may find the videos shared with them. Adding one is
  private until it is shared. Sharing is confirmed, and the recipients are the
  server's own share audience: a tutor reaches colleagues, the students they
  teach and those students' guardians, and batches they teach; a Super Admin
  anybody. One recipient outside that refuses the whole request.
* **Grading schemes.** Assigning one to a course or batch re-grades everyone
  it covers, so it is Super Admin only and confirmed.

The provider's address of a video is never returned: viewers are pointed at
the video's page in the LMS, where the player re-checks access every time.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select

from backend.ai.security import RiskLevel, SecurityPolicyEngine, ToolPolicy
from backend.ai.tools.registry import BOUND_PREFIX, ConfirmationPreview, ToolDefinition, ToolExecutionContext
from backend.core.errors import AuthorizationError, NotFoundError, ValidationError
from backend.schemas.base import PageParams
from backend.utils.enums import Roles

_STAFF = (Roles.TUTOR.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value)


def _bound(arguments: dict[str, Any], key: str) -> Any:
    return arguments.get(f"{BOUND_PREFIX}{key}")


def _has(context: ToolExecutionContext, permission: str) -> bool:
    return permission in SecurityPolicyEngine.caller_permissions(context.user)


# =============================================================================
# 1. MY ASSESSMENTS
# =============================================================================


async def handle_list_my_assessments(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    """The assignments, quizzes and exams the caller can see, with who may manage each."""
    from backend.schemas.assessment_common import ownership_fields
    from backend.services.assignment_service import AssignmentService
    from backend.services.exam_service import ExamService
    from backend.services.quiz_service import QuizService
    from backend.utils.enums import AssessmentState

    user, session = context.user, context.session
    mine_only = bool(arguments.get("mine_only", True))
    status = str(arguments.get("status") or "ALL").upper()
    params = PageParams(limit=100, offset=0)
    rows: list[dict[str, Any]] = []

    def keep(published: bool, row: Any) -> bool:
        if mine_only and row.created_by != user.id:
            return False
        return status == "ALL" or (status == "PUBLISHED") == published

    if _has(context, "assignment.read"):
        items, _ = await AssignmentService(session).list_assignments(params, actor=user)
        for a in items:
            published = a.state is AssessmentState.PUBLISHED
            if keep(published, a):
                rows.append({"type": "assignment", "id": str(a.public_id), "title": a.title,
                             "course": a.course.title if a.course else None,
                             "published": published, **ownership_fields(a, user)})
    if _has(context, "quiz.read"):
        items, _ = await QuizService(session).list_quizzes(params, actor=user)
        for q in items:
            if keep(bool(q.is_published), q):
                rows.append({"type": "quiz", "id": str(q.public_id), "title": q.title,
                             "course": q.course.title if q.course else None,
                             "published": bool(q.is_published), **ownership_fields(q, user)})
    if _has(context, "exam.read"):
        items, _ = await ExamService(session).list_exams(params, actor=user)
        for e in items:
            if keep(bool(e.is_published), e):
                rows.append({"type": "examination", "id": str(e.public_id), "title": e.title,
                             "course": e.course.title if e.course else None,
                             "published": bool(e.is_published), **ownership_fields(e, user)})

    return {
        "count": len(rows),
        "assessments": rows,
        "scope": "created by you" if mine_only else "everything you can see",
        "note": (
            "can_manage=true means the caller may edit, publish, unpublish and delete it. Tutors never "
            "see another tutor's assessments. Up to 100 of each type are listed."
        ),
    }


list_my_assessments_tool = ToolDefinition(
    name="list_my_assessments",
    description=(
        "List the caller's assessments (assignments, quizzes, examinations) with whether each is published and "
        "whether the caller may manage it. Use for 'which of my quizzes are drafts?', 'what have I published?'. "
        "mine_only (default true) limits to ones the caller created; status ALL/PUBLISHED/DRAFT."
    ),
    policy=ToolPolicy(
        name="list_my_assessments", description="List your assessments",
        required_permissions=("assignment.read",), allowed_roles=_STAFF,
        risk_level=RiskLevel.LOW,
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "mine_only": {"type": "boolean", "default": True},
            "status": {"type": "string", "enum": ["ALL", "PUBLISHED", "DRAFT"], "default": "ALL"},
        },
    },
    handler=handle_list_my_assessments,
)


# =============================================================================
# 2. DELETE (WITHDRAW) AN ASSESSMENT
# =============================================================================


async def _load_assessment(arguments: dict[str, Any], context: ToolExecutionContext) -> tuple[str, Any, Any]:
    from backend.ai.tools.academic_tools import _resolve_for_publish
    from backend.models.assignment import Assignment
    from backend.models.exam import Exam
    from backend.models.quiz import Quiz
    from backend.services.assessment_access import AssessmentAccess
    from backend.services.assignment_service import AssignmentService
    from backend.services.exam_service import ExamService
    from backend.services.quiz_service import QuizService

    raw = str(arguments.get("assessment_type") or "").lower().strip()
    kind = {"exam": "examination"}.get(raw, raw)
    models = {"assignment": (Assignment, AssignmentService, "assignment.delete"),
              "quiz": (Quiz, QuizService, "quiz.delete"),
              "examination": (Exam, ExamService, "exam.delete")}
    if kind not in models:
        raise ValidationError("assessment_type must be assignment, quiz or examination.")
    model, service_cls, permission = models[kind]
    if not _has(context, permission):
        raise AuthorizationError(f"You do not have permission to delete a {kind}.")
    ident = arguments.get("assessment_id")
    if not ident:
        raise ValidationError("assessment_id (id or exact title) is required.")
    row = await _resolve_for_publish(context.session, model, str(ident))
    if row is None:
        raise NotFoundError(f"{kind.capitalize()} '{ident}' not found.")
    service = service_cls(context.session)
    row = await service.get(row.public_id, actor=context.user)  # isolation: a colleague's is a 404
    if not AssessmentAccess.may_manage(row, context.user):
        raise AuthorizationError(f"Only the tutor who created this {kind} (or a Super Admin) can delete it.")
    return kind, row, service


async def preview_delete_assessment(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    kind, row, _ = await _load_assessment(arguments, context)
    return ConfirmationPreview(
        summary=(
            f"Delete the {kind} '{row.title}'? It disappears from every list and its links stop working for "
            "students and staff. Submissions, marks, grade-book entries and finalised transcripts are kept, "
            "and the deletion is recorded in the audit log."
        ),
        bound_parameters={"assessment_public_id": str(row.public_id)},
    )


async def handle_delete_assessment(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    kind, row, service = await _load_assessment(arguments, context)
    if str(row.public_id) != str(_bound(arguments, "assessment_public_id")):
        raise ValidationError("The assessment no longer matches the one confirmed; ask again.")
    title = row.title
    await service.delete(row.public_id, actor=context.user)
    return {"success": True, "assessment_type": kind, "title": title,
            "message": f"The {kind} '{title}' was deleted. Students' work and marks are kept."}


delete_assessment_tool = ToolDefinition(
    name="delete_assessment",
    description=(
        "Delete (withdraw) an assignment, quiz or examination. A tutor may delete only ones they created; a "
        "Super Admin any. Students' submissions and marks are kept. Requires confirmation."
    ),
    policy=ToolPolicy(
        name="delete_assessment", description="Delete an assessment",
        required_permissions=("course.read",), allowed_roles=_STAFF,
        risk_level=RiskLevel.HIGH, requires_confirmation=True, audit_action="DELETE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "assessment_type": {"type": "string", "enum": ["assignment", "quiz", "examination"]},
            "assessment_id": {"type": "string", "description": "UUID or exact title"},
        },
        "required": ["assessment_type", "assessment_id"],
    },
    handler=handle_delete_assessment,
    preview=preview_delete_assessment,
)


# =============================================================================
# 3. VIDEO LIBRARY
# =============================================================================


def _video_line(v: Any) -> dict[str, Any]:
    from backend.core.video_links import provider_label

    return {"id": str(v.public_id), "title": v.title, "provider": provider_label(v.provider),
            "description": (v.description or "")[:300] or None,
            # The LMS page, never the provider's address: the player there
            # re-checks access every time it is opened.
            "page": f"/videos/{v.public_id}"}


async def handle_find_videos(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.services.video_service import VideoService

    sharing = str(arguments.get("sharing") or "all")
    rows, total = await VideoService(context.session).list(
        PageParams(limit=25, offset=0), actor=context.user,
        query=arguments.get("query") or None, provider=arguments.get("provider") or None,
        sharing=sharing if sharing in ("all", "mine", "shared_with_me") else "all",
        sort="newest",
    )
    return {"count": len(rows), "total": total, "videos": [_video_line(v) for v in rows],
            "note": "Only videos the caller may watch are listed. Point the person to each video's page to watch it."}


find_videos_tool = ToolDefinition(
    name="find_videos",
    description=(
        "Find videos in the video library that the caller may watch (their own, shared with them, or shared "
        "with a batch they are in). Optional query (title/description), provider (youtube, vimeo, zoom...), "
        "sharing all/mine/shared_with_me. Returns each video's page in the LMS."
    ),
    policy=ToolPolicy(name="find_videos", description="Find videos", required_permissions=("video.read",),
                      risk_level=RiskLevel.LOW),
    parameters_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"}, "provider": {"type": "string"},
            "sharing": {"type": "string", "enum": ["all", "mine", "shared_with_me"]},
        },
    },
    handler=handle_find_videos,
)


async def _batch_public_id(context: ToolExecutionContext, code: Any) -> uuid.UUID | None:
    from backend.models.batch import Batch

    text = str(code or "").strip()
    if not text:
        return None
    found = (await context.session.execute(
        select(Batch.public_id).where(func.lower(Batch.batch_code) == text.lower()))).scalar_one_or_none()
    if found is None:
        raise NotFoundError(f"Batch '{text}' not found.")
    return found


async def handle_add_video(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.core.video_links import provider_profile
    from backend.services.video_service import VideoService

    title, url = str(arguments.get("title") or "").strip(), str(arguments.get("url") or "").strip()
    if len(title) < 2 or not url:
        raise ValidationError("A title and the video's link are required.")
    video = await VideoService(context.session).create(
        actor=context.user, title=title, url=url, description=arguments.get("description") or None,
        batch_id=await _batch_public_id(context, arguments.get("batch_code")),
    )
    profile = provider_profile(video.provider)
    return {
        "success": True, **_video_line(video),
        "plays_in_lms": profile.plays_in_lms, "download_note": profile.download,
        "message": f"Added '{video.title}' to the video library. Nobody else can see it until it is shared.",
    }


add_video_tool = ToolDefinition(
    name="add_video",
    description=(
        "Add a video link (YouTube, Vimeo, Wistia, Brightcove, Dacast, Zoom, Google Drive/Meet, Microsoft "
        "Teams/Stream, StreamYard, Zoho) to the video library. Private to the caller until shared with "
        "share_video. Optional batch_code (a batch the caller teaches)."
    ),
    policy=ToolPolicy(name="add_video", description="Add a video", required_permissions=("video.create",),
                      allowed_roles=_STAFF, risk_level=RiskLevel.MODERATE, audit_action="CREATE"),
    parameters_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"}, "url": {"type": "string"},
            "description": {"type": "string"}, "batch_code": {"type": "string"},
        },
        "required": ["title", "url"],
    },
    handler=handle_add_video,
)


async def _resolve_video(context: ToolExecutionContext, ident: Any) -> Any:
    from backend.services.video_service import VideoService

    service = VideoService(context.session)
    text = str(ident or "").strip()
    if not text:
        raise ValidationError("Name the video (its title or id).")
    try:
        return await service.get(uuid.UUID(text), actor=context.user)
    except ValueError:
        pass
    rows, _ = await service.list(PageParams(limit=10, offset=0), actor=context.user, query=text)
    exact = [r for r in rows if r.title.strip().lower() == text.lower()]
    candidates = exact or rows
    if not candidates:
        raise NotFoundError(f"No video titled '{text}' that you can see.")
    if len(candidates) > 1:
        raise ValidationError(
            "More than one video matches: " + "; ".join(r.title for r in candidates[:5]) + ". Which one?"
        )
    return candidates[0]


async def _resolve_people(context: ToolExecutionContext, names: list[str]) -> list[Any]:
    """Each name must match exactly one person in the caller's share audience."""
    from backend.services.resource_audience import ResourceShareAudience

    audience = ResourceShareAudience(context.session)
    people = []
    for name in names:
        text = " ".join(str(name).split())
        if not text:
            continue
        found = await audience.search(context.user, query=text, limit=10)
        exact = [c for c in found if c.name.lower() == text.lower()]
        pick = exact or found
        if len(pick) != 1:
            raise ValidationError(
                f"'{text}' does not match exactly one person you may share with"
                + (f" (did you mean: {', '.join(c.name for c in pick[:5])}?)" if pick else ".")
            )
        people.append(pick[0])
    return people


async def preview_share_video(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    video = await _resolve_video(context, arguments.get("video"))
    from backend.services.video_service import VideoService

    if not VideoService.may_manage(video, context.user):
        raise AuthorizationError("Only the person who added this video (or a Super Admin) can share it.")
    people = await _resolve_people(context, list(arguments.get("people") or []))
    batch = await _batch_public_id(context, arguments.get("batch_code"))
    if not people and batch is None:
        raise ValidationError("Name at least one person or a batch to share with.")
    who = [f"{p.name} ({p.role})" for p in people]
    if batch is not None:
        who.append(f"everyone in batch {arguments.get('batch_code')}")
    return ConfirmationPreview(
        summary=f"Share the video '{video.title}' with {', '.join(who)}? They can watch it in the LMS.",
        bound_parameters={"video_public_id": str(video.public_id),
                          "user_ids": [str(p.public_id) for p in people],
                          "batch_id": str(batch) if batch else None},
    )


async def handle_share_video(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.services.video_service import VideoService

    video_id = _bound(arguments, "video_public_id")
    if not video_id:
        raise ValidationError("Nothing was confirmed; ask again.")
    batch = _bound(arguments, "batch_id")
    people, batches = await VideoService(context.session).share(
        uuid.UUID(video_id), actor=context.user,
        user_ids=[uuid.UUID(u) for u in (_bound(arguments, "user_ids") or [])],
        batch_ids=[uuid.UUID(batch)] if batch else [],
    )
    return {"success": True, "people_added": people, "batches_added": batches,
            "message": f"Shared with {people} people and {batches} batch(es)."}


share_video_tool = ToolDefinition(
    name="share_video",
    description=(
        "Share a video-library video with people (by full name) and/or a batch (by code). A tutor may share "
        "only with colleagues, the students they teach and those students' guardians, and batches they teach; "
        "a Super Admin with anyone. Only the video's owner or a Super Admin may share it. Confirmed first."
    ),
    policy=ToolPolicy(name="share_video", description="Share a video", required_permissions=("video.publish",),
                      allowed_roles=_STAFF, risk_level=RiskLevel.HIGH, requires_confirmation=True,
                      audit_action="PERMISSION_CHANGE"),
    parameters_schema={
        "type": "object",
        "properties": {
            "video": {"type": "string", "description": "Title or id"},
            "people": {"type": "array", "items": {"type": "string"}, "description": "Full names"},
            "batch_code": {"type": "string"},
        },
        "required": ["video"],
    },
    handler=handle_share_video,
    preview=preview_share_video,
)


# =============================================================================
# 4. GRADING SCHEME ASSIGNMENT (SUPER ADMIN)
# =============================================================================


async def _scheme_target(arguments: dict[str, Any], context: ToolExecutionContext) -> tuple[str, Any, Any]:
    """(kind, record, scheme or None) -- None meaning 'stop overriding'."""
    from backend.models.batch import Batch
    from backend.models.course import Course
    from backend.models.grading import GradingScheme

    if context.user is None or not any(r.name == Roles.SUPER_ADMIN.value for r in context.user.roles or []):
        raise AuthorizationError("Only a Super Admin can assign grading schemes.")
    if not _has(context, "grading_scheme.manage"):
        raise AuthorizationError("You do not have permission to assign grading schemes.")
    session = context.session
    batch_code, course = str(arguments.get("batch_code") or "").strip(), str(arguments.get("course") or "").strip()
    if bool(batch_code) == bool(course):
        raise ValidationError("Name either a batch (batch_code) or a course (title or code), not both.")
    if batch_code:
        record = (await session.execute(
            select(Batch).where(func.lower(Batch.batch_code) == batch_code.lower()))).scalar_one_or_none()
        kind = "batch"
    else:
        record = (await session.execute(select(Course).where(
            Course.deleted_at.is_(None),
            (func.lower(Course.code) == course.lower()) | (func.lower(Course.title) == course.lower()),
        ))).scalars().first()
        kind = "course"
    if record is None:
        raise NotFoundError(f"That {kind} was not found.")
    name = str(arguments.get("scheme") or "").strip()
    if name.lower() in ("", "inherit", "default", "none"):
        return kind, record, None
    scheme = (await session.execute(
        select(GradingScheme).where(func.lower(GradingScheme.name) == name.lower()))).scalar_one_or_none()
    if scheme is None:
        raise NotFoundError(f"No grading scheme named '{name}'.")
    if not scheme.is_active:
        raise ValidationError(f"'{scheme.name}' is not activated; activate it before assigning it.")
    return kind, record, scheme


async def preview_assign_grading_scheme(arguments: dict[str, Any], context: ToolExecutionContext) -> ConfirmationPreview:
    kind, record, scheme = await _scheme_target(arguments, context)
    label = record.batch_code if kind == "batch" else record.title
    fallback = "its course's scheme" if kind == "batch" else "the institution default"
    what = f"'{scheme.name}'" if scheme else fallback
    return ConfirmationPreview(
        summary=(f"Grade {kind} {label} under {what}? Results of every student it covers are recalculated "
                 "immediately; finalised transcripts keep the scheme they were issued under."),
        bound_parameters={"kind": kind, "record_public_id": str(record.public_id),
                          "scheme_public_id": str(scheme.public_id) if scheme else None},
    )


async def handle_assign_grading_scheme(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from backend.services.grading_scheme_service import GradingSchemeService

    kind, record, scheme = await _scheme_target(arguments, context)
    if str(record.public_id) != str(_bound(arguments, "record_public_id")) or (
        (str(scheme.public_id) if scheme else None) != _bound(arguments, "scheme_public_id")
    ):
        raise ValidationError("This no longer matches what was confirmed; ask again.")
    service = GradingSchemeService(context.session)
    scheme_id = scheme.public_id if scheme else None
    if kind == "batch":
        await service.assign_to_batch(record.public_id, scheme_id, actor=context.user)
        effective, source = await service.resolve(course_id=record.course_id, batch_id=record.id)
    else:
        await service.assign_to_course(record.public_id, scheme_id, actor=context.user)
        effective, source = await service.resolve(course_id=record.id)
    return {"success": True, "effective_scheme": effective.name if effective else None, "source": source.value,
            "message": f"The {kind} is now graded under {effective.name if effective else 'no scheme'} ({source.value.lower()})."}


assign_grading_scheme_tool = ToolDefinition(
    name="assign_grading_scheme",
    description=(
        "Super Admin: set which grading scheme a course or a batch is graded under. A batch's scheme overrides "
        "its course's, which overrides the institution default. scheme='inherit' removes the override. "
        "Only activated schemes can be assigned. Confirmed first."
    ),
    policy=ToolPolicy(name="assign_grading_scheme", description="Assign a grading scheme",
                      required_permissions=("grading_scheme.manage",), allowed_roles=(Roles.SUPER_ADMIN.value,),
                      risk_level=RiskLevel.HIGH, requires_confirmation=True, audit_action="UPDATE"),
    parameters_schema={
        "type": "object",
        "properties": {
            "course": {"type": "string", "description": "Course code or exact title"},
            "batch_code": {"type": "string"},
            "scheme": {"type": "string", "description": "Scheme name, or 'inherit'"},
        },
        "required": ["scheme"],
    },
    handler=handle_assign_grading_scheme,
    preview=preview_assign_grading_scheme,
)


LIBRARY_TOOLS = (
    list_my_assessments_tool,
    delete_assessment_tool,
    find_videos_tool,
    add_video_tool,
    share_video_tool,
    assign_grading_scheme_tool,
)

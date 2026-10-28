"""Communication tools: drafting a message, posting an announcement.

**A message is drafted, never sent.** An outgoing message carries the sender's
name to another person's inbox and, by email, beyond the platform. The tool
puts a draft in the person's own Drafts folder and stops; sending is done by
the person, on the Messages screen, after reading it. A model that could send
mail could be talked into sending it by text it read somewhere else.

**An announcement is posted only after confirmation**, because it is visible
to a whole course or batch the moment it exists. Who may target what is
decided by AnnouncementService, exactly as for the console's own form.

Recipients are found only among people the caller may already write to
(`MailService.directory`, which searches names only), so the tool cannot be
used to discover who exists elsewhere.
"""

from __future__ import annotations

import html
import uuid
from typing import Any

from sqlalchemy import func, select

from backend.ai.security import RiskLevel, ToolPolicy
from backend.ai.tools.registry import BOUND_PREFIX, ConfirmationPreview, ToolDefinition, ToolExecutionContext
from backend.core.errors import NotFoundError, ValidationError
from backend.models.batch import Batch
from backend.models.course import Course
from backend.services.scope import ScopeResolver
from backend.utils.enums import Roles

_MAX_RECIPIENTS = 50


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value).strip())
    except (ValueError, TypeError):
        return None


def _text_to_html(text: str) -> str:
    """Plain text from the model, escaped, with paragraphs and line breaks kept.

    Escaped before anything else: the stored body is HTML rendered to the
    recipient, and model output is not trusted to be markup.
    """
    paragraphs = [p.strip() for p in str(text).replace("\r\n", "\n").split("\n\n") if p.strip()]
    return "".join(f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in paragraphs)


# =============================================================================
# 1. DRAFT MESSAGE
# =============================================================================


async def handle_draft_message(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    """Save a message as a draft for the caller to review and send."""
    from backend.schemas.mail import ComposeRequest
    from backend.services.mail_service import MailService

    recipients = arguments.get("recipients") or []
    if isinstance(recipients, str):
        recipients = [recipients]
    if not recipients:
        raise ValidationError("Name at least one recipient.")
    if len(recipients) > _MAX_RECIPIENTS:
        raise ValidationError(f"A drafted message can go to at most {_MAX_RECIPIENTS} people.")
    subject = str(arguments.get("subject") or "").strip()
    body = str(arguments.get("body") or "").strip()
    if not (subject or body):
        raise ValidationError("Give the message a subject or a body.")

    mail = MailService(context.session)
    resolved: dict[uuid.UUID, str] = {}
    unresolved: list[dict[str, Any]] = []
    for raw in recipients:
        term = str(raw).strip()
        if not term:
            continue
        pid = _as_uuid(term)
        candidates = await mail.directory(context.user, query=None if pid else term, limit=200 if pid else 6)
        if pid is not None:
            matches = [p for p in candidates if p.public_id == pid]
        else:
            exact = [p for p in candidates if p.name.strip().lower() == term.lower()]
            matches = exact or candidates
        if len(matches) == 1:
            resolved[matches[0].public_id] = matches[0].name
        else:
            unresolved.append({
                "requested": term,
                # Only people the caller may already write to; names and role
                # labels, never an address.
                "candidates": [{"name": p.name, "role": p.role, "id": str(p.public_id)} for p in matches[:5]],
            })

    if unresolved:
        return {
            "success": False,
            "status": "NEEDS_CLARIFICATION",
            "unresolved": unresolved,
            "message": (
                "No draft was saved. Some recipients matched nobody you can write to, or more than one person; "
                "ask the user which person they mean."
            ),
        }

    message = await mail.save(
        context.user,
        ComposeRequest(to=list(resolved), subject=subject, body_html=_text_to_html(body), email_copy=False),
        send=False,
    )
    return {
        "success": True,
        "status": "DRAFT_SAVED",
        "draft_id": str(message.public_id),
        "recipients": sorted(resolved.values()),
        "subject": subject,
        "message": "Saved to your Drafts. Nothing has been sent -- review it in Messages and send it from there.",
    }


draft_message_tool = ToolDefinition(
    name="draft_message",
    description=(
        "Draft a message to people the user may write to (their students, tutors, colleagues). "
        "Saves it in the user's Drafts; it is NOT sent -- the user sends it themselves from Messages."
    ),
    policy=ToolPolicy(
        name="draft_message",
        description="Draft a message",
        required_permissions=("message.create",),
        risk_level=RiskLevel.MODERATE,
        audit_action="CREATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "recipients": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Recipients' full names (or ids returned by an earlier clarification).",
            },
            "subject": {"type": "string", "description": "Message subject"},
            "body": {"type": "string", "description": "Message body as plain text; blank lines separate paragraphs."},
        },
        "required": ["recipients", "subject", "body"],
    },
    handler=handle_draft_message,
)


# =============================================================================
# 2. POST ANNOUNCEMENT
# =============================================================================


async def _resolve_announcement(
    arguments: dict[str, Any], context: ToolExecutionContext
) -> tuple[str, str, uuid.UUID | None, uuid.UUID | None, Roles | None, bool, str]:
    """Validate the announcement and its audience before anything is staged."""
    from backend.services.announcement_service import AnnouncementService

    title = str(arguments.get("title") or "").strip()
    content = str(arguments.get("content") or "").strip()
    if not title or not content:
        raise ValidationError("An announcement needs a title and content.")

    session = context.session
    course_pid: uuid.UUID | None = None
    batch_pid: uuid.UUID | None = None
    audience = []

    course_ident = str(arguments.get("course_code") or "").strip()
    if course_ident:
        course = (
            await session.execute(
                select(Course).where(func.lower(Course.code) == course_ident.lower(), Course.is_deleted.is_(False))
            )
        ).scalar_one_or_none()
        if course is None:
            raise NotFoundError(f"Course '{course_ident}' not found.")
        course_pid = course.public_id
        audience.append(f"course {course.code}")

    batch_ident = str(arguments.get("batch_code") or "").strip()
    if batch_ident:
        batch = (await session.execute(select(Batch).where(Batch.batch_code == batch_ident))).scalar_one_or_none()
        if batch is None:
            raise NotFoundError(f"Batch '{batch_ident}' not found.")
        batch_pid = batch.public_id
        audience.append(f"batch {batch.batch_code}")

    role_scope = None
    raw_role = str(arguments.get("role_scope") or "").strip().upper()
    if raw_role:
        try:
            role_scope = Roles(raw_role)
        except ValueError:
            raise ValidationError(f"Unknown role '{raw_role}'.") from None
        audience.append(f"{role_scope.value.replace('_', ' ').lower()}s only")

    # The same targeting rule the console's form is held to, checked now so a
    # person is never asked to confirm something they are not allowed to do.
    service = AnnouncementService(session)
    course_pk = await service._resolve_course(course_pid) if course_pid else None
    batch_pk = await service._resolve_batch(batch_pid) if batch_pid else None
    if course_pk is not None and batch_pk is not None:
        await service._assert_batch_in_course(batch_pk, course_pk)
    if not ScopeResolver.is_unrestricted(context.user):
        await service._assert_may_target(context.user, course_pk=course_pk, batch_pk=batch_pk)

    pinned = bool(arguments.get("pinned", False))
    return title, content, course_pid, batch_pid, role_scope, pinned, ", ".join(audience) or "everyone"


async def preview_post_announcement(
    arguments: dict[str, Any], context: ToolExecutionContext
) -> ConfirmationPreview:
    title, _, course_pid, batch_pid, role_scope, pinned, audience = await _resolve_announcement(arguments, context)
    return ConfirmationPreview(
        summary=f"Post the announcement '{title}' to {audience}{' (pinned)' if pinned else ''}?",
        bound_parameters={
            "course_public_id": str(course_pid) if course_pid else None,
            "batch_public_id": str(batch_pid) if batch_pid else None,
        },
    )


async def handle_post_announcement(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    """Post the confirmed announcement through AnnouncementService."""
    from backend.schemas.announcement import CreateAnnouncementRequest
    from backend.services.announcement_service import AnnouncementService

    title, content, course_pid, batch_pid, role_scope, pinned, audience = await _resolve_announcement(arguments, context)
    bound = (
        arguments.get(f"{BOUND_PREFIX}course_public_id"),
        arguments.get(f"{BOUND_PREFIX}batch_public_id"),
    )
    if bound != (str(course_pid) if course_pid else None, str(batch_pid) if batch_pid else None):
        raise ValidationError("The audience no longer matches what was confirmed; ask again.")

    announcement = await AnnouncementService(context.session).create(
        CreateAnnouncementRequest(
            title=title,
            content=content,
            course_id=course_pid,
            batch_id=batch_pid,
            role_scope=role_scope,
            pinned=pinned,
        ),
        actor=context.user,
    )
    return {
        "success": True,
        "announcement_id": str(announcement.public_id),
        "title": announcement.title,
        "audience": audience,
        "message": f"The announcement '{announcement.title}' is posted to {audience}.",
    }


post_announcement_tool = ToolDefinition(
    name="post_announcement",
    description=(
        "Post an announcement to a course, a batch, or (administrators only) everyone. "
        "Requires the user's confirmation."
    ),
    policy=ToolPolicy(
        name="post_announcement",
        description="Post an announcement",
        required_permissions=("announcement.create",),
        allowed_roles=(Roles.TUTOR.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value),
        risk_level=RiskLevel.HIGH,
        requires_confirmation=True,
        audit_action="CREATE",
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string", "description": "Announcement text"},
            "course_code": {"type": "string", "description": "Course code to target, e.g. 'PY-ADV'"},
            "batch_code": {"type": "string", "description": "Batch code to target, e.g. '11405'"},
            "role_scope": {
                "type": "string",
                "enum": [r.value for r in Roles],
                "description": "Optionally narrow to one role",
            },
            "pinned": {"type": "boolean", "default": False},
        },
        "required": ["title", "content"],
    },
    handler=handle_post_announcement,
    preview=preview_post_announcement,
)

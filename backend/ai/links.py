"""Links to this LMS, pasted into the assistant.

A tutor pastes `https://www.lait.co/assignments/49019f92-...` and asks "go to
this link and check". The assistant has no web access, so it answered "I can't
open that link" -- while the link named a record the assistant can read through
its own tools. The URL was never the point; the id inside it was.

This recognises links to the console itself (the configured site's hosts, or a
bare path) and resolves each to the record it names, **through the same scoped
service the screen uses, as the person asking**. A record they cannot see
answers exactly like one that does not exist, so a pasted id cannot be used to
probe for records. Links to anywhere else are left alone: those really cannot
be opened, and the assistant is told so.
"""

from __future__ import annotations

import re
import uuid
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.models.identity.user import User

logger = get_logger(__name__)

_URL = re.compile(r"https?://[^\s<>()\"']+|(?<![\w/])/(?:assignments|quizzes|exams|courses|batches|sessions|resources)/[0-9a-fA-F-]{36}")
_PATH = re.compile(r"^/(assignments|quizzes|exams|courses|batches|sessions|resources)/([0-9a-fA-F-]{36})(?:/|$)")
MAX_LINKS = 5

# route segment -> (kind, the tool and argument that read it)
_KINDS = {
    "assignments": ("assignment", "get_assignment_brief(assignment_id=...)"),
    "quizzes": ("quiz", "the quiz tools with this quiz id"),
    "exams": ("exam", "get_exam_mark_sheet(exam id)"),
    "courses": ("course", "get_course_curriculum / get_teaching_context"),
    "batches": ("batch", "the batch tools with this batch's code"),
    "sessions": ("class session", "manage_batch_session / mark_session_attendance with this session id"),
    "resources": ("file", "search_course_knowledge"),
}


def _own_hosts() -> set[str]:
    settings = get_settings()
    hosts = {"localhost", "127.0.0.1"}
    for origin in list(getattr(settings.api, "cors_origins", []) or []):
        host = urlparse(str(origin)).hostname
        if host:
            hosts.add(host.lower())
    app_url = getattr(getattr(settings, "mail", None), "app_url", "") or ""
    if app_url:
        host = urlparse(app_url).hostname
        if host:
            hosts.add(host.lower())
    # "www.example.com" and "example.com" are the same site to a person pasting a link.
    hosts |= {h[4:] for h in hosts if h.startswith("www.")} | {f"www.{h}" for h in hosts if not h.startswith("www.")}
    return hosts


def find_links(text: str, hosts: set[str] | None = None) -> tuple[list[tuple[str, str, uuid.UUID]], list[str]]:
    """(internal links as (url, route, id), external URLs) found in `text`."""
    hosts = hosts if hosts is not None else _own_hosts()
    internal: list[tuple[str, str, uuid.UUID]] = []
    external: list[str] = []
    for raw in _URL.findall(text or ""):
        url = raw.rstrip(".,;:!?")
        parsed = urlparse(url) if url.startswith("http") else None
        path = parsed.path if parsed else url
        own = parsed is None or (parsed.hostname or "").lower() in hosts
        match = _PATH.match(path)
        if own and match:
            try:
                internal.append((url, match.group(1), uuid.UUID(match.group(2))))
            except ValueError:
                external.append(url)
        elif parsed is not None:
            external.append(url)
    return internal[:MAX_LINKS], external[:MAX_LINKS]


async def _label(session: AsyncSession, user: User, route: str, public_id: uuid.UUID) -> str | None:
    """The record's name, read as `user`; None when they cannot see it."""
    from backend.core.errors import AppError

    try:
        if route == "assignments":
            from backend.services.assignment_service import AssignmentService
            row = await AssignmentService(session).get(public_id, actor=user)
            return f"'{row.title}'"
        if route == "quizzes":
            from backend.services.quiz_service import QuizService
            row = await QuizService(session).get(public_id, actor=user)
            return f"'{row.title}'"
        if route == "exams":
            from backend.services.exam_service import ExamService
            row = await ExamService(session).get(public_id, actor=user)
            return f"'{row.title}'"
        if route == "courses":
            from backend.services.course_service import CourseService
            row = await CourseService(session).get(public_id, actor=user)
            return f"'{row.title}' (code {row.code})"
        if route == "batches":
            from backend.services.batch_service import BatchService
            row = await BatchService(session).get(public_id, actor=user)
            return f"batch code {row.batch_code}"
        if route == "sessions":
            from backend.services.session_service import SessionService
            row = await SessionService(session).get(public_id, actor=user)
            return f"the class on {row.session_start_time:%Y-%m-%d %H:%M} UTC"
        if route == "resources":
            from backend.services.resource_service import ResourceService
            row = await ResourceService(session).get(public_id, actor=user)
            return f"'{row.name}'"
    except AppError:
        return None
    except Exception:  # noqa: BLE001 -- a link note is a convenience; it must never fail the turn
        logger.warning("Could not resolve an LMS link", extra={"route": route})
        return None
    return None


async def describe_links(session: AsyncSession, user: User, text: str) -> str:
    """A note for the model about the links in `text`, or "" when there are none."""
    internal, external = find_links(text)
    if not internal and not external:
        return ""
    lines = ["[LINKS IN THIS MESSAGE -- resolved by the system]"]
    for url, route, public_id in internal:
        kind, how = _KINDS[route]
        label = await _label(session, user, route, public_id)
        if label is None:
            lines.append(f"- {url}: a link to this LMS naming a {kind} that does not exist or that you cannot see. "
                         "Say so; do not guess what it contains.")
        else:
            lines.append(f"- {url}: this LMS's {kind} {label}, id {public_id}. You CAN read it -- use {how}. "
                         "Do not say you cannot open the link.")
    for url in external:
        lines.append(f"- {url}: an outside website. You have no web access and have not seen it; say so if it matters.")
    return "\n\n" + "\n".join(lines)

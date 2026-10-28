"""User-Scoped AI Conversation State & Memory Management.

Ensures strict context isolation, prevents cross-user conversation leakage,
and provides user-controlled memory deletion in compliance with §9.6.

**What is kept, and for how long.** A conversation is kept for
`AI_CONVERSATION_RETENTION_DAYS` (30 by default) and then deleted. Of each
tool call, only its name and outcome are kept -- not the records it returned.
A stored result is a copy of data taken at one moment under one person's
access; it would outlive that access (a tutor reassigned away from a batch
could scroll back to its marks) and duplicate records the platform already
holds properly. The one exception is an assessment draft, which the assistant
drawer re-renders from history.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.config import get_ai_settings
from backend.core.logging import get_logger
from backend.models.ai_embedding import AIConversationMessage

logger = get_logger(__name__)

# Tool calls whose full (already privacy-filtered) result is kept, because the
# console renders it again when the conversation is reopened.
_RESULTS_KEPT_FOR = frozenset({"create_assessment_draft"})


def minimise_tool_calls(tool_calls: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Reduce tool calls to what may be stored: name and outcome."""
    if not tool_calls:
        return None
    kept = []
    for call in tool_calls:
        name = call.get("tool")
        result = call.get("result")
        if name in _RESULTS_KEPT_FOR:
            kept.append({"tool": name, "result": result})
            continue
        outcome: dict[str, Any] = {}
        if isinstance(result, dict):
            for key in ("success", "status"):
                if key in result:
                    outcome[key] = result[key]
        kept.append({"tool": name, "result": outcome})
    return kept


def _cutoff() -> datetime:
    return datetime.now(UTC) - timedelta(days=get_ai_settings().conversation_retention_days)


class ConversationStateManager:
    """Manages persistent conversational memory scoped to individual users."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append_message(
        self,
        *,
        user_id: int,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> AIConversationMessage | None:
        """Persist a conversation message bound to the user, and expire old ones."""
        try:
            # A savepoint, so a failure here cannot poison the caller's
            # transaction: the history is a convenience, the request's own work
            # is not, and an aborted flush would otherwise fail its commit.
            async with self.session.begin_nested():
                await self.session.execute(
                    delete(AIConversationMessage).where(
                        AIConversationMessage.user_id == user_id,
                        AIConversationMessage.created_at < _cutoff(),
                    )
                )
                msg = AIConversationMessage(
                    user_id=user_id,
                    role=role,
                    content=content,
                    tool_calls=minimise_tool_calls(tool_calls),
                )
                self.session.add(msg)
                await self.session.flush()
            return msg
        except Exception as exc:
            logger.warning("Failed to persist conversation message (database unmigrated or unavailable): %s", exc)
            return None

    async def get_recent_history(
        self,
        *,
        user_id: int,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Retrieve the most recent conversation messages for the user in chronological order.

        Messages past the retention window are excluded even if no write has
        yet deleted them: retention must not depend on the person speaking again.
        """
        try:
            stmt = (
                select(AIConversationMessage)
                .where(
                    AIConversationMessage.user_id == user_id,
                    AIConversationMessage.created_at >= _cutoff(),
                )
                .order_by(desc(AIConversationMessage.created_at))
                .limit(limit)
            )
            rows = list((await self.session.execute(stmt)).scalars().all())
            # Return in chronological order
            rows.reverse()

            return [
                {
                    "message_id": str(r.public_id),
                    "role": r.role,
                    "content": r.content,
                    "tool_calls": r.tool_calls,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        except Exception as exc:
            logger.warning("Failed to retrieve conversation history (database unmigrated or unavailable): %s", exc)
            return []

    async def clear_history(self, *, user_id: int) -> int:
        """Permanently delete all conversation messages for a user (Data Subject Erasure)."""
        try:
            stmt = (
                delete(AIConversationMessage)
                .where(AIConversationMessage.user_id == user_id)
            )
            res = await self.session.execute(stmt)
            count = res.rowcount or 0
            await self.session.flush()
            logger.info("Cleared %d conversation messages for user ID %d", count, user_id)
            return count
        except Exception as exc:
            logger.warning("Failed to clear conversation history: %s", exc)
            return 0

"""User-Scoped AI Conversation State & Memory Management.

Ensures strict context isolation, prevents cross-user conversation leakage,
and provides user-controlled memory deletion in compliance with §9.6.
"""

from __future__ import annotations

from typing import Any, Sequence
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.logging import get_logger
from backend.models.ai_embedding import AIConversationMessage
from backend.models.identity.user import User

logger = get_logger(__name__)


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
        """Persist a conversation message bound to the user."""
        try:
            msg = AIConversationMessage(
                user_id=user_id,
                role=role,
                content=content,
                tool_calls=tool_calls,
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
        """Retrieve the most recent conversation messages for the user in chronological order."""
        try:
            stmt = (
                select(AIConversationMessage)
                .where(AIConversationMessage.user_id == user_id)
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


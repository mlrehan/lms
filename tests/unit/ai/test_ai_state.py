"""Unit tests for User-Scoped AI Conversation State Management."""

import asyncio
import uuid
from datetime import UTC, datetime
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.ai.state import ConversationStateManager
from backend.models.ai_embedding import AIConversationMessage


def test_conversation_state_manager_append_and_retrieve():
    async def run_test():
        mock_session = MagicMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        msg1 = AIConversationMessage(
            id=1,
            public_id=uuid.uuid4(),
            user_id=42,
            role="user",
            content="Hello AI",
            created_at=datetime.now(UTC),
        )
        msg2 = AIConversationMessage(
            id=2,
            public_id=uuid.uuid4(),
            user_id=42,
            role="assistant",
            content="Hello! How can I assist your studies today?",
            created_at=datetime.now(UTC),
        )

        mock_result = MagicMock()
        # Order by desc in query returns [msg2, msg1]
        mock_result.scalars.return_value.all.return_value = [msg2, msg1]
        mock_session.execute = AsyncMock(return_value=mock_result)

        mgr = ConversationStateManager(session=mock_session)

        # 1. Append message
        appended = await mgr.append_message(
            user_id=42,
            role="user",
            content="Hello AI",
        )
        assert appended.user_id == 42
        assert appended.content == "Hello AI"
        mock_session.add.assert_called_once()
        mock_session.flush.assert_awaited()

        # 2. Get history (should be reversed into chronological order [msg1, msg2])
        history = await mgr.get_recent_history(user_id=42, limit=10)
        assert len(history) == 2
        assert history[0]["content"] == "Hello AI"
        assert history[1]["content"] == "Hello! How can I assist your studies today?"

    asyncio.run(run_test())


def test_conversation_state_manager_clear_history():
    async def run_test():
        mock_session = MagicMock()
        mock_result = MagicMock(rowcount=5)
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.flush = AsyncMock()

        mgr = ConversationStateManager(session=mock_session)
        deleted_count = await mgr.clear_history(user_id=42)

        assert deleted_count == 5
        mock_session.execute.assert_awaited_once()
        mock_session.flush.assert_awaited()

    asyncio.run(run_test())


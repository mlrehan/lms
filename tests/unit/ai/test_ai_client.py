"""Unit tests for OpenAI client error mapping and client initialization."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import openai

from backend.ai.client import (
    AIClientError,
    AIRateLimitError,
    OpenAIClient,
    get_openai_client,
)
from backend.core.errors import ServiceUnavailableError


def test_openai_client_singleton():
    c1 = get_openai_client()
    c2 = get_openai_client()
    assert c1 is c2
    assert c1.settings.openai_model == "gpt-5-mini"


def test_chat_completion_maps_rate_limit_error():
    async def run_test():
        client = OpenAIClient()
        mock_async_client = MagicMock()
        mock_async_client.chat.completions.create = AsyncMock(
            side_effect=openai.RateLimitError(
                message="Rate limit exceeded",
                response=MagicMock(status_code=429),
                body=None,
            )
        )
        client._client = mock_async_client

        with pytest.raises(AIRateLimitError):
            await client.chat_completion(
                messages=[{"role": "user", "content": "Hello"}],
            )

    asyncio.run(run_test())


def test_chat_completion_maps_timeout_error():
    async def run_test():
        client = OpenAIClient()
        mock_async_client = MagicMock()
        mock_async_client.chat.completions.create = AsyncMock(
            side_effect=openai.APITimeoutError(request=MagicMock())
        )
        client._client = mock_async_client

        with pytest.raises(ServiceUnavailableError):
            await client.chat_completion(
                messages=[{"role": "user", "content": "Hello"}],
            )

    asyncio.run(run_test())


def test_chat_completion_maps_auth_error():
    async def run_test():
        client = OpenAIClient()
        mock_async_client = MagicMock()
        mock_async_client.chat.completions.create = AsyncMock(
            side_effect=openai.AuthenticationError(
                message="Incorrect API key",
                response=MagicMock(status_code=401),
                body=None,
            )
        )
        client._client = mock_async_client

        with pytest.raises(AIClientError):
            await client.chat_completion(
                messages=[{"role": "user", "content": "Hello"}],
            )

    asyncio.run(run_test())


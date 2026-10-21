"""Asynchronous OpenAI client wrapper.

Provides robust, rate-limited, retried interactions with OpenAI endpoints
while mapping upstream errors into the LMS AppError hierarchy.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator, Sequence
import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from backend.ai.config import AISettings, get_ai_settings
from backend.core.errors import (
    AppError,
    ServiceUnavailableError,
    ValidationError,
)
from backend.core.logging import get_logger

logger = get_logger(__name__)


class AIClientError(AppError):
    """Raised when an AI platform operation fails."""

    status_code = 502
    code = "AI_PLATFORM_ERROR"


class AIRateLimitError(AppError):
    """Raised when OpenAI rate limits are exceeded."""

    status_code = 429
    code = "AI_RATE_LIMIT_EXCEEDED"


class OpenAIClient:
    """Thread-safe asynchronous client for OpenAI LLM and multimodal services."""

    def __init__(self, settings: AISettings | None = None) -> None:
        self.settings = settings or get_ai_settings()
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self.settings.get_api_key_str(),
                timeout=self.settings.request_timeout_seconds,
                max_retries=self.settings.max_retries,
            )
        return self._client

    async def chat_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = 2048,
    ) -> ChatCompletion:
        """Execute chat completion with retry and error mapping."""
        target_model = model or self.settings.openai_model
        params: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
        }
        # Some models (like newer reasoning or gpt-5 models) do not accept custom temperature
        is_fixed_temp_model = any(prefix in target_model.lower() for prefix in ("o1", "o3", "gpt-5"))
        if not is_fixed_temp_model and temperature is not None:
            params["temperature"] = temperature
        if max_tokens:
            params["max_completion_tokens"] = max_tokens
        if tools:
            params["tools"] = tools
        if tool_choice:
            params["tool_choice"] = tool_choice

        try:
            return await self.client.chat.completions.create(**params)
        except openai.BadRequestError as exc:
            # If rejected due to temperature parameter on unknown model, retry once without temperature
            if "temperature" in str(exc).lower() and "temperature" in params:
                logger.info("Retrying chat completion without temperature parameter for model %s", target_model)
                params.pop("temperature", None)
                return await self.client.chat.completions.create(**params)
            logger.error("OpenAI bad request error: %s", exc)
            raise AIClientError(f"AI platform error: {exc.message}") from exc
        except openai.RateLimitError as exc:
            logger.warning("OpenAI rate limit encountered: %s", exc)
            raise AIRateLimitError("AI service is currently busy. Please retry shortly.") from exc
        except openai.AuthenticationError as exc:
            logger.error("OpenAI authentication failed: %s", exc)
            raise AIClientError("AI platform authentication configuration is invalid.") from exc
        except openai.APIConnectionError as exc:
            logger.error("OpenAI connection failed: %s", exc)
            raise ServiceUnavailableError("Cannot connect to AI service. Please verify network.") from exc
        except openai.APITimeoutError as exc:
            logger.warning("OpenAI request timed out: %s", exc)
            raise ServiceUnavailableError("AI response timed out. Please try again.") from exc
        except openai.APIError as exc:
            logger.error("OpenAI general API error: %s", exc)
            raise AIClientError(f"AI platform error: {exc.message}") from exc

    async def stream_chat_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = 2048,
    ) -> AsyncGenerator[str, None]:
        """Stream response text chunks for live conversational UI feedback."""
        target_model = model or self.settings.openai_model
        params: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "stream": True,
        }
        is_fixed_temp_model = any(prefix in target_model.lower() for prefix in ("o1", "o3", "gpt-5"))
        if not is_fixed_temp_model and temperature is not None:
            params["temperature"] = temperature
        if max_tokens:
            params["max_completion_tokens"] = max_tokens

        try:
            stream = await self.client.chat.completions.create(**params)
            async for chunk in stream:  # type: ignore[union-attr]
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except openai.BadRequestError as exc:
            if "temperature" in str(exc).lower() and "temperature" in params:
                logger.info("Retrying stream completion without temperature parameter for model %s", target_model)
                params.pop("temperature", None)
                stream = await self.client.chat.completions.create(**params)
                async for chunk in stream:  # type: ignore[union-attr]
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
            else:
                logger.error("OpenAI streaming bad request error: %s", exc)
                raise AIClientError(f"AI stream bad request: {exc.message}") from exc
        except openai.APIError as exc:
            logger.error("OpenAI streaming error: %s", exc)
            raise AIClientError(f"AI stream interrupted: {exc.message}") from exc

    async def create_embeddings(
        self,
        texts: Sequence[str],
        model: str | None = None,
    ) -> list[list[float]]:
        """Generate high-dimensional vector embeddings for text chunks."""
        if not texts:
            return []
        target_model = model or self.settings.openai_embedding_model
        try:
            resp = await self.client.embeddings.create(
                input=list(texts),
                model=target_model,
            )
            return [record.embedding for record in resp.data]
        except openai.APIError as exc:
            logger.error("OpenAI embedding error: %s", exc)
            raise AIClientError(f"Could not compute embeddings: {exc.message}") from exc

    async def transcribe_audio(
        self,
        *,
        audio_file: tuple[str, bytes],
        model: str | None = None,
    ) -> str:
        """Transcribe audio file bytes using the configured transcription model."""
        target_model = model or self.settings.openai_transcription_model
        try:
            resp = await self.client.audio.transcriptions.create(
                model=target_model,
                file=audio_file,
            )
            return resp.text
        except openai.APIError as exc:
            logger.error("OpenAI transcription error: %s", exc)
            raise AIClientError(f"Audio transcription failed: {exc.message}") from exc


_openai_client_instance: OpenAIClient | None = None


def get_openai_client() -> OpenAIClient:
    """Return singleton instance of OpenAIClient."""
    global _openai_client_instance
    if _openai_client_instance is None:
        _openai_client_instance = OpenAIClient()
    return _openai_client_instance


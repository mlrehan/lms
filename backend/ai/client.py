"""Asynchronous OpenAI client wrapper.

Provides robust, rate-limited, retried interactions with OpenAI endpoints
while mapping upstream errors into the LMS AppError hierarchy.

Supports both the OpenAI Responses API (/v1/responses) and the Chat
Completions API (/v1/chat/completions), selected via the
``OPENAI_API_MODE`` setting (``"responses"`` or ``"chat"``).
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator, Sequence

import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionChunk, ChatCompletionMessage
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)
from openai.types.chat.chat_completion import Choice

from backend.ai.config import AISettings, get_ai_settings
from backend.core.errors import (
    AppError,
    ServiceUnavailableError,
    ValidationError,
)
from backend.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Conversion helpers – Chat Completions format ⇄ Responses API format
# ---------------------------------------------------------------------------


def _convert_tools_for_responses(
    tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Convert chat-format tools to responses-format tools.

    Chat format:
        ``{"type": "function", "function": {"name": …, "description": …, "parameters": …}}``

    Responses format:
        ``{"type": "function", "name": …, "description": …, "parameters": …}``

    If a tool already has ``"name"`` at top level (already responses format),
    it is passed through unchanged.
    """
    if not tools:
        return None

    converted: list[dict[str, Any]] = []
    for tool in tools:
        # Already in responses format?
        if "name" in tool:
            converted.append(tool)
            continue

        fn = tool.get("function", {})
        converted.append(
            {
                "type": "function",
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {}),
            }
        )
    return converted


def _user_content_for_responses(content: Any) -> Any:
    """Chat-format content parts (text, image_url) as Responses input parts."""
    if not isinstance(content, list):
        return content
    parts: list[dict[str, Any]] = []
    for part in content:
        kind = part.get("type") if isinstance(part, dict) else None
        if kind == "text":
            parts.append({"type": "input_text", "text": part.get("text", "")})
        elif kind == "image_url":
            image = part.get("image_url") or {}
            parts.append({
                "type": "input_image",
                "image_url": image.get("url", ""),
                "detail": image.get("detail", "auto"),
            })
        elif isinstance(part, dict):
            parts.append(part)
    return parts


def _convert_messages_for_responses(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert chat-format messages to Responses API input items.

    Key mapping rules:
    * ``system`` role → ``developer`` role (Responses API convention).
    * ``assistant`` with ``tool_calls`` → content item + ``function_call`` items.
    * ``tool`` role → ``function_call_output`` items.
    """
    items: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content") or ""

        if role == "system":
            items.append({"role": "developer", "content": content})

        elif role == "user":
            items.append({"role": "user", "content": _user_content_for_responses(content)})

        elif role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                # Emit assistant content first (if non-empty).
                if content:
                    items.append({"role": "assistant", "content": content})
                for tc in tool_calls:
                    # Support both dict and object (e.g. Pydantic model) representations.
                    tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "")
                    if isinstance(tc, dict):
                        fn = tc.get("function", {})
                        fn_name = fn.get("name", "")
                        fn_args = fn.get("arguments", "")
                    else:
                        fn = getattr(tc, "function", None)
                        fn_name = getattr(fn, "name", "") if fn else ""
                        fn_args = getattr(fn, "arguments", "") if fn else ""
                    items.append(
                        {
                            "type": "function_call",
                            "call_id": tc_id,
                            "name": fn_name,
                            "arguments": fn_args,
                        }
                    )
            else:
                items.append({"role": "assistant", "content": content})

        elif role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": msg.get("tool_call_id", ""),
                    "output": content,
                }
            )
        else:
            # Pass through any other roles unchanged.
            items.append(msg)

    return items


def _response_to_chat_completion(response: Any, model: str) -> ChatCompletion:
    """Convert an OpenAI Responses API ``Response`` object to a ``ChatCompletion``.

    This shim allows existing agent code written against the Chat Completions
    schema to work unchanged when the Responses API is in use.
    """
    text_content: str | None = None
    tool_calls_list: list[ChatCompletionMessageToolCall] = []

    for item in response.output:
        item_type = getattr(item, "type", None)

        if item_type == "function_call":
            tool_calls_list.append(
                ChatCompletionMessageToolCall(
                    id=item.call_id,
                    type="function",
                    function=Function(
                        name=item.name,
                        arguments=item.arguments,
                    ),
                )
            )
        elif item_type == "message":
            # Collect text from content parts.
            parts = getattr(item, "content", []) or []
            texts: list[str] = []
            for part in parts:
                if getattr(part, "type", "") == "output_text":
                    texts.append(getattr(part, "text", ""))
            if texts:
                text_content = "".join(texts)

    msg = ChatCompletionMessage(
        role="assistant",
        content=text_content or None,
        tool_calls=tool_calls_list or None,
    )
    choice = Choice(
        finish_reason="tool_calls" if tool_calls_list else "stop",
        index=0,
        message=msg,
    )

    created_at = getattr(response, "created_at", 0)
    return ChatCompletion(
        id=response.id,
        choices=[choice],
        created=int(created_at) if created_at else 0,
        model=model,
        object="chat.completion",
    )


# ---------------------------------------------------------------------------
# Error classes
# ---------------------------------------------------------------------------


class AIClientError(AppError):
    """Raised when an AI platform operation fails."""

    status_code = 502
    code = "AI_PLATFORM_ERROR"


class AIRateLimitError(AppError):
    """Raised when OpenAI rate limits are exceeded."""

    status_code = 429
    code = "AI_RATE_LIMIT_EXCEEDED"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


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

    # ---- helpers -----------------------------------------------------------

    @property
    def _use_responses_api(self) -> bool:
        """Return ``True`` when the configured API mode is ``responses``."""
        return self.settings.openai_api_mode == "responses"

    @property
    def _reasoning_param(self) -> dict[str, Any] | None:
        """Return a ``reasoning`` parameter dict if reasoning effort is configured."""
        effort = self.settings.openai_reasoning_effort
        if effort and effort.lower() != "none":
            return {"effort": effort}
        return None

    # ---- Chat Completions --------------------------------------------------

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
        # Delegate to Responses API when configured.
        if self._use_responses_api:
            return await self._responses_completion(
                messages=messages,
                model=model,
                tools=tools,
                tool_choice=tool_choice,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        target_model = model or self.settings.openai_model
        params: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
        }
        # Some models (like newer reasoning or gpt-5 models) do not accept custom temperature
        is_fixed_temp_model = any(prefix in target_model.lower() for prefix in ("o1", "o3", "gpt-5", "gpt-6"))
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
        except openai.NotFoundError as exc:
            if target_model != "gpt-4o-mini":
                logger.warning("Model '%s' not found or accessible; falling back to 'gpt-4o-mini': %s", target_model, exc)
                params["model"] = "gpt-4o-mini"
                return await self.client.chat.completions.create(**params)
            logger.error("OpenAI model not found: %s", exc)
            raise AIClientError(f"AI platform model error: {exc.message}") from exc
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

    # ---- Responses API completion -----------------------------------------

    async def _responses_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = 2048,
    ) -> ChatCompletion:
        """Execute a completion via the Responses API and return a ``ChatCompletion``."""
        target_model = model or self.settings.openai_model
        input_items = _convert_messages_for_responses(messages)
        converted_tools = _convert_tools_for_responses(tools)

        params: dict[str, Any] = {
            "model": target_model,
            "input": input_items,
        }

        if converted_tools:
            params["tools"] = converted_tools

        # Reasoning parameter
        reasoning = self._reasoning_param
        if reasoning:
            params["reasoning"] = reasoning

        if max_tokens:
            params["max_output_tokens"] = max_tokens

        # Some models do not accept a custom temperature value.
        is_fixed_temp_model = any(
            prefix in target_model.lower() for prefix in ("o1", "o3", "gpt-5", "gpt-6")
        )
        if not is_fixed_temp_model and temperature is not None:
            params["temperature"] = temperature

        if tool_choice is not None:
            # String values ("auto", "required", "none") or dict values pass through.
            params["tool_choice"] = tool_choice

        try:
            response = await self.client.responses.create(**params)
            return _response_to_chat_completion(response, target_model)
        except openai.NotFoundError as exc:
            if target_model != "gpt-4o-mini":
                logger.warning(
                    "Responses model '%s' not found; falling back to 'gpt-4o-mini' via chat completions: %s",
                    target_model,
                    exc,
                )
                # Fallback uses chat completions with gpt-4o-mini.
                fallback_params: dict[str, Any] = {
                    "model": "gpt-4o-mini",
                    "messages": messages,
                }
                if not is_fixed_temp_model and temperature is not None:
                    fallback_params["temperature"] = temperature
                if max_tokens:
                    fallback_params["max_completion_tokens"] = max_tokens
                if tools:
                    fallback_params["tools"] = tools
                if tool_choice:
                    fallback_params["tool_choice"] = tool_choice
                return await self.client.chat.completions.create(**fallback_params)
            logger.error("OpenAI model not found: %s", exc)
            raise AIClientError(f"AI platform model error: {exc.message}") from exc
        except openai.BadRequestError as exc:
            if "temperature" in str(exc).lower() and "temperature" in params:
                logger.info("Retrying responses completion without temperature for model %s", target_model)
                params.pop("temperature", None)
                response = await self.client.responses.create(**params)
                return _response_to_chat_completion(response, target_model)
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

    # ---- Streaming ---------------------------------------------------------

    async def stream_chat_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = 2048,
    ) -> AsyncGenerator[str, None]:
        """Stream response text chunks for live conversational UI feedback."""
        # Delegate to Responses API when configured.
        if self._use_responses_api:
            async for chunk in self._stream_responses_completion(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                yield chunk
            return

        target_model = model or self.settings.openai_model
        params: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "stream": True,
        }
        is_fixed_temp_model = any(prefix in target_model.lower() for prefix in ("o1", "o3", "gpt-5", "gpt-6"))
        if not is_fixed_temp_model and temperature is not None:
            params["temperature"] = temperature
        if max_tokens:
            params["max_completion_tokens"] = max_tokens

        try:
            stream = await self.client.chat.completions.create(**params)
            async for chunk in stream:  # type: ignore[union-attr]
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except openai.NotFoundError as exc:
            if target_model != "gpt-4o-mini":
                logger.warning("Stream model '%s' not found or accessible; falling back to 'gpt-4o-mini': %s", target_model, exc)
                params["model"] = "gpt-4o-mini"
                stream = await self.client.chat.completions.create(**params)
                async for chunk in stream:  # type: ignore[union-attr]
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                return
            logger.error("OpenAI model not found: %s", exc)
            raise AIClientError(f"AI platform model error: {exc.message}") from exc
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

    # ---- Responses API streaming -------------------------------------------

    async def _stream_responses_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = 2048,
    ) -> AsyncGenerator[str, None]:
        """Stream text deltas via the Responses API."""
        target_model = model or self.settings.openai_model
        input_items = _convert_messages_for_responses(messages)

        params: dict[str, Any] = {
            "model": target_model,
            "input": input_items,
            "stream": True,
        }

        reasoning = self._reasoning_param
        if reasoning:
            params["reasoning"] = reasoning

        if max_tokens:
            params["max_output_tokens"] = max_tokens

        is_fixed_temp_model = any(
            prefix in target_model.lower() for prefix in ("o1", "o3", "gpt-5", "gpt-6")
        )
        if not is_fixed_temp_model and temperature is not None:
            params["temperature"] = temperature

        try:
            stream = await self.client.responses.create(**params)
            async for event in stream:
                if getattr(event, "type", "") == "response.output_text.delta" and event.delta:
                    yield event.delta
        except openai.NotFoundError as exc:
            if target_model != "gpt-4o-mini":
                logger.warning(
                    "Responses stream model '%s' not found; falling back to 'gpt-4o-mini': %s",
                    target_model,
                    exc,
                )
                fallback_params: dict[str, Any] = {
                    "model": "gpt-4o-mini",
                    "messages": messages,
                    "stream": True,
                }
                if not is_fixed_temp_model and temperature is not None:
                    fallback_params["temperature"] = temperature
                if max_tokens:
                    fallback_params["max_completion_tokens"] = max_tokens
                stream = await self.client.chat.completions.create(**fallback_params)
                async for chunk in stream:  # type: ignore[union-attr]
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                return
            logger.error("OpenAI model not found: %s", exc)
            raise AIClientError(f"AI platform model error: {exc.message}") from exc
        except openai.BadRequestError as exc:
            if "temperature" in str(exc).lower() and "temperature" in params:
                logger.info("Retrying responses stream without temperature for model %s", target_model)
                params.pop("temperature", None)
                stream = await self.client.responses.create(**params)
                async for event in stream:
                    if getattr(event, "type", "") == "response.output_text.delta" and event.delta:
                        yield event.delta
            else:
                logger.error("OpenAI responses streaming bad request error: %s", exc)
                raise AIClientError(f"AI stream bad request: {exc.message}") from exc
        except openai.APIError as exc:
            logger.error("OpenAI responses streaming error: %s", exc)
            raise AIClientError(f"AI stream interrupted: {exc.message}") from exc

    # ---- Embeddings --------------------------------------------------------

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

    # ---- Audio transcription -----------------------------------------------

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

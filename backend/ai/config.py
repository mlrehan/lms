"""AI subsystem configuration.

Loads settings from the project's root .env without modifying or overriding
any existing LMS configuration schemas.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.core.errors import ServiceUnavailableError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


class AISettings(BaseSettings):
    """Runtime configuration for OpenAI models and agentic safeguards."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    openai_api_key: SecretStr = Field(
        default=SecretStr(""),
        alias="OPENAI_API_KEY",
        description="Master API key for OpenAI platform services",
    )
    openai_model: str = Field(
        default="gpt-4o",
        alias="OPENAI_MODEL",
        description="Default reasoning and conversational agent model",
    )
    openai_intent_model: str = Field(
        default="gpt-4o-mini",
        alias="OPENAI_INTENT_MODEL",
        description="Fast router model for user intent resolution and guardrail checks",
    )
    openai_transcription_model: str = Field(
        default="whisper-1",
        alias="OPENAI_TRANSCRIPTION_MODEL",
        description="Voice and audio transcription model",
    )
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        alias="OPENAI_EMBEDDING_MODEL",
        description="High-dimensional text embedding model for semantic RAG search",
    )
    openai_api_mode: str = Field(
        default="responses",
        alias="OPENAI_API_MODE",
        description="OpenAI API interaction mode: 'responses' (/v1/responses) or 'chat' (/v1/chat/completions)",
    )
    openai_reasoning_effort: str | None = Field(
        default="high",
        alias="OPENAI_REASONING_EFFORT",
        description="Reasoning effort level for models that support reasoning ('low', 'medium', 'high', 'none', or None)",
    )

    # Operational safeguards
    confirmation_ticket_ttl_seconds: int = Field(
        default=900,
        description="Expiration time in seconds for high-risk action confirmation tickets (15 minutes)",
    )
    request_timeout_seconds: float = Field(
        default=60.0,
        description="Maximum wall-clock seconds to wait for an OpenAI API response before timing out",
    )
    max_retries: int = Field(
        default=3,
        description="Number of automatic retries with exponential backoff on transient errors",
    )
    system_prompt_version: str = Field(
        default="1.0.0",
        description="Version identifier for immutable system instructions",
    )

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def clean_api_key(cls, value: str | SecretStr) -> str | SecretStr:
        if isinstance(value, str):
            # Clean any inadvertent whitespace or newline wrapping from .env
            cleaned = "".join(value.split())
            return SecretStr(cleaned)
        return value

    def get_api_key_str(self) -> str:
        key = self.openai_api_key.get_secret_value()
        if not key or key.strip().lower() in ("your_openai_api_key_here", "sk-...", ""):
            raise ServiceUnavailableError(
                "OPENAI_API_KEY is not configured or invalid in .env. Please configure a valid OpenAI API key."
            )
        return key


@lru_cache(maxsize=1)
def get_ai_settings() -> AISettings:
    """Return cached instance of AI configuration."""
    return AISettings()


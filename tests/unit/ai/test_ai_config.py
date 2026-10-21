"""Unit tests for AI configuration."""

import pytest
from pydantic import SecretStr

from backend.ai.config import AISettings, get_ai_settings


def test_ai_settings_loading():
    settings = get_ai_settings()
    assert settings.openai_model == "gpt-5-mini"
    assert settings.openai_intent_model == "gpt-5-mini"
    assert settings.openai_transcription_model == "gpt-4o-transcribe"
    assert settings.openai_embedding_model == "text-embedding-3-large"
    assert settings.confirmation_ticket_ttl_seconds == 900
    assert len(settings.get_api_key_str()) > 20


def test_ai_settings_key_cleaner():
    raw_with_spaces = "  sk-proj-test-1234567890 \n \r "
    settings = AISettings(
        OPENAI_API_KEY=raw_with_spaces,
    )
    assert settings.get_api_key_str() == "sk-proj-test-1234567890"

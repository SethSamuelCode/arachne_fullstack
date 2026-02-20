"""Tests for the ModelProvider base class and Gemini provider classes."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.providers import ModelProvider


class StubProvider(ModelProvider):
    """Minimal concrete implementation for testing the ABC."""

    def create_pydantic_model(self, using_cached_tools=False, cached_content_name=None):
        return object()


class TestModelProviderBase:
    def test_stub_instantiation(self):
        p = StubProvider(
            model_id="test-model",
            api_model_id="test/model-api",
            display_name="Test Model",
            provider_label="Test Provider",
            context_limit=100_000,
        )
        assert p.model_id == "test-model"
        assert p.api_model_id == "test/model-api"
        assert p.display_name == "Test Model"
        assert p.provider_label == "Test Provider"
        assert p.context_limit == 100_000

    def test_default_context_limit(self):
        p = StubProvider("m", "m", "M", "P")
        assert p.context_limit == 850_000

    def test_supports_caching_false_by_default(self):
        p = StubProvider("m", "m", "M", "P")
        assert p.supports_caching is False

    def test_supports_thinking_false_by_default(self):
        p = StubProvider("m", "m", "M", "P")
        assert p.supports_thinking is False

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            ModelProvider("m", "m", "M", "P")  # type: ignore[abstract]

    @pytest.mark.anyio
    async def test_count_tokens_basic(self):
        p = StubProvider("m", "m", "M", "P")
        messages = [{"role": "user", "content": "Hello world"}]
        result = await p.count_tokens(messages, system_prompt="You are helpful.")
        assert result > 0

    @pytest.mark.anyio
    async def test_count_tokens_empty(self):
        p = StubProvider("m", "m", "M", "P")
        result = await p.count_tokens([])
        assert result >= 1  # max(1, ...)

    @pytest.mark.anyio
    async def test_count_tokens_multipart_content(self):
        p = StubProvider("m", "m", "M", "P")
        messages = [{"role": "user", "content": [{"text": "part one"}, {"text": "part two"}]}]
        result = await p.count_tokens(messages)
        assert result > 0

    @pytest.mark.anyio
    async def test_count_tokens_none_content(self):
        """Malformed messages with None content should not raise and return minimum."""
        p = StubProvider("m", "m", "M", "P")
        messages = [{"role": "user", "content": None}]
        result = await p.count_tokens(messages)
        assert result >= 1


class TestGeminiModelProvider:
    """Tests for Gemini provider classes."""

    def test_gemini25_supports_caching(self):
        from app.agents.providers.gemini import Gemini25ModelProvider

        p = Gemini25ModelProvider("gemini-2.5-flash", "gemini-2.5-flash", "Gemini 2.5 Flash")
        assert p.supports_caching is True

    def test_gemini25_supports_thinking(self):
        from app.agents.providers.gemini import Gemini25ModelProvider

        p = Gemini25ModelProvider("gemini-2.5-flash", "gemini-2.5-flash", "Gemini 2.5 Flash")
        assert p.supports_thinking is True

    def test_gemini25_provider_label(self):
        from app.agents.providers.gemini import Gemini25ModelProvider

        p = Gemini25ModelProvider("gemini-2.5-flash", "gemini-2.5-flash", "Gemini 2.5 Flash")
        assert p.provider_label == "Google Gemini"

    def test_gemini3_provider_label(self):
        from app.agents.providers.gemini import Gemini3ModelProvider

        p = Gemini3ModelProvider(
            "gemini-3-flash-preview", "gemini-3-flash-preview", "Gemini 3 Flash"
        )
        assert p.provider_label == "Google Gemini"

    def test_gemini3_is_separate_class(self):
        from app.agents.providers.gemini import Gemini3ModelProvider, Gemini25ModelProvider

        assert Gemini25ModelProvider is not Gemini3ModelProvider

    def test_gemini25_attributes(self):
        from app.agents.providers.gemini import Gemini25ModelProvider

        p = Gemini25ModelProvider(
            "gemini-2.5-flash", "gemini-2.5-flash", "Gemini 2.5 Flash", context_limit=891_289
        )
        assert p.model_id == "gemini-2.5-flash"
        assert p.api_model_id == "gemini-2.5-flash"
        assert p.display_name == "Gemini 2.5 Flash"
        assert p.context_limit == 891_289

    def test_gemini3_attributes(self):
        from app.agents.providers.gemini import Gemini3ModelProvider

        p = Gemini3ModelProvider(
            "gemini-3-flash-preview",
            "gemini-3-flash-preview",
            "Gemini 3 Flash",
            context_limit=850_000,
        )
        assert p.model_id == "gemini-3-flash-preview"
        assert p.context_limit == 850_000

    def test_gemini25_build_model_settings_has_thinking(self):
        from app.agents.providers.gemini import Gemini25ModelProvider

        p = Gemini25ModelProvider("gemini-2.5-flash", "gemini-2.5-flash", "Gemini 2.5 Flash")
        ms = p._build_model_settings()
        assert "google_thinking_config" in ms
        assert ms["google_thinking_config"] is not None

    def test_gemini3_build_model_settings_has_thinking(self):
        from app.agents.providers.gemini import Gemini3ModelProvider

        p = Gemini3ModelProvider(
            "gemini-3-flash-preview", "gemini-3-flash-preview", "Gemini 3 Flash"
        )
        ms = p._build_model_settings()
        assert "google_thinking_config" in ms
        assert ms["google_thinking_config"] is not None

    @pytest.mark.anyio
    async def test_count_tokens_falls_back_on_error(self):
        from app.agents.providers.gemini import Gemini25ModelProvider

        p = Gemini25ModelProvider("gemini-2.5-flash", "gemini-2.5-flash", "Gemini 2.5 Flash")
        # Mock the client to raise an error
        mock_client = MagicMock()
        mock_client.aio.models.count_tokens = AsyncMock(side_effect=Exception("API error"))
        p._genai_client = mock_client
        messages = [{"role": "user", "content": "Hello world"}]
        result = await p.count_tokens(messages, system_prompt="Be helpful.")
        assert result >= 1

    @pytest.mark.anyio
    async def test_count_tokens_uses_api_result(self):
        from app.agents.providers.gemini import Gemini25ModelProvider

        p = Gemini25ModelProvider("gemini-2.5-flash", "gemini-2.5-flash", "Gemini 2.5 Flash")
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.total_tokens = 42
        mock_client.aio.models.count_tokens = AsyncMock(return_value=mock_response)
        p._genai_client = mock_client
        messages = [{"role": "user", "content": "Hello"}]
        result = await p.count_tokens(messages)
        assert result == 42

    @pytest.mark.anyio
    async def test_count_tokens_empty_messages_no_error(self):
        from app.agents.providers.gemini import Gemini25ModelProvider

        p = Gemini25ModelProvider("gemini-2.5-flash", "gemini-2.5-flash", "Gemini 2.5 Flash")
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.total_tokens = 1
        mock_client.aio.models.count_tokens = AsyncMock(return_value=mock_response)
        p._genai_client = mock_client
        result = await p.count_tokens([])
        assert result >= 1

    @pytest.mark.anyio
    async def test_count_tokens_none_content_fallback(self):
        """None message content should not raise in the Gemini API path."""
        from app.agents.providers.gemini import Gemini25ModelProvider

        p = Gemini25ModelProvider("gemini-2.5-flash", "gemini-2.5-flash", "Gemini 2.5 Flash")
        mock_client = MagicMock()
        mock_client.aio.models.count_tokens = AsyncMock(side_effect=Exception("API error"))
        p._genai_client = mock_client
        messages = [{"role": "user", "content": None}]
        result = await p.count_tokens(messages)
        assert result >= 1

"""Tests for the ModelProvider base class."""

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

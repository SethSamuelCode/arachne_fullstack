"""Tests for context optimizer session state compression.

Tests cover:
- SessionState schema validation
- compress_session_state() initial compression and merge
- compress_session_state() graceful failure
- optimize_context_window() compression trigger at 70% threshold
- optimize_context_window() no compression below threshold
- optimize_context_window() with existing compressed state injection
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse

from app.agents.context_optimizer import (
    _estimate_tokens,
    _fifo_trim,
    compress_session_state,
    optimize_context_window,
)
from app.schemas.conversation import SessionState

# =============================================================================
# SessionState Schema Tests
# =============================================================================


class TestSessionStateSchema:
    """Test SessionState Pydantic model validation."""

    def test_session_state_defaults(self):
        """Empty SessionState has correct defaults."""
        state = SessionState()
        assert state.logos == []
        assert state.pathos == []
        assert state.abstract == []
        assert state.conversation_summary == ""

    def test_session_state_with_data(self):
        """SessionState accepts valid data."""
        state = SessionState(
            logos=["User is building an AI chat app", "Stack: FastAPI + Next.js"],
            pathos=["Engaged and technically confident"],
            abstract=["Understands async/await deeply"],
            conversation_summary="Discussed architecture decisions.",
        )
        assert len(state.logos) == 2
        assert len(state.pathos) == 1
        assert len(state.abstract) == 1
        assert "architecture" in state.conversation_summary

    def test_session_state_serialization(self):
        """SessionState serializes to dict correctly."""
        state = SessionState(
            logos=["fact1"],
            pathos=["tone1"],
            abstract=["concept1"],
            conversation_summary="Summary here.",
        )
        d = state.model_dump()
        assert isinstance(d, dict)
        assert d["logos"] == ["fact1"]
        assert d["conversation_summary"] == "Summary here."

    def test_session_state_from_dict(self):
        """SessionState can be constructed from a dict."""
        data = {
            "logos": ["a", "b"],
            "pathos": [],
            "abstract": ["x"],
            "conversation_summary": "test",
        }
        state = SessionState(**data)
        assert state.logos == ["a", "b"]


# =============================================================================
# compress_session_state() Tests
# =============================================================================


class TestCompressSessionState:
    """Test the compress_session_state function."""

    @pytest.mark.anyio
    async def test_compress_initial_no_prior_state(self):
        """Initial compression with no previous state returns valid SessionState."""
        mock_response = MagicMock()
        mock_response.text = json.dumps(
            {
                "logos": ["User wants to build a chat app"],
                "pathos": ["Enthusiastic tone"],
                "abstract": ["Familiar with FastAPI"],
                "conversation_summary": "Discussed project setup.",
            }
        )

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        messages = [
            {"role": "user", "content": "I want to build a chat app with FastAPI"},
            {"role": "assistant", "content": "Great choice! FastAPI is excellent for that."},
        ]

        with patch("app.agents.context_optimizer._get_genai_client", return_value=mock_client):
            result = await compress_session_state(messages)

        assert result is not None
        assert "logos" in result
        assert "pathos" in result
        assert "abstract" in result
        assert "conversation_summary" in result
        assert len(result["logos"]) == 1

        # Verify the LLM was called with the compression prompt (not merge)
        call_kwargs = mock_client.aio.models.generate_content.call_args
        prompt = call_kwargs.kwargs.get("contents") or call_kwargs.args[0]
        # Should NOT contain <previous_state> since no prior state
        assert "<previous_state>" not in str(prompt)

    @pytest.mark.anyio
    async def test_compress_merge_with_existing_state(self):
        """Merge compression with existing state uses merge prompt."""
        mock_response = MagicMock()
        mock_response.text = json.dumps(
            {
                "logos": ["User builds chat app", "Now adding compression"],
                "pathos": ["Engaged"],
                "abstract": ["Knows FastAPI", "Understands LLMs"],
                "conversation_summary": "Extended discussion about compression.",
            }
        )

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        messages = [
            {"role": "user", "content": "Let's add session state compression"},
            {"role": "assistant", "content": "Good idea, here's the design..."},
        ]
        previous_state = {
            "logos": ["User builds chat app"],
            "pathos": ["Enthusiastic"],
            "abstract": ["Knows FastAPI"],
            "conversation_summary": "Discussed project setup.",
        }

        with patch("app.agents.context_optimizer._get_genai_client", return_value=mock_client):
            result = await compress_session_state(messages, previous_state=previous_state)

        assert result is not None
        assert len(result["logos"]) == 2

        # Verify merge prompt was used (contains <previous_state>)
        call_kwargs = mock_client.aio.models.generate_content.call_args
        prompt = call_kwargs.kwargs.get("contents") or call_kwargs.args[0]
        assert "<previous_state>" in str(prompt)

    @pytest.mark.anyio
    async def test_compress_failure_returns_none(self):
        """Compression failure returns None (graceful degradation)."""
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("API error")
        )

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        with patch("app.agents.context_optimizer._get_genai_client", return_value=mock_client):
            result = await compress_session_state(messages)

        assert result is None

    @pytest.mark.anyio
    async def test_compress_empty_messages_returns_none(self):
        """Empty message list returns None."""
        result = await compress_session_state([])
        assert result is None

    @pytest.mark.anyio
    async def test_compress_invalid_json_returns_none(self):
        """Invalid JSON from LLM returns None."""
        mock_response = MagicMock()
        mock_response.text = "not valid json"

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]

        with patch("app.agents.context_optimizer._get_genai_client", return_value=mock_client):
            result = await compress_session_state(messages)

        assert result is None


# =============================================================================
# optimize_context_window() Tests
# =============================================================================


class TestOptimizeContextWindow:
    """Test optimize_context_window with compression support."""

    @pytest.mark.anyio
    async def test_empty_history(self):
        """Empty history returns empty result with no compression."""
        result = await optimize_context_window(
            history=[],
            model_name="gemini-2.5-flash",
        )
        assert result["history"] == []
        assert result["new_compressed_state"] is None
        assert result["new_compressed_at_message_id"] is None

    @pytest.mark.anyio
    async def test_below_threshold_no_compression(self):
        """No compression when context is below 70% threshold."""
        # Create a small history that won't exceed the threshold
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]

        result = await optimize_context_window(
            history=history,
            model_name="gemini-2.5-flash",
            max_context_tokens=100_000,  # Large budget relative to messages
        )

        assert result["new_compressed_state"] is None
        assert result["new_compressed_at_message_id"] is None
        # All messages should be kept
        assert len(result["history"]) == 3

    @pytest.mark.anyio
    async def test_compression_triggers_at_threshold(self):
        """Compression triggers when context exceeds 70% of budget."""
        # Each message ~1000 tokens (4000 chars / 4)
        large_content = "x" * 4000
        history = [
            {"role": "user", "content": large_content},
            {"role": "assistant", "content": large_content},
            {"role": "user", "content": large_content},
            {"role": "assistant", "content": large_content},
            {"role": "user", "content": large_content},
            {"role": "assistant", "content": large_content},
            {"role": "user", "content": "Current question"},
        ]
        # total_used = 8192 (response) + 6000 (6 msgs * 1000 tok) + 4 (latest) = 14196
        # budget = 20000 => ratio = 14196/20000 = 0.71 > 0.70 ✓
        # target_tokens = 20000*0.6 - 8192 - 4 = 3804
        # Only 3 newest messages (3000 tok) fit target, so 3 oldest get compressed

        compressed_result = {
            "logos": ["Compressed fact"],
            "pathos": ["Compressed tone"],
            "abstract": [],
            "conversation_summary": "Compressed summary.",
        }

        with patch(
            "app.agents.context_optimizer.compress_session_state",
            new_callable=AsyncMock,
            return_value=compressed_result,
        ):
            result = await optimize_context_window(
                history=history,
                model_name="gemini-2.5-flash",
                max_context_tokens=20_000,
            )

        # Compression should have been triggered
        assert result["new_compressed_state"] is not None
        assert result["new_compressed_state"]["logos"] == ["Compressed fact"]

    @pytest.mark.anyio
    async def test_existing_compressed_state_injected(self):
        """Existing compressed state is injected as synthetic message pair."""
        compressed_state = {
            "logos": ["Existing fact"],
            "pathos": ["Existing tone"],
            "abstract": [],
            "conversation_summary": "Previous context.",
        }

        history = [
            {"role": "user", "content": "Follow-up question"},
            {"role": "assistant", "content": "Follow-up answer"},
            {"role": "user", "content": "Another question"},
        ]

        result = await optimize_context_window(
            history=history,
            model_name="gemini-2.5-flash",
            max_context_tokens=100_000,
            compressed_state=compressed_state,
            compressed_at_message_id="some-uuid",
        )

        # Should have synthetic pair + 3 original messages = 5 messages
        assert len(result["history"]) == 5

        # First message should be the synthetic user message with session_state
        first_msg = result["history"][0]
        assert isinstance(first_msg, ModelRequest)
        first_content = first_msg.parts[0].content
        assert "<session_state>" in first_content
        assert "Existing fact" in first_content

        # Second message should be synthetic assistant "Understood."
        second_msg = result["history"][1]
        assert isinstance(second_msg, ModelResponse)
        assert second_msg.parts[0].content == "Understood."

        # No new compression should be triggered (under threshold)
        assert result["new_compressed_state"] is None

    @pytest.mark.anyio
    async def test_compression_failure_falls_back_to_fifo(self):
        """When compression fails, FIFO truncation is used as fallback."""
        large_content = "x" * 4000  # ~1000 tokens each
        history = [
            {"role": "user", "content": large_content},
            {"role": "assistant", "content": large_content},
            {"role": "user", "content": large_content},
            {"role": "assistant", "content": large_content},
            {"role": "user", "content": large_content},
            {"role": "assistant", "content": large_content},
            {"role": "user", "content": "Current question"},
        ]

        # Make compress_session_state return None (failure)
        with patch(
            "app.agents.context_optimizer.compress_session_state",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await optimize_context_window(
                history=history,
                model_name="gemini-2.5-flash",
                max_context_tokens=20_000,
            )

        # Should still return a valid result (FIFO fallback)
        assert result["new_compressed_state"] is None
        assert len(result["history"]) > 0
        # Last message should be the current question
        last_msg = result["history"][-1]
        assert last_msg.parts[0].content == "Current question"

    @pytest.mark.anyio
    async def test_optimized_context_has_all_fields(self):
        """OptimizedContext includes all required fields including new compression fields."""
        result = await optimize_context_window(
            history=[{"role": "user", "content": "test"}],
            model_name="gemini-2.5-flash",
        )

        # Verify all TypedDict fields are present
        assert "history" in result
        assert "cached_prompt_name" in result
        assert "system_prompt" in result
        assert "skip_tool_registration" in result
        assert "new_compressed_state" in result
        assert "new_compressed_at_message_id" in result


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestFifoTrim:
    """Test the _fifo_trim helper function."""

    def test_fifo_trim_all_fit(self):
        """All messages fit within budget."""
        messages = [
            {"role": "user", "content": "short"},
            {"role": "assistant", "content": "short"},
        ]
        tokens = [2, 2]
        kept, total = _fifo_trim(messages, tokens, budget=100)
        assert len(kept) == 2
        assert total == 4

    def test_fifo_trim_drops_oldest(self):
        """Oldest messages are dropped when budget is exceeded."""
        messages = [
            {"role": "user", "content": "old message"},
            {"role": "assistant", "content": "old reply"},
            {"role": "user", "content": "recent message"},
            {"role": "assistant", "content": "recent reply"},
        ]
        tokens = [100, 100, 100, 100]
        kept, total = _fifo_trim(messages, tokens, budget=250)
        # Should keep the 2 newest messages
        assert len(kept) == 2
        assert kept[0]["content"] == "recent message"
        assert kept[1]["content"] == "recent reply"
        assert total == 200

    def test_fifo_trim_empty(self):
        """Empty messages returns empty result."""
        kept, total = _fifo_trim([], [], budget=100)
        assert kept == []
        assert total == 0


class TestEstimateTokens:
    """Test the _estimate_tokens helper."""

    def test_estimate_tokens_basic(self):
        """Token estimation uses char/4 heuristic."""
        assert _estimate_tokens("1234") == 1
        assert _estimate_tokens("12345678") == 2
        assert _estimate_tokens("") == 0

    def test_estimate_tokens_long_text(self):
        """Longer texts produce proportional estimates."""
        text = "a" * 4000
        assert _estimate_tokens(text) == 1000

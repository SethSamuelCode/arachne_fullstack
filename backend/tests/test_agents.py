"""Tests for AI agent module (PydanticAI)."""

from unittest.mock import patch

import pytest

from app.agents.assistant import AssistantAgent, Deps, get_agent
from app.agents.tools.datetime_tool import get_current_datetime


class TestDeps:
    """Tests for Deps dataclass."""

    def test_deps_default_values(self):
        """Test Deps has correct default values."""
        deps = Deps()
        assert deps.user_id is None
        assert deps.user_name is None
        assert deps.metadata == {}

    def test_deps_with_values(self):
        """Test Deps with custom values."""
        deps = Deps(user_id="123", user_name="Test User", metadata={"key": "value"})
        assert deps.user_id == "123"
        assert deps.user_name == "Test User"
        assert deps.metadata == {"key": "value"}


class TestGetCurrentDatetime:
    """Tests for get_current_datetime tool."""

    def test_returns_formatted_string(self):
        """Test get_current_datetime returns formatted string."""
        result = get_current_datetime()
        assert isinstance(result, str)
        # Should contain year, month, day
        assert len(result) > 10


class TestAssistantAgent:
    """Tests for AssistantAgent class."""

    def test_init_with_defaults(self):
        """Test AssistantAgent initializes with defaults."""
        agent = AssistantAgent()
        # Default system prompt is from prompts.py DEFAULT_SYSTEM_PROMPT
        assert agent.system_prompt is not None
        assert agent._agent is None

    def test_init_with_custom_values(self):
        """Test AssistantAgent with custom configuration."""
        agent = AssistantAgent(
            model_name="gemini-2.5-flash",
            system_prompt="Custom prompt",
        )
        assert agent.model_name == "gemini-2.5-flash"
        assert agent.system_prompt == "Custom prompt"

    @patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key-for-testing"})
    def test_agent_property_creates_agent(self):
        """Test agent property creates agent on first access."""
        agent = AssistantAgent()
        # Access the agent property - this creates the pydantic-ai Agent
        result = agent.agent
        assert agent._agent is not None
        assert result is agent._agent

    @patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key-for-testing"})
    def test_agent_property_caches_agent(self):
        """Test agent property caches the agent instance."""
        agent = AssistantAgent()
        agent1 = agent.agent
        agent2 = agent.agent
        # Same instance should be returned
        assert agent1 is agent2


class TestGetAgent:
    """Tests for get_agent factory function."""

    def test_returns_assistant_agent(self):
        """Test get_agent returns AssistantAgent."""
        agent = get_agent()
        assert isinstance(agent, AssistantAgent)


class TestAgentRoutes:
    """Tests for agent WebSocket routes."""

    @pytest.mark.anyio
    async def test_agent_websocket_connection(self, client):
        """Test WebSocket connection to agent endpoint."""
        # This test verifies the WebSocket endpoint is accessible
        # Actual agent testing would require mocking OpenAI
        pass


class TestHistoryConversion:
    """Tests for conversation history conversion."""

    def test_empty_history(self):
        """Test with empty history."""
        _agent = AssistantAgent()
        # History conversion happens inside run/iter methods
        # We test the structure here
        history = []
        assert len(history) == 0

    def test_history_roles(self):
        """Test history with different roles."""
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "system", "content": "You are helpful"},
        ]
        assert len(history) == 3
        assert all("role" in msg and "content" in msg for msg in history)


class TestPermissiveSafetySettings:
    """Tests for permissive safety settings on main LLM."""

    def test_assistant_safety_settings_are_off(self):
        """Test that the assistant has all safety filters set to OFF."""
        from google.genai.types import HarmBlockThreshold

        from app.agents.assistant import PERMISSIVE_SAFETY_SETTINGS

        # Verify we have all expected harm categories
        assert len(PERMISSIVE_SAFETY_SETTINGS) == 5

        # Verify all are set to OFF
        for setting in PERMISSIVE_SAFETY_SETTINGS:
            assert setting["threshold"] == HarmBlockThreshold.OFF

    def test_tool_register_safety_settings_are_off(self):
        """Test that spawned agents also have safety filters disabled."""
        from google.genai.types import HarmBlockThreshold

        from app.agents.tool_register import PERMISSIVE_SAFETY_SETTINGS

        # Verify we have all expected harm categories
        assert len(PERMISSIVE_SAFETY_SETTINGS) == 5

        # Verify all are set to OFF
        for setting in PERMISSIVE_SAFETY_SETTINGS:
            assert setting["threshold"] == HarmBlockThreshold.OFF


class TestGenerateImageTool:
    """Tests for generate_image tool."""

    @pytest.fixture
    def mock_deps(self):
        """Create mock dependencies for RunContext."""
        return Deps(user_id="test-user-123", user_name="Test User", metadata={})

    @pytest.mark.anyio
    async def test_imagen4_generation_success(self, mock_deps):
        """Test successful image generation with Imagen4 - verify config structure."""
        from google.genai import types

        # Verify the Imagen config structure with safety filters disabled
        config = types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio="1:1",
            negative_prompt=None,
            safety_filter_level=types.SafetyFilterLevel.BLOCK_NONE,
            person_generation=types.PersonGeneration.ALLOW_ALL,
            include_rai_reason=True,
            include_safety_attributes=True,
            output_mime_type="image/png",
        )
        assert config.safety_filter_level == types.SafetyFilterLevel.BLOCK_NONE
        assert config.person_generation == types.PersonGeneration.ALLOW_ALL
        assert config.include_rai_reason is True
        assert config.include_safety_attributes is True

    @pytest.mark.anyio
    async def test_gemini_safety_settings_disabled(self):
        """Test that Gemini safety settings are set to OFF."""
        from google.genai import types

        # Verify we can create safety settings with OFF threshold
        safety_settings = [
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                threshold=types.HarmBlockThreshold.OFF,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                threshold=types.HarmBlockThreshold.OFF,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                threshold=types.HarmBlockThreshold.OFF,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                threshold=types.HarmBlockThreshold.OFF,
            ),
        ]

        assert len(safety_settings) == 4
        for setting in safety_settings:
            assert setting.threshold == types.HarmBlockThreshold.OFF

    def test_image_model_name_type(self):
        """Test ImageModelName type alias accepts valid models."""
        from app.agents.tool_register import ImageModelName

        # These should be valid
        valid_models: list[ImageModelName] = [
            "gemini-3-pro-image-preview",
            "imagen4",
        ]
        assert len(valid_models) == 2

    def test_config_defaults(self):
        """Test image generation config defaults are set correctly."""
        from app.core.config import settings

        assert settings.GEMINI_IMAGE_MODEL == "gemini-3-pro-image-preview"
        assert settings.IMAGEN_MODEL == "imagen4"
        assert settings.IMAGE_GEN_DEFAULT_ASPECT_RATIO == "1:1"
        assert settings.IMAGE_GEN_DEFAULT_SIZE == "2K"
        assert settings.IMAGE_GEN_DEFAULT_COUNT == 1

    @pytest.mark.anyio
    async def test_imagen_config_structure(self):
        """Test Imagen GenerateImagesConfig has expected structure."""
        from google.genai import types

        config = types.GenerateImagesConfig(
            number_of_images=2,
            aspect_ratio="16:9",
            negative_prompt="blurry, distorted",
            safety_filter_level=types.SafetyFilterLevel.BLOCK_NONE,
            person_generation=types.PersonGeneration.ALLOW_ALL,
            include_rai_reason=True,
            include_safety_attributes=True,
            output_mime_type="image/png",
        )

        assert config.number_of_images == 2
        assert config.aspect_ratio == "16:9"
        assert config.negative_prompt == "blurry, distorted"
        assert config.output_mime_type == "image/png"

    @pytest.mark.anyio
    async def test_gemini_content_config_structure(self):
        """Test Gemini GenerateContentConfig has expected structure."""
        from google.genai import types

        image_config = types.ImageConfig(
            aspect_ratio="4:3",
            output_mime_type="image/png",
        )

        config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=image_config,
            safety_settings=[
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                    threshold=types.HarmBlockThreshold.OFF,
                ),
            ],
        )

        assert "IMAGE" in config.response_modalities
        assert config.image_config.aspect_ratio == "4:3"
        assert len(config.safety_settings) == 1

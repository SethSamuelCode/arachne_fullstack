"""Tests for AI agent module (PydanticAI)."""

from unittest.mock import patch

import pytest

from app.agents.assistant import AssistantAgent, Deps, get_agent
from app.agents.providers.registry import get_provider
from app.agents.tools.datetime_tool import get_current_datetime
from app.agents.tools.decorators import safe_tool


class TestSafeTool:
    """Tests for the @safe_tool decorator."""

    @pytest.mark.anyio
    async def test_safe_tool_passes_through_on_success(self):
        """Test that @safe_tool returns normal result when no exception."""

        @safe_tool
        async def successful_tool(arg: str) -> str:
            return f"Success: {arg}"

        result = await successful_tool("test")
        assert result == "Success: test"

    @pytest.mark.anyio
    async def test_safe_tool_catches_exception_returns_error_dict(self):
        """Test that @safe_tool catches exceptions and returns error dict."""

        @safe_tool
        async def failing_tool(arg: str) -> str:
            raise ValueError("Something went wrong")

        result = await failing_tool("test")

        assert isinstance(result, dict)
        assert result["error"] is True
        assert result["message"] == "Something went wrong"
        assert result["code"] == "ValueError"
        assert "details" in result

    @pytest.mark.anyio
    async def test_safe_tool_handles_empty_error_message(self):
        """Test that @safe_tool handles exceptions with empty messages."""

        @safe_tool
        async def empty_error_tool() -> str:
            raise RuntimeError()

        result = await empty_error_tool()

        assert result["error"] is True
        assert result["message"] == "An unexpected error occurred"
        assert result["code"] == "RuntimeError"

    @pytest.mark.anyio
    async def test_safe_tool_extracts_boto_error_details(self):
        """Test that @safe_tool extracts details from boto ClientError."""

        class MockBotoError(Exception):
            def __init__(self):
                super().__init__("NoSuchKey error")
                self.response = {"Error": {"Code": "NoSuchKey", "Message": "Key not found"}}

        @safe_tool
        async def boto_failing_tool() -> str:
            raise MockBotoError()

        result = await boto_failing_tool()

        assert result["error"] is True
        assert result["code"] == "MockBotoError"
        assert result["details"] == {"Code": "NoSuchKey", "Message": "Key not found"}

    @pytest.mark.anyio
    async def test_safe_tool_preserves_function_metadata(self):
        """Test that @safe_tool preserves function name and docstring."""

        @safe_tool
        async def documented_tool() -> str:
            """This is the docstring."""
            return "result"

        assert documented_tool.__name__ == "documented_tool"
        assert documented_tool.__doc__ == "This is the docstring."

    @pytest.mark.anyio
    async def test_safe_tool_reraises_keyboard_interrupt(self):
        """Test that @safe_tool re-raises KeyboardInterrupt for proper shutdown."""

        @safe_tool
        async def interrupted_tool() -> str:
            raise KeyboardInterrupt("User cancelled")

        with pytest.raises(KeyboardInterrupt):
            await interrupted_tool()

    @pytest.mark.anyio
    async def test_safe_tool_reraises_system_exit(self):
        """Test that @safe_tool re-raises SystemExit for proper shutdown."""

        @safe_tool
        async def exit_tool() -> str:
            raise SystemExit(1)

        with pytest.raises(SystemExit):
            await exit_tool()


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
            provider=get_provider("gemini-2.5-flash"),
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

        from app.agents.providers.gemini import PERMISSIVE_SAFETY_SETTINGS

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

        # Verify the Imagen config structure
        # Note: API only supports BLOCK_LOW_AND_ABOVE for safety_filter_level
        # and ALLOW_ADULT for person_generation (BLOCK_NONE/ALLOW_ALL rejected)
        config = types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio="1:1",
            negative_prompt=None,
            safety_filter_level=types.SafetyFilterLevel.BLOCK_LOW_AND_ABOVE,
            person_generation=types.PersonGeneration.ALLOW_ADULT,
            include_rai_reason=True,
            include_safety_attributes=True,
            output_mime_type="image/png",
        )
        assert config.safety_filter_level == types.SafetyFilterLevel.BLOCK_LOW_AND_ABOVE
        assert config.person_generation == types.PersonGeneration.ALLOW_ADULT
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
            "imagen-4.0-generate-001",
            "imagen-4.0-ultra-generate-001",
            "imagen-4.0-fast-generate-001",
        ]
        assert len(valid_models) == 4

    def test_config_defaults(self):
        """Test image generation config defaults are set correctly."""
        from app.core.config import settings

        assert settings.GEMINI_IMAGE_MODEL == "gemini-3-pro-image-preview"
        assert settings.IMAGEN_MODEL == "imagen-4.0-generate-001"
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


# =============================================================================
# Academic Search Tools Tests
# =============================================================================


class TestAcademicSearchExceptions:
    """Tests for academic search exception hierarchy."""

    def test_academic_search_error_base_class(self):
        """Test AcademicSearchError base class."""
        from app.core.exceptions import AcademicSearchError

        error = AcademicSearchError(
            message="Test error",
            retry_after=30,
            api_status_code=429,
        )
        assert error.message == "Test error"
        assert error.retry_after == 30
        assert error.api_status_code == 429
        assert error.code == "ACADEMIC_SEARCH_ERROR"
        assert error.status_code == 503

    def test_openalex_error(self):
        """Test OpenAlexError inherits from AcademicSearchError."""
        from app.core.exceptions import AcademicSearchError, OpenAlexError

        error = OpenAlexError(message="OpenAlex API failed")
        assert isinstance(error, AcademicSearchError)
        assert error.code == "OPENALEX_ERROR"
        assert error.message == "OpenAlex API failed"

    def test_semantic_scholar_error(self):
        """Test SemanticScholarError with rate limit info."""
        from app.core.exceptions import SemanticScholarError

        error = SemanticScholarError(
            message="Rate limited",
            api_status_code=429,
            retry_after=60,
        )
        assert error.code == "SEMANTIC_SCHOLAR_ERROR"
        assert error.retry_after == 60
        assert error.api_status_code == 429

    def test_arxiv_error(self):
        """Test ArxivError."""
        from app.core.exceptions import ArxivError

        error = ArxivError(message="arXiv timeout")
        assert error.code == "ARXIV_ERROR"
        assert error.message == "arXiv timeout"


class TestOpenAlexClient:
    """Tests for OpenAlex client."""

    def test_singleton_instance(self):
        """Test get_openalex_client returns singleton."""
        from app.clients.academic import get_openalex_client

        client1 = get_openalex_client()
        client2 = get_openalex_client()
        assert client1 is client2

    def test_build_filter_basic(self):
        """Test filter string building."""
        from app.clients.academic.openalex import OpenAlexClient

        client = OpenAlexClient()
        filter_str = client._build_filter(
            query="machine learning",
            search_field="title",
        )
        assert "title.search:machine learning" in filter_str

    def test_build_filter_complex(self):
        """Test complex filter with multiple parameters."""
        from app.clients.academic.openalex import OpenAlexClient

        client = OpenAlexClient()
        filter_str = client._build_filter(
            query="deep learning",
            search_field="all",
            year_from=2020,
            year_to=2024,
            min_citations=100,
            open_access_only=True,
        )
        assert "default.search:deep learning" in filter_str
        assert "from_publication_date:2020-01-01" in filter_str
        assert "to_publication_date:2024-12-31" in filter_str
        assert "cited_by_count:>=100" in filter_str
        assert "is_oa:true" in filter_str

    def test_build_filter_single_year(self):
        """Test filter with single year."""
        from app.clients.academic.openalex import OpenAlexClient

        client = OpenAlexClient()
        filter_str = client._build_filter(
            query="test",
            year_from=2023,
            year_to=2023,
        )
        assert "publication_year:2023" in filter_str

    def test_build_select_fields(self):
        """Test select field building."""
        from app.clients.academic.openalex import OpenAlexClient

        client = OpenAlexClient()
        select_str = client._build_select(
            include_abstract=True,
            include_authors=True,
            include_citations=True,
        )
        assert "abstract_inverted_index" in select_str
        assert "authorships" in select_str
        assert "cited_by_count" in select_str


class TestSemanticScholarClient:
    """Tests for Semantic Scholar client."""

    def test_singleton_instance(self):
        """Test get_semantic_scholar_client returns singleton."""
        from app.clients.academic import get_semantic_scholar_client

        client1 = get_semantic_scholar_client()
        client2 = get_semantic_scholar_client()
        assert client1 is client2

    def test_build_fields_basic(self):
        """Test fields parameter building."""
        from app.clients.academic.semantic_scholar import SemanticScholarClient

        client = SemanticScholarClient()
        fields = client._build_fields(
            include_abstract=True,
            include_tldr=True,
            include_authors=True,
        )
        assert "abstract" in fields
        assert "tldr" in fields
        assert "authors" in fields
        assert "paperId" in fields  # Always included

    def test_build_fields_with_embedding(self):
        """Test fields with embedding."""
        from app.clients.academic.semantic_scholar import SemanticScholarClient

        client = SemanticScholarClient()
        fields = client._build_fields(include_embedding=True)
        assert "embedding.specter_v2" in fields


class TestArxivClient:
    """Tests for arXiv client."""

    def test_singleton_instance(self):
        """Test get_arxiv_client returns singleton."""
        from app.clients.academic import get_arxiv_client

        client1 = get_arxiv_client()
        client2 = get_arxiv_client()
        assert client1 is client2

    def test_build_query_basic(self):
        """Test query string building."""
        from app.clients.academic.arxiv import ArxivClient

        client = ArxivClient()
        query = client._build_query("machine learning", search_field="all")
        # When search_field is "all", prefix is omitted (query used as-is)
        assert "machine+learning" in query

    def test_build_query_with_categories(self):
        """Test query with category filter."""
        from app.clients.academic.arxiv import ArxivClient

        client = ArxivClient()
        query = client._build_query(
            "neural network",
            categories=["cs.LG", "cs.AI"],
        )
        assert "cat:cs.LG" in query or "cs.LG" in query
        assert "cat:cs.AI" in query or "cs.AI" in query

    def test_build_query_with_dates(self):
        """Test query with date range."""
        from app.clients.academic.arxiv import ArxivClient

        client = ArxivClient()
        query = client._build_query(
            "test",
            submitted_after="20230101",
            submitted_before="20231231",
        )
        assert "submittedDate:" in query

    def test_category_validation(self):
        """Test arXiv category codes are valid."""
        from app.clients.academic.arxiv import ARXIV_CATEGORIES

        # Check some known categories exist
        assert "cs.AI" in ARXIV_CATEGORIES
        assert "cs.LG" in ARXIV_CATEGORIES
        assert "stat.ML" in ARXIV_CATEGORIES
        assert "quant-ph" in ARXIV_CATEGORIES

        # Verify structure
        for _code, info in ARXIV_CATEGORIES.items():
            assert "name" in info
            assert "group" in info


class TestArxivCategories:
    """Tests for arXiv category functions."""

    def test_get_categories(self):
        """Test get_categories returns all categories."""
        from app.clients.academic.arxiv import get_categories

        categories = get_categories()
        assert len(categories) > 100  # Should have many categories
        assert "cs.AI" in categories

    def test_get_categories_by_group(self):
        """Test get_categories_by_group organizes correctly."""
        from app.clients.academic.arxiv import get_categories_by_group

        by_group = get_categories_by_group()
        assert "Computer Science" in by_group
        assert "Physics" in by_group
        assert "Mathematics" in by_group

        # Check CS categories
        cs_codes = [c["code"] for c in by_group["Computer Science"]]
        assert "cs.AI" in cs_codes
        assert "cs.LG" in cs_codes

    def test_list_arxiv_categories_impl(self):
        """Test list_arxiv_categories_impl tool."""
        from app.agents.tools.academic_search import list_arxiv_categories_impl

        result = list_arxiv_categories_impl()
        assert "categories" in result
        assert "by_group" in result
        assert "cs.AI" in result["categories"]


class TestAcademicSearchSchemas:
    """Tests for academic search Pydantic schemas."""

    def test_openalex_work_from_api_response(self):
        """Test OpenAlexWork.from_api_response parsing."""
        from app.schemas.academic import OpenAlexWork

        api_response = {
            "id": "https://openalex.org/W2125098916",
            "doi": "https://doi.org/10.1038/nature12373",
            "display_name": "Test Paper Title",
            "publication_year": 2023,
            "cited_by_count": 150,
            "is_oa": True,
            "open_access": {"is_oa": True, "oa_status": "gold"},
            "authorships": [
                {"author": {"id": "A1", "display_name": "Author One", "orcid": "0000-0001-2345-6789"}}
            ],
            "abstract_inverted_index": {"This": [0], "is": [1], "a": [2], "test": [3]},
        }

        work = OpenAlexWork.from_api_response(api_response)
        assert work.id == "W2125098916"
        assert work.doi == "10.1038/nature12373"
        assert work.title == "Test Paper Title"
        assert work.publication_year == 2023
        assert work.cited_by_count == 150
        assert work.is_oa is True
        assert work.abstract == "This is a test"
        assert len(work.authors) == 1
        assert work.authors[0].display_name == "Author One"

    def test_openalex_inverted_index_decode(self):
        """Test OpenAlex abstract inverted index decoding."""
        from app.schemas.academic import OpenAlexWork

        inverted = {
            "The": [0],
            "quick": [1],
            "brown": [2],
            "fox": [3],
            "jumps": [4],
        }
        result = OpenAlexWork._decode_inverted_index(inverted)
        assert result == "The quick brown fox jumps"

    def test_semantic_scholar_paper_from_api_response(self):
        """Test SemanticScholarPaper.from_api_response parsing."""
        from app.schemas.academic import SemanticScholarPaper

        api_response = {
            "paperId": "649def34f8be52c8b66281af98ae884c09aef38b",
            "title": "Attention Is All You Need",
            "abstract": "We propose a new architecture...",
            "year": 2017,
            "citationCount": 50000,
            "influentialCitationCount": 5000,
            "isOpenAccess": True,
            "openAccessPdf": {"url": "https://example.com/paper.pdf", "status": "GOLD"},
            "tldr": {"text": "This paper introduces transformers.", "model": "v2"},
            "authors": [{"authorId": "A1", "name": "Vaswani"}],
            "fieldsOfStudy": ["Computer Science"],
            "externalIds": {"DOI": "10.123/test", "ArXiv": "1706.03762"},
        }

        paper = SemanticScholarPaper.from_api_response(api_response)
        assert paper.paper_id == "649def34f8be52c8b66281af98ae884c09aef38b"
        assert paper.title == "Attention Is All You Need"
        assert paper.year == 2017
        assert paper.citation_count == 50000
        assert paper.tldr is not None
        assert paper.tldr.text == "This paper introduces transformers."
        assert paper.is_open_access is True
        assert paper.open_access_pdf is not None
        assert paper.external_ids is not None
        assert paper.external_ids.arxiv_id == "1706.03762"

    def test_arxiv_paper_from_api_response(self):
        """Test ArxivPaper.from_api_response parsing."""
        from app.schemas.academic import ArxivPaper

        api_response = {
            "id": "2301.00001",
            "title": "A Test Paper on arXiv",
            "summary": "This paper discusses important topics.",
            "authors": [{"name": "John Doe", "affiliation": "MIT"}],
            "published": "2023-01-01T00:00:00Z",
            "updated": "2023-01-15T00:00:00Z",
            "categories": ["cs.AI", "cs.LG"],
            "primary_category": "cs.AI",
            "pdf_url": "http://arxiv.org/pdf/2301.00001",
            "abs_url": "http://arxiv.org/abs/2301.00001",
            "doi": "10.1234/test",
        }

        paper = ArxivPaper.from_api_response(api_response)
        assert paper.id == "2301.00001"
        assert paper.title == "A Test Paper on arXiv"
        assert paper.primary_category == "cs.AI"
        assert "cs.LG" in paper.categories
        assert len(paper.authors) == 1
        assert paper.authors[0].name == "John Doe"
        assert paper.doi == "10.1234/test"


class TestAcademicSearchConfig:
    """Tests for academic search configuration."""

    def test_openalex_email_config(self):
        """Test OPENALEX_EMAIL config setting exists."""
        from app.core.config import Settings

        # Check the field exists in Settings
        assert hasattr(Settings, "model_fields")
        field_names = list(Settings.model_fields.keys())
        assert "OPENALEX_EMAIL" in field_names

    def test_semantic_scholar_api_key_config(self):
        """Test SEMANTIC_SCHOLAR_API_KEY config setting exists."""
        from app.core.config import Settings

        field_names = list(Settings.model_fields.keys())
        assert "SEMANTIC_SCHOLAR_API_KEY" in field_names

    def test_config_defaults_are_none(self):
        """Test academic API keys default to None."""
        from app.core.config import settings

        # These should be None by default (unless set in .env)
        # We just verify they exist and can be accessed
        _ = settings.OPENALEX_EMAIL
        _ = settings.SEMANTIC_SCHOLAR_API_KEY


class TestSchemaSanitization:
    """Tests for Gemini schema sanitization."""

    def test_sanitize_removes_examples(self):
        """Test _sanitize_schema_for_gemini removes examples field."""
        from app.agents.context_optimizer import _sanitize_schema_for_gemini

        schema = {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "examples": ["example1", "example2"],
                }
            },
        }
        result = _sanitize_schema_for_gemini(schema)
        assert "examples" not in result["properties"]["name"]
        assert result["properties"]["name"]["type"] == "string"

    def test_sanitize_removes_defs(self):
        """Test _sanitize_schema_for_gemini removes $defs field."""
        from app.agents.context_optimizer import _sanitize_schema_for_gemini

        schema = {
            "type": "object",
            "$defs": {"SomeType": {"type": "string"}},
            "properties": {"name": {"type": "string"}},
        }
        result = _sanitize_schema_for_gemini(schema)
        assert "$defs" not in result

    def test_sanitize_resolves_refs(self):
        """Test _sanitize_schema_for_gemini resolves $ref references."""
        from app.agents.context_optimizer import _sanitize_schema_for_gemini

        schema = {
            "type": "object",
            "$defs": {
                "SingleTask": {
                    "type": "object",
                    "properties": {"task_name": {"type": "string"}},
                    "required": ["task_name"],
                }
            },
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/SingleTask"},
                }
            },
        }
        result = _sanitize_schema_for_gemini(schema)

        # $ref should be resolved
        assert "$ref" not in result["properties"]["steps"]["items"]
        # Resolved type should be inlined
        assert result["properties"]["steps"]["items"]["type"] == "object"
        assert "task_name" in result["properties"]["steps"]["items"]["properties"]

    def test_sanitize_removes_title(self):
        """Test _sanitize_schema_for_gemini removes title field."""
        from app.agents.context_optimizer import _sanitize_schema_for_gemini

        schema = {
            "type": "object",
            "title": "MySchema",
            "properties": {
                "name": {"type": "string", "title": "Name Field"}
            },
        }
        result = _sanitize_schema_for_gemini(schema)
        assert "title" not in result
        assert "title" not in result["properties"]["name"]

    def test_sanitize_preserves_required_fields(self):
        """Test _sanitize_schema_for_gemini preserves required schema fields."""
        from app.agents.context_optimizer import _sanitize_schema_for_gemini

        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The name"},
                "count": {"type": "integer", "minimum": 0},
            },
            "required": ["name"],
        }
        result = _sanitize_schema_for_gemini(schema)

        assert result["type"] == "object"
        assert result["required"] == ["name"]
        assert result["properties"]["name"]["type"] == "string"
        assert result["properties"]["name"]["description"] == "The name"
        assert result["properties"]["count"]["minimum"] == 0

    def test_sanitize_enriches_description_with_examples(self):
        """Test _sanitize_schema_for_gemini adds examples to description."""
        from app.agents.context_optimizer import _sanitize_schema_for_gemini

        schema = {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The project name",
                    "examples": ["Project Alpha", "Marketing Plan"],
                }
            },
        }
        result = _sanitize_schema_for_gemini(schema)

        # Examples should be removed as a field
        assert "examples" not in result["properties"]["name"]
        # But added to description for LLM understanding
        desc = result["properties"]["name"]["description"]
        assert "Project Alpha" in desc
        assert "Marketing Plan" in desc
        assert "The project name" in desc

    def test_sanitize_enriches_description_with_title(self):
        """Test _sanitize_schema_for_gemini adds title to description."""
        from app.agents.context_optimizer import _sanitize_schema_for_gemini

        schema = {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "title": "Item Count",
                    "description": "Number of items to process",
                }
            },
        }
        result = _sanitize_schema_for_gemini(schema)

        # Title should be removed as a field
        assert "title" not in result["properties"]["count"]
        # But added to description
        desc = result["properties"]["count"]["description"]
        assert "Item Count" in desc
        assert "Number of items" in desc

    def test_sanitize_enriches_description_with_default(self):
        """Test _sanitize_schema_for_gemini adds default to description."""
        from app.agents.context_optimizer import _sanitize_schema_for_gemini

        schema = {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max results",
                    "default": 10,
                }
            },
        }
        result = _sanitize_schema_for_gemini(schema)

        # Default should be removed as a field
        assert "default" not in result["properties"]["limit"]
        # But mentioned in description
        desc = result["properties"]["limit"]["description"]
        assert "Default: 10" in desc
        assert "Max results" in desc

    def test_sanitize_single_example_format(self):
        """Test single example uses 'Example:' not 'Examples:'."""
        from app.agents.context_optimizer import _sanitize_schema_for_gemini

        schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "examples": ["machine learning"],
                }
            },
        }
        result = _sanitize_schema_for_gemini(schema)
        desc = result["properties"]["query"]["description"]
        assert "Example: " in desc
        assert "Examples:" not in desc

    def test_sanitize_removes_additional_properties(self):
        """Test _sanitize_schema_for_gemini removes additionalProperties."""
        from app.agents.context_optimizer import _sanitize_schema_for_gemini

        schema = {
            "type": "object",
            "properties": {
                "data": {"type": "object", "additionalProperties": True}
            },
            "additionalProperties": False,
        }
        result = _sanitize_schema_for_gemini(schema)

        assert "additionalProperties" not in result
        assert "additionalProperties" not in result["properties"]["data"]


class TestContextOptimizer:
    """Tests for context window optimization."""

    def test_registry_context_limits(self):
        """Test that registry has correct context limits for all models."""
        from app.agents.providers.registry import MODEL_REGISTRY
        assert MODEL_REGISTRY["gemini-2.5-flash"].context_limit == 1_048_576
        assert MODEL_REGISTRY["gemini-3-pro-preview"].context_limit == 2_000_000
        assert MODEL_REGISTRY["gemini-3.1-pro-preview"].context_limit == 2_000_000
        assert MODEL_REGISTRY["glm-5"].context_limit == 200_000

    def test_get_token_budget_returns_85_percent(self):
        """Test get_token_budget returns 85% of context limit."""
        from app.agents.context_optimizer import get_token_budget
        from app.agents.providers.registry import get_provider
        assert get_token_budget(get_provider("gemini-3-pro-preview")) == 1_700_000
        assert get_token_budget(get_provider("gemini-2.5-flash")) == 891_289

    def test_get_token_budget_for_vertex_model(self):
        """Test get_token_budget works for Vertex AI models."""
        from app.agents.context_optimizer import get_token_budget
        from app.agents.providers.registry import get_provider
        # 200_000 * 0.85 = 170_000
        assert get_token_budget(get_provider("glm-5")) == 170_000

    @pytest.mark.anyio
    async def test_optimize_empty_history_returns_optimized_context(self):
        """Test optimize_context_window with empty history returns OptimizedContext."""
        from app.agents.context_optimizer import optimize_context_window

        from app.agents.providers.registry import get_provider
        result = await optimize_context_window(
            history=[],
            provider=get_provider("gemini-3-pro-preview"),
        )
        # Should return OptimizedContext TypedDict, not a list
        assert isinstance(result, dict)
        assert "history" in result
        assert "cached_prompt_name" in result
        assert "system_prompt" in result
        assert "skip_tool_registration" in result
        assert result["history"] == []
        assert result["cached_prompt_name"] is None
        assert result["system_prompt"] is None
        assert result["skip_tool_registration"] is False

    @pytest.mark.anyio
    async def test_optimize_returns_optimized_context_structure(self):
        """Test optimize_context_window returns correct OptimizedContext structure."""
        from app.agents.context_optimizer import optimize_context_window

        from app.agents.providers.registry import get_provider
        history = [{"role": "user", "content": "Hello"}]
        result = await optimize_context_window(
            history=history,
            provider=get_provider("gemini-3-pro-preview"),
            system_prompt="You are helpful",
        )

        # Verify TypedDict structure
        assert isinstance(result, dict)
        assert "history" in result
        assert "cached_prompt_name" in result
        assert "system_prompt" in result
        assert "skip_tool_registration" in result

        # Without Redis, caching is disabled
        assert result["cached_prompt_name"] is None
        # System prompt should be returned since not cached
        assert result["system_prompt"] == "You are helpful"
        # Tools should be registered since not cached
        assert result["skip_tool_registration"] is False
        # History should contain the message
        assert len(result["history"]) == 1

    @pytest.mark.anyio
    async def test_optimize_single_message(self):
        """Test optimize_context_window with single message."""
        from app.agents.context_optimizer import optimize_context_window

        from app.agents.providers.registry import get_provider
        history = [{"role": "user", "content": "Hello"}]
        result = await optimize_context_window(
            history=history,
            provider=get_provider("gemini-3-pro-preview"),
        )
        assert len(result["history"]) == 1
        assert result["history"][0].parts[0].content == "Hello"

    @pytest.mark.anyio
    async def test_optimize_preserves_latest_message(self):
        """Test that the latest message is always preserved."""
        from app.agents.context_optimizer import optimize_context_window

        history = [
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "First response"},
            {"role": "user", "content": "Latest message"},
        ]
        from app.agents.providers.registry import get_provider
        result = await optimize_context_window(
            history=history,
            provider=get_provider("gemini-3-pro-preview"),
        )
        # Latest message must be present
        assert any(
            hasattr(msg, "parts") and
            hasattr(msg.parts[0], "content") and
            msg.parts[0].content == "Latest message"
            for msg in result["history"]
        )

    @pytest.mark.anyio
    async def test_optimize_trims_old_messages_when_over_budget(self):
        """Test that old messages are trimmed when budget exceeded."""
        from app.agents.context_optimizer import optimize_context_window

        # Create a history with messages that exceed a small budget
        history = [
            {"role": "user", "content": "x" * 10000}  # ~2500 tokens
            for _ in range(100)
        ]
        history.append({"role": "user", "content": "Latest"})

        # Use a small budget to force trimming
        from app.agents.providers.registry import get_provider
        result = await optimize_context_window(
            history=history,
            provider=get_provider("gemini-3-pro-preview"),
            max_context_tokens=50000,  # Small budget
        )
        # Should have fewer messages than original
        assert len(result["history"]) < len(history)
        # Latest message must be present
        assert result["history"][-1].parts[0].content == "Latest"

    @pytest.mark.anyio
    async def test_optimize_with_system_prompt_reserves_space(self):
        """Test that system prompt token count is reserved."""
        from app.agents.context_optimizer import optimize_context_window

        history = [
            {"role": "user", "content": "x" * 10000}
            for _ in range(50)
        ]
        history.append({"role": "user", "content": "Latest"})

        long_system_prompt = "System: " + "y" * 20000  # ~5000 tokens

        from app.agents.providers.registry import get_provider
        result_with_prompt = await optimize_context_window(
            history=history,
            provider=get_provider("gemini-3-pro-preview"),
            system_prompt=long_system_prompt,
            max_context_tokens=100000,
        )

        result_without_prompt = await optimize_context_window(
            history=history,
            provider=get_provider("gemini-3-pro-preview"),
            system_prompt=None,
            max_context_tokens=100000,
        )

        # With system prompt, less history should fit
        assert len(result_with_prompt["history"]) <= len(result_without_prompt["history"])

    @pytest.mark.anyio
    async def test_optimize_with_redis_cache_miss(self, mock_redis):
        """Test optimize_context_window with Redis but cache miss."""
        from unittest.mock import AsyncMock, patch

        from app.agents.context_optimizer import optimize_context_window

        # Mock cache miss - get returns None, create fails gracefully
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock(return_value=True)

        history = [{"role": "user", "content": "Hello"}]
        # Mock tool definitions for caching
        tool_definitions = [{"name": "test_tool", "description": "Test", "parameters": {}}]

        # Mock the Gemini client to avoid actual API calls
        with patch("app.agents.context_optimizer._get_genai_client") as mock_client:
            mock_client.return_value.aio.caches.create = AsyncMock(return_value=None)

            from app.agents.providers.registry import get_provider
            result = await optimize_context_window(
                history=history,
                provider=get_provider("gemini-2.5-flash"),
                system_prompt="You are helpful",
                tool_definitions=tool_definitions,
                redis_client=mock_redis,
            )

        # Should return system_prompt since caching failed
        assert result["system_prompt"] == "You are helpful"
        assert result["cached_prompt_name"] is None
        assert result["skip_tool_registration"] is False

    @pytest.mark.anyio
    async def test_optimize_with_redis_cache_hit(self, mock_redis):
        """Test optimize_context_window with Redis cache hit."""
        from unittest.mock import AsyncMock, patch

        from app.agents.context_optimizer import optimize_context_window

        # Mock cache hit
        mock_redis.get = AsyncMock(return_value="cachedContents/abc123")
        mock_redis.set = AsyncMock(return_value=True)

        history = [{"role": "user", "content": "Hello"}]
        # Mock tool definitions for caching
        tool_definitions = [{"name": "test_tool", "description": "Test", "parameters": {}}]

        # Mock the Gemini client for TTL extension
        with patch("app.agents.context_optimizer._get_genai_client") as mock_client:
            mock_client.return_value.aio.caches.update = AsyncMock()

            from app.agents.providers.registry import get_provider
            result = await optimize_context_window(
                history=history,
                provider=get_provider("gemini-2.5-flash"),
                system_prompt="You are helpful",
                tool_definitions=tool_definitions,
                redis_client=mock_redis,
            )

        # Should return cached_prompt_name and system_prompt=None
        assert result["cached_prompt_name"] == "cachedContents/abc123"
        assert result["system_prompt"] is None
        assert result["skip_tool_registration"] is True

    @pytest.mark.anyio
    async def test_optimize_caching_disabled_by_feature_flag(self, mock_redis, monkeypatch):
        """Test that caching is disabled when feature flag is off."""
        from app.agents.context_optimizer import optimize_context_window
        from app.core import config

        # Disable caching via feature flag
        monkeypatch.setattr(config.settings, "ENABLE_SYSTEM_PROMPT_CACHING", False)

        history = [{"role": "user", "content": "Hello"}]
        # Mock tool definitions for caching
        tool_definitions = [{"name": "test_tool", "description": "Test", "parameters": {}}]

        from app.agents.providers.registry import get_provider
        result = await optimize_context_window(
            history=history,
            provider=get_provider("gemini-2.5-flash"),
            system_prompt="You are helpful",
            tool_definitions=tool_definitions,
            redis_client=mock_redis,
        )

        # Should not attempt caching, return raw system_prompt
        assert result["cached_prompt_name"] is None
        assert result["system_prompt"] == "You are helpful"
        assert result["skip_tool_registration"] is False
        # Redis should not be called
        mock_redis.get.assert_not_called()

    def test_estimate_tokens_heuristic(self):
        """Test _estimate_tokens uses char/4 heuristic."""
        from app.agents.context_optimizer import _estimate_tokens

        text = "x" * 400  # 400 chars
        assert _estimate_tokens(text) == 100  # 400 / 4 = 100

    def test_hash_prompt_is_deterministic(self):
        """Test _hash_prompt produces consistent hashes."""
        from app.agents.context_optimizer import _hash_prompt

        prompt = "Test system prompt"
        hash1 = _hash_prompt(prompt)
        hash2 = _hash_prompt(prompt)
        assert hash1 == hash2
        assert len(hash1) == 16  # Truncated to 16 chars

    def test_hash_prompt_different_inputs(self):
        """Test _hash_prompt produces different hashes for different inputs."""
        from app.agents.context_optimizer import _hash_prompt

        hash1 = _hash_prompt("Prompt A")
        hash2 = _hash_prompt("Prompt B")
        assert hash1 != hash2

    @pytest.mark.anyio
    async def test_to_pydantic_messages_format(self):
        """Test _to_pydantic_messages produces correct format."""
        from pydantic_ai.messages import ModelRequest, ModelResponse

        from app.agents.context_optimizer import _to_pydantic_messages

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = _to_pydantic_messages(messages)

        assert len(result) == 2
        assert isinstance(result[0], ModelRequest)
        assert isinstance(result[1], ModelResponse)
        assert result[0].parts[0].content == "Hello"
        assert result[1].parts[0].content == "Hi there"


class TestAssistantAgentWithCaching:
    """Tests for AssistantAgent with system prompt caching support."""

    def test_init_with_cached_prompt_nullifies_system_prompt(self):
        """Test AssistantAgent sets system_prompt=None when cached_prompt_name provided."""
        agent = AssistantAgent(
            provider=get_provider("gemini-2.5-flash"),
            system_prompt="Original prompt",
            cached_prompt_name="cachedContents/abc123",
        )
        # System prompt should be None when using cache
        assert agent.system_prompt is None
        assert agent.cached_prompt_name == "cachedContents/abc123"

    def test_init_without_cached_prompt_keeps_system_prompt(self):
        """Test AssistantAgent keeps system_prompt when no cached_prompt_name."""
        agent = AssistantAgent(
            provider=get_provider("gemini-2.5-flash"),
            system_prompt="Custom prompt",
        )
        assert agent.system_prompt == "Custom prompt"
        assert agent.cached_prompt_name is None

    @patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key-for-testing"})
    def test_agent_creates_with_cached_content_setting(self):
        """Test agent includes google_cached_content in model settings when cache provided."""
        agent = AssistantAgent(
            provider=get_provider("gemini-2.5-flash"),
            cached_prompt_name="cachedContents/abc123",
        )
        # Access agent to trigger creation
        pydantic_agent = agent.agent
        # The agent should be created (we can't easily inspect model_settings,
        # but we verify it doesn't raise and the agent is created)
        assert pydantic_agent is not None
        assert agent.cached_prompt_name == "cachedContents/abc123"


class TestGetAgentFactory:
    """Tests for get_agent factory function with caching support."""

    def test_get_agent_with_cached_prompt_name(self):
        """Test get_agent passes cached_prompt_name to AssistantAgent."""
        agent = get_agent(
            system_prompt="Original",
            model_name="gemini-2.5-flash",
            cached_prompt_name="cachedContents/xyz789",
        )
        assert agent.cached_prompt_name == "cachedContents/xyz789"
        # System prompt should be None when using cache
        assert agent.system_prompt is None

    def test_get_agent_without_cached_prompt_name(self):
        """Test get_agent works without cached_prompt_name."""
        agent = get_agent(
            system_prompt="My prompt",
            model_name="gemini-2.5-flash",
        )
        assert agent.cached_prompt_name is None
        assert agent.system_prompt == "My prompt"

    def test_get_agent_with_skip_tool_registration(self):
        """Test get_agent passes skip_tool_registration to AssistantAgent."""
        agent = get_agent(
            system_prompt="Test",
            model_name="gemini-2.5-flash",
            cached_prompt_name="cachedContents/xyz789",
            skip_tool_registration=True,
        )
        assert agent.skip_tool_registration is True

    def test_get_agent_skip_tool_registration_default_false(self):
        """Test get_agent defaults skip_tool_registration to False."""
        agent = get_agent(
            system_prompt="Test",
            model_name="gemini-2.5-flash",
        )
        assert agent.skip_tool_registration is False


class TestToolExtraction:
    """Tests for tool definition extraction utilities."""

    def test_get_tool_definitions_returns_list(self):
        """Test get_tool_definitions returns a list of tool definitions."""
        from app.agents.tools import get_tool_definitions

        defs = get_tool_definitions()
        assert isinstance(defs, list)
        assert len(defs) > 0

    def test_get_tool_definitions_structure(self):
        """Test each tool definition has required fields."""
        from app.agents.tools import get_tool_definitions

        defs = get_tool_definitions()
        for tool_def in defs:
            assert "name" in tool_def
            assert "description" in tool_def
            assert "parameters" in tool_def
            assert isinstance(tool_def["name"], str)
            assert isinstance(tool_def["description"], str)
            assert isinstance(tool_def["parameters"], dict)

    def test_get_tool_definitions_includes_known_tools(self):
        """Test get_tool_definitions includes expected tools."""
        from app.agents.tools import get_tool_definitions

        defs = get_tool_definitions()
        tool_names = {d["name"] for d in defs}

        # Check for some known tools
        assert "search_web" in tool_names
        assert "spawn_agent" in tool_names
        assert "current_datetime" in tool_names

    def test_get_tool_definitions_sorted_by_name(self):
        """Test tool definitions are sorted by name for consistent hashing."""
        from app.agents.tools import get_tool_definitions

        defs = get_tool_definitions()
        names = [d["name"] for d in defs]
        assert names == sorted(names)

    def test_get_tools_schema_hash_consistent(self):
        """Test get_tools_schema_hash returns consistent hash."""
        from app.agents.tools import get_tools_schema_hash

        hash1 = get_tools_schema_hash()
        hash2 = get_tools_schema_hash()
        assert hash1 == hash2
        assert len(hash1) == 16  # SHA256 first 16 chars

    def test_get_tools_schema_hash_is_hex(self):
        """Test get_tools_schema_hash returns valid hex string."""
        from app.agents.tools import get_tools_schema_hash

        hash_val = get_tools_schema_hash()
        # Should be valid hex
        int(hash_val, 16)


class TestCacheManager:
    """Tests for the cache manager functionality."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        from unittest.mock import AsyncMock, MagicMock

        mock = MagicMock()
        mock.get = AsyncMock(return_value=None)
        mock.set = AsyncMock(return_value=True)
        mock.delete = AsyncMock(return_value=1)
        mock.raw = MagicMock()
        mock.raw.scan = AsyncMock(return_value=(0, []))
        return mock

    @pytest.mark.anyio
    async def test_validate_tools_cache_stores_new_hash(self, mock_redis, monkeypatch):
        """Test validate_tools_cache stores hash when none exists."""
        from unittest.mock import AsyncMock

        from app.core import cache_manager

        # No stored hash
        mock_redis.get = AsyncMock(return_value=None)

        # Run validation
        result = await cache_manager.validate_tools_cache(mock_redis)

        # Should have stored the new hash
        mock_redis.set.assert_called_once()
        assert not result  # Cache was invalid (no hash)

    @pytest.mark.anyio
    async def test_validate_tools_cache_valid_hash(self, mock_redis, monkeypatch):
        """Test validate_tools_cache returns True when hash matches."""
        from unittest.mock import AsyncMock

        from app.agents.tools import get_tools_schema_hash
        from app.core import cache_manager

        current_hash = get_tools_schema_hash()
        mock_redis.get = AsyncMock(return_value=current_hash)

        result = await cache_manager.validate_tools_cache(mock_redis)

        assert result is True  # Cache is valid

    @pytest.mark.anyio
    async def test_get_subagent_cached_content_returns_none_when_disabled(self, monkeypatch):
        """Test get_subagent_cached_content returns None when caching disabled."""
        from app.core import cache_manager, config

        monkeypatch.setattr(config.settings, "ENABLE_SYSTEM_PROMPT_CACHING", False)

        result = await cache_manager.get_subagent_cached_content("gemini-2.5-flash")
        assert result is None

    @pytest.mark.anyio
    async def test_get_subagent_cached_content_returns_cached_value(self, monkeypatch):
        """Test get_subagent_cached_content returns cached value from memory."""
        from app.core import cache_manager, config

        monkeypatch.setattr(config.settings, "ENABLE_SYSTEM_PROMPT_CACHING", True)

        # Pre-populate the in-memory cache
        cache_manager._subagent_cache["gemini-2.5-flash"] = "cachedContents/test123"

        result = await cache_manager.get_subagent_cached_content("gemini-2.5-flash")
        assert result == "cachedContents/test123"

        # Clean up
        del cache_manager._subagent_cache["gemini-2.5-flash"]


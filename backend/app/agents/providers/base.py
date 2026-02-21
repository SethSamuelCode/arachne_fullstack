"""Abstract base class for LLM model providers."""

from abc import ABC, abstractmethod

from pydantic_ai.models import Model as PydanticAIModel

from app.schemas.models import ModalitySupport


class ModelProvider(ABC):
    """Abstract base for all LLM model providers.

    Subclasses encapsulate all provider-specific configuration:
    model creation, token counting, and capability flags.
    """

    def __init__(
        self,
        model_id: str,
        api_model_id: str,
        display_name: str,
        provider_label: str,
        context_limit: int = 850_000,
    ) -> None:
        self.model_id = model_id
        self.api_model_id = api_model_id
        self.display_name = display_name
        self.provider_label = provider_label
        self._context_limit = context_limit

    @abstractmethod
    def create_pydantic_model(
        self,
        using_cached_tools: bool = False,
        cached_content_name: str | None = None,
    ) -> PydanticAIModel:
        """Return a PydanticAI model object ready for agent use."""

    async def count_tokens(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
    ) -> int:
        """Estimate token count. Default: chars / 4.

        Gemini subclasses override this with the real API.
        Vertex AI subclasses use this fallback.
        """
        text = system_prompt or ""
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                text += content
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        text += part.get("text", "")
        return max(1, len(text) // 4)

    @property
    def supports_caching(self) -> bool:
        """Whether this provider supports CachedContent API."""
        return False

    @property
    def supports_thinking(self) -> bool:
        """Whether this provider supports thinking/reasoning traces."""
        return False

    @property
    def modalities(self) -> ModalitySupport:
        """Supported input modalities. Override in providers that support multimodal input."""
        return ModalitySupport()

    @property
    def context_limit(self) -> int:
        """Maximum context window in tokens."""
        return self._context_limit

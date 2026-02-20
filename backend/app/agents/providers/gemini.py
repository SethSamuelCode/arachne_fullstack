"""Gemini model providers for the Google Gemini (direct API) backend."""

from abc import ABC, abstractmethod
from typing import Any

from google import genai
from google.genai.types import HarmBlockThreshold, HarmCategory, ThinkingLevel
from pydantic_ai.models import Model as PydanticAIModel
from pydantic_ai.models.google import GoogleModelSettings

from app.agents.cached_google_model import CachedContentGoogleModel
from app.agents.providers.base import ModelProvider
from app.core.config import settings

# Safety settings with all filters disabled for maximum permissiveness.
# Mirrors PERMISSIVE_SAFETY_SETTINGS in assistant.py.
PERMISSIVE_SAFETY_SETTINGS: list[dict[str, Any]] = [
    {"category": HarmCategory.HARM_CATEGORY_HARASSMENT, "threshold": HarmBlockThreshold.OFF},
    {"category": HarmCategory.HARM_CATEGORY_HATE_SPEECH, "threshold": HarmBlockThreshold.OFF},
    {"category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, "threshold": HarmBlockThreshold.OFF},
    {"category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, "threshold": HarmBlockThreshold.OFF},
    {"category": HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY, "threshold": HarmBlockThreshold.OFF},
]


async def _count_tokens_via_api(
    client: genai.Client,
    api_model_id: str,
    messages: list[dict],
    system_prompt: str | None = None,
) -> int:
    """Call Gemini's count_tokens API. Returns chars/4 estimate on API failure.

    Args:
        client: Google GenAI client instance.
        api_model_id: Gemini model identifier string.
        messages: Conversation messages as list of role/content dicts.
        system_prompt: Optional system prompt text to include in count.

    Returns:
        Token count from the API, or a chars/4 estimate if the API call fails.
    """
    try:
        contents: list[dict] = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": system_prompt}]})
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                contents.append({"role": msg.get("role", "user"), "parts": [{"text": content}]})
            elif isinstance(content, list):
                parts = [{"text": p.get("text", "")} for p in content if isinstance(p, dict)]
                if parts:
                    contents.append({"role": msg.get("role", "user"), "parts": parts})
        response = await client.aio.models.count_tokens(
            model=api_model_id,
            contents=contents,
        )
        return response.total_tokens or 1
    except Exception:
        # Fallback to char/4 estimate
        text = system_prompt or ""
        for msg in messages:
            c = msg.get("content", "")
            if isinstance(c, str):
                text += c
        return max(1, len(text) // 4)


class GeminiModelProvider(ModelProvider, ABC):
    """Abstract base for all Google Gemini (direct API) providers.

    Subclasses implement `_build_model_settings()` to supply
    generation-specific config (thinking settings, etc.).
    """

    def __init__(
        self,
        model_id: str,
        api_model_id: str,
        display_name: str,
        context_limit: int = 850_000,
    ) -> None:
        super().__init__(
            model_id=model_id,
            api_model_id=api_model_id,
            display_name=display_name,
            provider_label="Google Gemini",
            context_limit=context_limit,
        )
        self._genai_client: genai.Client | None = None

    def _get_client(self) -> genai.Client:
        """Lazily initialise and return the Google GenAI client."""
        if self._genai_client is None:
            self._genai_client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        return self._genai_client

    @property
    def supports_caching(self) -> bool:
        return True

    @property
    def supports_thinking(self) -> bool:
        return True

    @abstractmethod
    def _build_model_settings(self) -> GoogleModelSettings:
        """Return GoogleModelSettings for this Gemini generation."""

    def create_pydantic_model(
        self,
        using_cached_tools: bool = False,
        cached_content_name: str | None = None,
    ) -> PydanticAIModel:
        """Create a PydanticAI-compatible model object.

        Args:
            using_cached_tools: If True, tools are in cached content and will be
                stripped from the GenerateContent request.
            cached_content_name: Gemini cache name to reference in requests.

        Returns:
            A configured CachedContentGoogleModel instance.
        """
        base_settings = self._build_model_settings()

        # Start with permissive safety settings, then layer in generation-specific
        # config from the subclass, and finally apply runtime options.
        merged: GoogleModelSettings = GoogleModelSettings(
            google_safety_settings=PERMISSIVE_SAFETY_SETTINGS,
        )
        # Only copy keys that were explicitly set by the subclass.
        merged.update(base_settings)
        if cached_content_name is not None:
            merged["google_cached_content"] = cached_content_name

        return CachedContentGoogleModel(
            model_name=self.api_model_id,
            settings=merged,
            using_cached_tools=using_cached_tools,
        )

    async def count_tokens(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
    ) -> int:
        """Count tokens via the Gemini count_tokens API with a char/4 fallback."""
        return await _count_tokens_via_api(
            self._get_client(), self.api_model_id, messages, system_prompt
        )


class Gemini25ModelProvider(GeminiModelProvider):
    """Provider for the Gemini 2.5 model family.

    Uses ThinkingLevel.HIGH with included thought traces.
    """

    def _build_model_settings(self) -> GoogleModelSettings:
        return GoogleModelSettings(
            google_thinking_config={
                "thinking_level": ThinkingLevel.HIGH,
                "include_thoughts": True,
            },
        )


class Gemini3ModelProvider(GeminiModelProvider):
    """Provider for the Gemini 3 model family.

    Uses ThinkingLevel.HIGH with included thought traces.
    Kept as a separate class from Gemini25ModelProvider to allow
    generation-specific config differences as the Gemini 3 API evolves.
    """

    def _build_model_settings(self) -> GoogleModelSettings:
        return GoogleModelSettings(
            google_thinking_config={
                "thinking_level": ThinkingLevel.HIGH,
                "include_thoughts": True,
            },
        )

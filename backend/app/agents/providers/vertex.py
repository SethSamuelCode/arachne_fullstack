"""Vertex AI model provider."""

import os

from pydantic_ai.models import Model as PydanticAIModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from app.agents.providers.base import ModelProvider
from app.core.config import settings
from app.core.exceptions import ExternalServiceError


class VertexModelProvider(ModelProvider):
    """Provider for models accessed via Google Cloud Vertex AI.

    Supports any model available through the Vertex AI API, including
    third-party models (e.g. GLM-5 via the Model Garden).

    Does NOT support CachedContent API or thinking — use Gemini providers for those.
    Token counting falls back to the base class chars/4 estimate.
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
            provider_label="Google Vertex AI",
            context_limit=context_limit,
        )

    @property
    def supports_caching(self) -> bool:
        return False

    @property
    def supports_thinking(self) -> bool:
        return False

    def create_pydantic_model(
        self,
        using_cached_tools: bool = False,
        cached_content_name: str | None = None,
    ) -> PydanticAIModel:
        """Create a Vertex AI model, validating credentials are configured.

        Raises:
            ExternalServiceError: If GCP_PROJECT or GOOGLE_APPLICATION_CREDENTIALS
                is not configured.
        """
        if not settings.GCP_PROJECT:
            raise ExternalServiceError(
                "GCP_PROJECT must be set in environment to use Vertex AI models. "
                f"Cannot load model '{self.model_id}'."
            )
        if not settings.GOOGLE_APPLICATION_CREDENTIALS:
            raise ExternalServiceError(
                "GOOGLE_APPLICATION_CREDENTIALS must be set in environment to use "
                f"Vertex AI models. Cannot load model '{self.model_id}'."
            )
        # Ensure the Google SDK can find the credentials file via ADC.
        # pydantic-settings reads .env but does NOT set os.environ, so we must
        # propagate the path ourselves.
        os.environ.setdefault(
            "GOOGLE_APPLICATION_CREDENTIALS", settings.GOOGLE_APPLICATION_CREDENTIALS
        )
        provider = GoogleProvider(
            vertexai=True,
            project=settings.GCP_PROJECT,
            location=settings.GCP_LOCATION,
        )
        return GoogleModel(self.api_model_id, provider=provider)

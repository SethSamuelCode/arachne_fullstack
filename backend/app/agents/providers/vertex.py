"""Vertex AI model provider."""

import os
from pathlib import Path

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
        creds_path = settings.GOOGLE_APPLICATION_CREDENTIALS
        if not creds_path:
            raise ExternalServiceError(
                "GOOGLE_APPLICATION_CREDENTIALS must be set in environment to use "
                f"Vertex AI models. Cannot load model '{self.model_id}'."
            )
        if not Path(creds_path).is_file():
            raise ExternalServiceError(
                f"GOOGLE_APPLICATION_CREDENTIALS path does not exist or is not a file: "
                f"'{creds_path}'. Cannot load model '{self.model_id}'."
            )
        # Propagate the sanitised credentials path into os.environ so the Google
        # SDK can locate the credentials file via ADC.  pydantic-settings reads
        # .env but does NOT place values into os.environ, so we must do it here.
        # Using direct assignment (not setdefault) ensures the sanitised value
        # from settings always wins over any unsanitised value already in the env.
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
        provider = GoogleProvider(
            vertexai=True,
            project=settings.GCP_PROJECT,
            location=settings.GCP_LOCATION,
        )
        return GoogleModel(self.api_model_id, provider=provider)

"""Model registry — the single source of truth for all available LLM models."""

import logging

from app.agents.providers.base import ModelProvider
from app.agents.providers.gemini import Gemini3ModelProvider, Gemini25ModelProvider
from app.agents.providers.vertex import VertexModelProvider

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID: str = "gemini-2.5-flash"

MODEL_REGISTRY: dict[str, ModelProvider] = {
    # Gemini 2.5 family (direct API, caching + thinking)
    "gemini-2.5-flash-lite": Gemini25ModelProvider(
        model_id="gemini-2.5-flash-lite",
        api_model_id="gemini-2.5-flash-lite",
        display_name="Gemini 2.5 Flash Lite",
        context_limit=1_000_000,
    ),
    "gemini-2.5-flash": Gemini25ModelProvider(
        model_id="gemini-2.5-flash",
        api_model_id="gemini-2.5-flash",
        display_name="Gemini 2.5 Flash",
        context_limit=1_048_576,
    ),
    "gemini-2.5-pro": Gemini25ModelProvider(
        model_id="gemini-2.5-pro",
        api_model_id="gemini-2.5-pro",
        display_name="Gemini 2.5 Pro",
        context_limit=1_048_576,
    ),
    # Gemini 3 family (direct API, caching + thinking)
    "gemini-3-flash-preview": Gemini3ModelProvider(
        model_id="gemini-3-flash-preview",
        api_model_id="gemini-3-flash-preview",
        display_name="Gemini 3 Flash",
        context_limit=1_048_576,
    ),
    "gemini-3-pro-preview": Gemini3ModelProvider(
        model_id="gemini-3-pro-preview",
        api_model_id="gemini-3-pro-preview",
        display_name="Gemini 3 Pro",
        context_limit=2_000_000,
    ),
    "gemini-3.1-pro-preview": Gemini3ModelProvider(
        model_id="gemini-3.1-pro-preview",
        api_model_id="gemini-3.1-pro-preview",
        display_name="Gemini 3.1 Pro",
        context_limit=2_000_000,
    ),
    # Vertex AI models (no caching, no thinking)
    "glm-5": VertexModelProvider(
        model_id="glm-5",
        api_model_id="publishers/zai-org/models/glm-5-maas",
        display_name="GLM-5 (Vertex AI)",
        context_limit=200_000,  # Official Vertex AI GLM-5 context window
    ),
}


def get_provider(model_id: str) -> ModelProvider:
    """Return the ModelProvider for the given model ID.

    Falls back to DEFAULT_MODEL_ID if the model is not found.
    Logs a warning when falling back.
    """
    if model_id in MODEL_REGISTRY:
        return MODEL_REGISTRY[model_id]
    logger.warning("Unknown model '%s', falling back to default '%s'", model_id, DEFAULT_MODEL_ID)
    return MODEL_REGISTRY[DEFAULT_MODEL_ID]


def get_model_list() -> list[dict[str, object]]:
    """Return a list of all available models for the /models API endpoint.

    Each entry has: id, label, provider, supports_thinking, modalities.
    """
    return [
        {
            "id": provider.model_id,
            "label": provider.display_name,
            "provider": provider.provider_label,
            "supports_thinking": provider.supports_thinking,
            "modalities": provider.modalities.model_dump(),
        }
        for provider in MODEL_REGISTRY.values()
    ]

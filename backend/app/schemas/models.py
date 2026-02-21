"""Shared schema primitives for model configuration."""

from pydantic import BaseModel


class ModelInfo(BaseModel):
    """Available model information returned by the /models endpoint."""

    id: str
    label: str
    provider: str
    supports_thinking: bool = False


# Backward-compatible alias. New code should import DEFAULT_MODEL_ID from
# app.agents.providers.registry. This string alias avoids circular imports
# while being importable from schemas.
DEFAULT_GEMINI_MODEL: str = "gemini-2.5-flash"

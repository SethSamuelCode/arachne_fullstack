"""Models endpoint — returns the available LLM model list."""

from fastapi import APIRouter

from app.agents.providers.registry import get_model_list
from app.schemas.models import ModelInfo

router = APIRouter()


@router.get("/models", response_model=list[ModelInfo])
async def list_models() -> list[dict]:
    """Return all available LLM models.

    No authentication required — this is public configuration data,
    equivalent to a health check. The frontend uses this to populate
    the model selector on the profile page.

    Returns:
        List of model descriptors with id, label, provider, supports_thinking.
    """
    return get_model_list()

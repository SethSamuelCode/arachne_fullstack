from app.schemas.models import GeminiModelName, DEFAULT_GEMINI_MODEL
from dataclasses import dataclass, field
from typing import Any

@dataclass
class SpawnAgentDeps:
    """Dependencies for spawn_agent tool."""
    user_id: str | None = None
    user_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    spawn_depth: int = 0
    spawn_max_depth: int = 10
    model_name: GeminiModelName = DEFAULT_GEMINI_MODEL
    system_prompt: str | None = None
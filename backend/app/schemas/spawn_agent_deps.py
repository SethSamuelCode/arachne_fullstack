from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.schemas.models import DEFAULT_GEMINI_MODEL

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class SpawnAgentDeps:
    """Dependencies for spawn_agent tool."""
    user_id: str | None = None
    user_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    db: "AsyncSession | None" = None

    spawn_depth: int = 0
    spawn_max_depth: int = 10
    model_name: str = DEFAULT_GEMINI_MODEL
    system_prompt: str | None = None

    # Caching support: if set, use cached content instead of registering tools
    cached_content_name: str | None = None
    skip_tool_registration: bool = False

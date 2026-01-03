"""Universal agent factory.

Goal: one agent template (same tool registry + decision policy) that can be
instantiated with a free-form system prompt and an allow-listed model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel

from app.schemas import GeminiModelName


@dataclass(frozen=True)
class UniversalAgentConfig:
    """Runtime-configurable agent knobs.

    - `system_prompt` is free-form.
    - `model_name` is allow-listed via `GeminiModelName`.
    """

    system_prompt: str
    model_name: GeminiModelName


def create_universal_agent(config: UniversalAgentConfig) -> Agent:
    """Create a pydantic-ai Agent with the provided model + system prompt.

    Tool registration is handled separately (see `src.agent.tool_registry`).
    """

    model = GoogleModel(config.model_name.value)
    return Agent(model=model, system_prompt=config.system_prompt)


def create_universal_agent_typed(
    config: UniversalAgentConfig,
    *,
    deps_type: type[Any] | None = None,
    output_type: type[Any] | None = None,
    retries: int = 2,
) -> Agent:
    """Create an Agent with explicit deps/output types.

    PydanticAI agents have a fixed output type; the universal tools registry is
    designed to be attached to multiple agents that share the same deps type.
    """

    model = GoogleModel(config.model_name.value)
    return Agent(
        model=model,
        system_prompt=config.system_prompt,
        deps_type=deps_type,
        output_type=output_type,
        retries=retries,
    )

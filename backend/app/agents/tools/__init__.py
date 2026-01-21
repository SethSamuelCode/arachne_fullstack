"""Agent tools module.

This module contains utility functions that can be used as agent tools.
Tools are registered in the agent definition using @agent.tool decorator.
"""

import hashlib
import json
import logging
from typing import Any

from pydantic_ai import Agent

from app.agents.tools.datetime_tool import get_current_datetime
from app.schemas.assistant import Deps

logger = logging.getLogger(__name__)

__all__ = [
    "get_current_datetime",
    "get_tool_definitions",
    "get_tools_schema_hash",
]


def get_tool_definitions() -> list[dict[str, Any]]:
    """Extract tool definitions from registered agent tools.

    Creates a temporary agent, registers all tools via register_tools(),
    and extracts serializable schemas from PydanticAI's internal _function_tools.

    Returns:
        List of tool definition dicts with 'name', 'description', and 'parameters'.
    """
    # Import here to avoid circular imports
    from app.agents.tool_register import register_tools

    # Create a minimal temporary agent just to extract tool schemas
    # We use a mock model since we only need tool registration, not execution
    temp_agent: Agent[Deps, str] = Agent(
        model="test",  # Placeholder, won't be used
        deps_type=Deps,
    )

    # Register all tools to the temporary agent
    register_tools(temp_agent)

    # Extract tool definitions from PydanticAI's internal structure
    tool_definitions: list[dict[str, Any]] = []

    for tool in temp_agent._function_toolset.tools.values():
        tool_def = {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.function_schema.json_schema,
        }
        tool_definitions.append(tool_def)

    # Sort by name for consistent hashing
    tool_definitions.sort(key=lambda t: t["name"])

    logger.debug(f"Extracted {len(tool_definitions)} tool definitions")
    return tool_definitions


def get_tools_schema_hash() -> str:
    """Generate a consistent hash of all tool definitions.

    Used for cache key generation and detecting when tools have changed
    (requiring cache invalidation).

    Returns:
        SHA256 hash (first 16 chars) of serialized tool definitions.
    """
    tool_defs = get_tool_definitions()
    # Serialize with sorted keys for consistent ordering
    serialized = json.dumps(tool_defs, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]

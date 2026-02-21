"""Assistant agent with PydanticAI.

The main conversational agent that can be extended with custom tools.
Model-specific behaviour (safety settings, thinking config, caching) is
encapsulated in ModelProvider subclasses — this module has no knowledge of
specific providers.
"""

import logging
from collections.abc import AsyncGenerator, Sequence
from typing import Any

from pydantic_ai import Agent, BinaryContent, UsageLimits
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)

from app.agents.prompts import DEFAULT_SYSTEM_PROMPT
from app.agents.providers.base import ModelProvider
from app.agents.providers.registry import DEFAULT_MODEL_ID, get_provider
from app.agents.tool_register import register_tools
from app.core.config import settings
from app.schemas.assistant import Deps

logger = logging.getLogger(__name__)

# Type alias for multimodal user input (text + images)
UserContent = str | BinaryContent
MultimodalInput = str | Sequence[UserContent]


class AssistantAgent:
    """Assistant agent wrapper for conversational AI.

    Encapsulates agent creation and execution with tool support.
    Delegates all provider-specific concerns to the ModelProvider.
    """

    def __init__(
        self,
        provider: ModelProvider | None = None,
        system_prompt: str | None = None,
        cached_prompt_name: str | None = None,
        skip_tool_registration: bool = False,
    ):
        self.provider = provider or get_provider(DEFAULT_MODEL_ID)
        self.model_name = self.provider.model_id  # exposed for DB persistence
        # If using cached prompt, don't pass system_prompt to agent (it's in the cache)
        self.system_prompt = (
            None if cached_prompt_name else (system_prompt or DEFAULT_SYSTEM_PROMPT)
        )
        self.cached_prompt_name = cached_prompt_name
        self.skip_tool_registration = skip_tool_registration
        self._agent: Agent[Deps, str] | None = None

    def _create_agent(self) -> Agent[Deps, str]:
        """Create and configure the PydanticAI agent."""
        using_cached_tools = bool(self.cached_prompt_name)

        # Delegate model creation to the provider — no hardcoded Gemini logic here
        model = self.provider.create_pydantic_model(
            using_cached_tools=using_cached_tools,
            cached_content_name=self.cached_prompt_name,
        )

        agent_kwargs: dict[str, Any] = {
            "model": model,
            "deps_type": Deps,
            "retries": settings.AGENT_TOOL_RETRIES,
            "output_retries": settings.AGENT_OUTPUT_RETRIES,
        }
        if self.system_prompt:
            agent_kwargs["system_prompt"] = self.system_prompt

        agent = Agent[Deps, str](**agent_kwargs)

        # Always register tools locally - PydanticAI needs them to execute tool calls.
        # When using cached content, the model already knows about the tools (they're
        # in the cache), but PydanticAI still needs them registered to handle the
        # tool call responses. The provider's model strips tools from the API request
        # so the model doesn't get duplicate tool definitions.
        register_tools(agent)

        if using_cached_tools:
            logger.debug("Tools registered locally (will be stripped from API request)")

        return agent

    @property
    def agent(self) -> Agent[Deps, str]:
        """Get or create the agent instance."""
        if self._agent is None:
            self._agent = self._create_agent()
        return self._agent

    async def run(
        self,
        user_input: MultimodalInput,
        history: list[dict[str, str]] | None = None,
        deps: Deps | None = None,
    ) -> tuple[str, list[Any], Deps]:
        """Run agent and return the output along with tool call events.

        Args:
            user_input: User's message. Can be a string or a list containing
                text and BinaryContent (for images).
            history: Conversation history as list of {"role": "...", "content": "..."}.
            deps: Optional dependencies. If not provided, a new Deps will be created.

        Returns:
            Tuple of (output_text, tool_events, deps).
        """
        model_history: list[ModelRequest | ModelResponse] = []

        for msg in history or []:
            if msg["role"] == "user":
                model_history.append(ModelRequest(parts=[UserPromptPart(content=msg["content"])]))
            elif msg["role"] == "assistant":
                model_history.append(ModelResponse(parts=[TextPart(content=msg["content"])]))
            elif msg["role"] == "system":
                model_history.append(ModelRequest(parts=[SystemPromptPart(content=msg["content"])]))

        agent_deps = deps if deps is not None else Deps()

        # Log input (truncate if it's a string, otherwise note it's multimodal)
        if isinstance(user_input, str):
            logger.info(f"Running agent with user input: {user_input[:100]}...")
        else:
            text_parts = [p for p in user_input if isinstance(p, str)]
            image_count = sum(1 for p in user_input if isinstance(p, BinaryContent))
            logger.info(
                f"Running agent with multimodal input: {text_parts[0][:50] if text_parts else '(no text)'}... "
                f"({image_count} image(s))"
            )

        result = await self.agent.run(user_input, deps=agent_deps, message_history=model_history)

        tool_events: list[Any] = []
        for message in result.all_messages():
            if hasattr(message, "parts"):
                for part in message.parts:
                    if hasattr(part, "tool_name"):
                        tool_events.append(part)

        logger.info(f"Agent run complete. Output length: {len(result.output)} chars")

        return result.output, tool_events, agent_deps

    async def iter(
        self,
        user_input: MultimodalInput,
        history: list[dict[str, str]] | None = None,
        deps: Deps | None = None,
    ) -> AsyncGenerator[Any, None]:
        """Stream agent execution with full event access.

        Args:
            user_input: User's message. Can be a string or a list containing
                text and BinaryContent (for images).
            history: Conversation history.
            deps: Optional dependencies.

        Yields:
            Agent events for streaming responses.
        """
        model_history: list[ModelRequest | ModelResponse] = []

        for msg in history or []:
            if msg["role"] == "user":
                model_history.append(ModelRequest(parts=[UserPromptPart(content=msg["content"])]))
            elif msg["role"] == "assistant":
                model_history.append(ModelResponse(parts=[TextPart(content=msg["content"])]))
            elif msg["role"] == "system":
                model_history.append(ModelRequest(parts=[SystemPromptPart(content=msg["content"])]))

        agent_deps = deps if deps is not None else Deps()

        async with self.agent.iter(
            user_input,
            deps=agent_deps,
            message_history=model_history,
            usage_limits=UsageLimits(
                request_limit=settings.AGENT_MAX_REQUESTS,
                tool_calls_limit=settings.AGENT_MAX_TOOL_CALLS,
            ),
        ) as run:
            async for event in run:
                yield event


def get_agent(
    system_prompt: str | None = None,
    model_name: str | None = None,
    provider: ModelProvider | None = None,
    cached_prompt_name: str | None = None,
    skip_tool_registration: bool = False,
) -> AssistantAgent:
    """Factory function to create an AssistantAgent.

    Accepts either a pre-resolved ModelProvider or a model_name string.
    If both are given, provider takes precedence.

    Args:
        system_prompt: Custom system prompt (ignored if cached_prompt_name is provided).
        model_name: Model ID to look up in the registry (e.g. "gemini-2.5-flash").
        provider: Pre-resolved ModelProvider (takes precedence over model_name).
        cached_prompt_name: Provider-specific cache name for the content (e.g. "cachedContents/abc123").
        skip_tool_registration: Deprecated no-op. Tools are always registered locally
            so PydanticAI can handle tool call responses. Kept for backward compatibility.

    Returns:
        Configured AssistantAgent instance.
    """
    resolved_provider = provider or get_provider(model_name or DEFAULT_MODEL_ID)
    return AssistantAgent(
        provider=resolved_provider,
        system_prompt=system_prompt,
        cached_prompt_name=cached_prompt_name,
        skip_tool_registration=skip_tool_registration,
    )


async def run_agent(
    user_input: str,
    history: list[dict[str, str]],
    deps: Deps | None = None,
    system_prompt: str | None = None,
) -> tuple[str, list[Any], Deps]:
    """Run agent and return the output along with tool call events.

    This is a convenience function for backwards compatibility.

    Args:
        user_input: User's message.
        history: Conversation history.
        deps: Optional dependencies.
        system_prompt: Optional custom system prompt.

    Returns:
        Tuple of (output_text, tool_events, deps).
    """
    agent = get_agent(system_prompt=system_prompt)
    return await agent.run(user_input, history, deps)

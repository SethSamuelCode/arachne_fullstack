"""Assistant agent with PydanticAI.

The main conversational agent that can be extended with custom tools.
"""

import logging
from collections.abc import Sequence
from typing import Any

from google.genai.types import HarmBlockThreshold, HarmCategory, ThinkingLevel
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models.google import GoogleModelSettings

from app.agents.cached_google_model import CachedContentGoogleModel
from app.agents.prompts import DEFAULT_SYSTEM_PROMPT
from app.agents.tool_register import register_tools
from app.schemas import DEFAULT_GEMINI_MODEL
from app.schemas.assistant import Deps

logger = logging.getLogger(__name__)

# Type alias for multimodal user input (text + images)
UserContent = str | BinaryContent
MultimodalInput = str | Sequence[UserContent]

# Safety settings with all filters disabled for maximum permissiveness
PERMISSIVE_SAFETY_SETTINGS: list[dict[str, Any]] = [
    {"category": HarmCategory.HARM_CATEGORY_HARASSMENT, "threshold": HarmBlockThreshold.OFF},
    {"category": HarmCategory.HARM_CATEGORY_HATE_SPEECH, "threshold": HarmBlockThreshold.OFF},
    {"category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, "threshold": HarmBlockThreshold.OFF},
    {"category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, "threshold": HarmBlockThreshold.OFF},
    {"category": HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY, "threshold": HarmBlockThreshold.OFF},
]


class AssistantAgent:
    """Assistant agent wrapper for conversational AI.

    Encapsulates agent creation and execution with tool support.
    """

    def __init__(
        self,
        model_name: str | None = None,
        system_prompt: str | None = None,
        cached_prompt_name: str | None = None,
        skip_tool_registration: bool = False,
    ):
        self.model_name = model_name or DEFAULT_GEMINI_MODEL
        # If using cached prompt, don't pass system_prompt to agent (it's in the cache)
        self.system_prompt = None if cached_prompt_name else (system_prompt or DEFAULT_SYSTEM_PROMPT)
        self.cached_prompt_name = cached_prompt_name
        self.skip_tool_registration = skip_tool_registration
        self._agent: Agent[Deps, str] | None = None

    def _create_agent(self) -> Agent[Deps, str]:
        """Create and configure the PydanticAI agent."""
        # Determine if we're using cached content with tools
        using_cached_tools = bool(self.cached_prompt_name)

        # Model settings with safety filters disabled and thinking enabled
        model_settings = GoogleModelSettings(
            google_safety_settings=PERMISSIVE_SAFETY_SETTINGS,
            google_thinking_config={
                "thinking_level": ThinkingLevel.HIGH,
            },
            # Use cached content if available (75% cost reduction)
            google_cached_content=self.cached_prompt_name if self.cached_prompt_name else None,
        )

        # Use our custom model that strips tools when using cached content
        model = CachedContentGoogleModel(
            model_name=self.model_name,
            settings=model_settings,
            using_cached_tools=using_cached_tools,
        )

        # Build agent kwargs - omit system_prompt entirely when using cached content
        agent_kwargs: dict[str, Any] = {
            "model": model,
            "deps_type": Deps,
            "retries": 3,  # Allow more retries for tool calls and output validation
        }
        if self.system_prompt:
            agent_kwargs["system_prompt"] = self.system_prompt

        agent = Agent[Deps, str](**agent_kwargs)

        # Always register tools locally - PydanticAI needs them to execute tool calls.
        # When using cached content, Gemini already knows about the tools (they're
        # in the cache), but PydanticAI still needs them registered to handle the
        # tool call responses. Our CachedContentGoogleModel strips tools from the
        # API request so Gemini doesn't get duplicate tool definitions.
        register_tools(agent)

        if using_cached_tools:
            logger.debug("Tools registered locally (will be stripped from Gemini request)")

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
    ):
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
        ) as run:
            async for event in run:
                yield event


def get_agent(
    system_prompt: str | None = None,
    model_name: str | None = None,
    cached_prompt_name: str | None = None,
    skip_tool_registration: bool = False,
) -> AssistantAgent:
    """Factory function to create an AssistantAgent.

    Args:
        system_prompt: Custom system prompt (ignored if cached_prompt_name is provided).
        model_name: Gemini model name to use.
        cached_prompt_name: Gemini cache name for the content (75% cost savings).
        skip_tool_registration: If True, skip tool registration (tools in cache).

    Returns:
        Configured AssistantAgent instance.
    """
    return AssistantAgent(
        system_prompt=system_prompt,
        model_name=model_name,
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

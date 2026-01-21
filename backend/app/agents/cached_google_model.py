"""Custom Google Model wrapper for cached content support.

When using Gemini's CachedContent API with tools, Gemini requires that:
1. Tools must be included in the CachedContent (not in the request)
2. The GenerateContent request must NOT include tools/tool_config

But PydanticAI automatically sends registered tools with every request.
This wrapper intercepts requests and strips tools when using cached content,
allowing PydanticAI to still execute tool calls locally while Gemini uses
the cached tool definitions.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.settings import ModelSettings

logger = logging.getLogger(__name__)


class CachedContentGoogleModel(GoogleModel):
    """Google Model that strips tools from requests when using cached content.

    When `google_cached_content` is set in settings, this model:
    1. Removes tools from the request (they're in the cache)
    2. Passes the cached content reference to Gemini
    3. Still allows PydanticAI to execute tool calls locally

    This solves the conflict where Gemini rejects requests with both
    cached content AND tools/tool_config.
    """

    def __init__(
        self,
        model_name: str,
        *,
        settings: GoogleModelSettings | None = None,
        using_cached_tools: bool = False,
    ):
        """Initialize the cached content model.

        Args:
            model_name: Gemini model name.
            settings: Google model settings including google_cached_content.
            using_cached_tools: If True, strip tools from requests (they're cached).
        """
        super().__init__(model_name=model_name, settings=settings)
        self._using_cached_tools = using_cached_tools

    def _strip_tools_if_cached(
        self,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelRequestParameters:
        """Strip tools from request parameters if using cached content.

        Args:
            model_request_parameters: Original request parameters with tools.

        Returns:
            Modified parameters with tools removed if using cached content.
        """
        if not self._using_cached_tools:
            return model_request_parameters

        # Create a copy without tools
        # ModelRequestParameters is a dataclass, so we rebuild it
        logger.debug("Stripping tools from request (using cached content)")
        return ModelRequestParameters(
            function_tools=[],  # Empty - tools are in cache
            allow_text_output=model_request_parameters.allow_text_output,
            output_tools=model_request_parameters.output_tools,
        )

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Make a request, stripping tools if using cached content."""
        model_request_parameters = self._strip_tools_if_cached(model_request_parameters)

        return await super().request(
            messages=messages,
            model_settings=model_settings,
            model_request_parameters=model_request_parameters,
        )

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: Any | None = None,
    ) -> AsyncIterator[Any]:
        """Make a streaming request, stripping tools if using cached content."""
        model_request_parameters = self._strip_tools_if_cached(model_request_parameters)

        async with super().request_stream(
            messages=messages,
            model_settings=model_settings,
            model_request_parameters=model_request_parameters,
            run_context=run_context,
        ) as stream:
            yield stream

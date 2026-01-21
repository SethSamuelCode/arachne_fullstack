"""Context window optimizer for Gemini models.

Implements tiered memory management with:
- Token-aware context trimming using Gemini's native count_tokens API
- System prompt + tools caching via CachedContent for 75% cost reduction
- TTL extension for active sessions

Note: Gemini's CachedContent API requires system_instruction, tools, and
tool_config to ALL be cached together - you cannot mix cached content with
dynamically registered tools.
"""

import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any, TypedDict

from google import genai

if TYPE_CHECKING:
    from app.clients.redis import RedisClient
from google.genai import types as genai_types
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from app.core.config import settings

logger = logging.getLogger(__name__)


class OptimizedContext(TypedDict):
    """Result of context optimization.

    Attributes:
        history: Optimized message history in PydanticAI format.
        cached_prompt_name: Gemini cache name if content was cached, None otherwise.
        system_prompt: The system prompt text if NOT cached, None if using cache.
        skip_tool_registration: If True, tools are in cache; skip register_tools().
    """

    history: list[ModelRequest | ModelResponse]
    cached_prompt_name: str | None
    system_prompt: str | None
    skip_tool_registration: bool


# Model context limits (input tokens) with 85% budget for responsiveness
MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "gemini-2.5-flash-lite": 891_289,  # 1M * 0.85
    "gemini-2.5-flash": 891_289,  # 1M * 0.85
    "gemini-2.5-pro": 891_289,  # 1M * 0.85
    "gemini-3-flash-preview": 850_000,  # 1M * 0.85
    "gemini-3-pro-preview": 1_700_000,  # 2M * 0.85
}

# Default fallback budget (conservative)
DEFAULT_TOKEN_BUDGET = 850_000

# Cache TTL in seconds (55 minutes, under Gemini's 1-hour limit)
CACHE_TTL_SECONDS = 3300

# Gemini count_tokens API limit per call (conservative)
COUNT_TOKENS_CHUNK_LIMIT = 900_000


def _get_genai_client() -> genai.Client:
    """Get Google GenAI client instance."""
    return genai.Client(api_key=settings.GOOGLE_API_KEY)


def _hash_prompt(prompt: str) -> str:
    """Generate a short hash for cache key derivation."""
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


def _estimate_tokens(content: str) -> int:
    """Estimate token count using char/4 heuristic.

    Used as fallback when API counting is unavailable or for cached messages.
    """
    return len(content) // 4


def _messages_to_contents(
    messages: list[dict[str, str]],
) -> list[genai_types.Content]:
    """Convert conversation history to Gemini Content format for counting."""
    contents: list[genai_types.Content] = []

    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"
        contents.append(
            genai_types.Content(
                role=role,
                parts=[genai_types.Part(text=msg["content"])],
            )
        )

    return contents


async def count_tokens_batch(
    messages: list[dict[str, str]],
    model_name: str,
    system_prompt: str | None = None,
) -> int:
    """Count tokens for messages using Gemini's native API.

    Handles chunking for contexts exceeding the 1M API limit.

    Args:
        messages: Conversation history as list of {"role": "...", "content": "..."}.
        model_name: Gemini model name for accurate tokenization.
        system_prompt: Optional system prompt to include in count.

    Returns:
        Total token count for the context.
    """
    if not messages:
        return _estimate_tokens(system_prompt) if system_prompt else 0

    client = _get_genai_client()

    # Quick estimate to determine if chunking needed
    estimated_total = sum(_estimate_tokens(m["content"]) for m in messages)
    if system_prompt:
        estimated_total += _estimate_tokens(system_prompt)

    try:
        if estimated_total < COUNT_TOKENS_CHUNK_LIMIT:
            # Single API call
            contents = _messages_to_contents(messages)
            config: dict[str, Any] = {}
            if system_prompt:
                config["system_instruction"] = system_prompt

            result = await client.aio.models.count_tokens(
                model=model_name,
                contents=contents,
                config=config if config else None,
            )
            return result.total_tokens or 0

        # Chunked counting for large contexts
        total_tokens = 0
        chunk: list[dict[str, str]] = []
        chunk_estimate = 0

        # Count system prompt separately if present
        if system_prompt:
            result = await client.aio.models.count_tokens(
                model=model_name,
                contents=[
                    genai_types.Content(
                        role="user",
                        parts=[genai_types.Part(text=system_prompt)],
                    )
                ],
            )
            total_tokens += result.total_tokens or 0

        for msg in messages:
            msg_estimate = _estimate_tokens(msg["content"])

            if chunk_estimate + msg_estimate > COUNT_TOKENS_CHUNK_LIMIT and chunk:
                # Count current chunk
                contents = _messages_to_contents(chunk)
                result = await client.aio.models.count_tokens(
                    model=model_name,
                    contents=contents,
                )
                total_tokens += result.total_tokens or 0
                chunk = []
                chunk_estimate = 0

            chunk.append(msg)
            chunk_estimate += msg_estimate

        # Count remaining chunk
        if chunk:
            contents = _messages_to_contents(chunk)
            result = await client.aio.models.count_tokens(
                model=model_name,
                contents=contents,
            )
            total_tokens += result.total_tokens or 0

        return total_tokens

    except Exception as e:
        logger.warning(f"Token counting API failed, using estimate: {e}")
        return estimated_total


def _hash_tools(tool_definitions: list[dict[str, Any]]) -> str:
    """Generate a short hash for tool definitions.

    Args:
        tool_definitions: List of tool definition dicts.

    Returns:
        16-char hash of serialized tools.
    """
    serialized = json.dumps(tool_definitions, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


def _sanitize_schema_for_gemini(schema: dict[str, Any]) -> dict[str, Any]:
    """Sanitize a JSON Schema for Gemini's FunctionDeclaration.

    Gemini's API uses a limited subset of JSON Schema and doesn't support:
    - `examples` field
    - `$ref` references
    - `$defs` definitions
    - `title` field in nested objects

    This function resolves $ref references, removes unsupported fields, and
    **enriches descriptions** with examples and titles for better LLM tool use.
    Since schemas are cached, the enrichment cost is amortized.

    Args:
        schema: JSON Schema dict from PydanticAI tool.

    Returns:
        Sanitized schema compatible with Gemini, with enriched descriptions.
    """
    # Extract $defs for reference resolution
    defs = schema.get("$defs", {})

    def _enrich_description(obj: dict[str, Any]) -> str | None:
        """Build an enriched description from title, description, and examples."""
        parts: list[str] = []

        # Add title as context if different from description
        title = obj.get("title")
        description = obj.get("description", "")

        if title and title.lower() != description.lower()[:len(title)]:
            parts.append(title + ".")

        if description:
            parts.append(description)

        # Add examples - very valuable for LLM tool understanding
        examples = obj.get("examples")
        if examples:
            if len(examples) == 1:
                parts.append(f"Example: {examples[0]!r}")
            else:
                example_strs = [repr(ex) for ex in examples[:3]]  # Limit to 3
                parts.append(f"Examples: {', '.join(example_strs)}")

        # Add default value hint
        default = obj.get("default")
        if default is not None:
            parts.append(f"Default: {default!r}")

        return " ".join(parts) if parts else None

    def resolve_refs(obj: Any) -> Any:
        """Recursively resolve $ref, enrich descriptions, remove unsupported."""
        if isinstance(obj, dict):
            # Handle $ref - replace with the referenced definition
            if "$ref" in obj:
                ref_path = obj["$ref"]
                # Parse "#/$defs/TypeName" format
                if ref_path.startswith("#/$defs/"):
                    type_name = ref_path[8:]  # Remove "#/$defs/"
                    if type_name in defs:
                        # Return resolved definition (recursively sanitize it too)
                        return resolve_refs(defs[type_name])
                # If can't resolve, return empty object schema
                logger.warning(f"Could not resolve $ref: {ref_path}")
                return {"type": "object"}

            # Build enriched description before removing fields
            enriched_desc = _enrich_description(obj)

            # Fields not supported by Gemini's Schema
            unsupported = {"examples", "$defs", "title", "default"}
            result: dict[str, Any] = {}

            for key, value in obj.items():
                if key not in unsupported:
                    result[key] = resolve_refs(value)

            # Apply enriched description (overwrite if we built a better one)
            if enriched_desc:
                result["description"] = enriched_desc

            return result

        if isinstance(obj, list):
            return [resolve_refs(item) for item in obj]

        return obj

    return resolve_refs(schema)


def _convert_tools_to_gemini_format(
    tool_definitions: list[dict[str, Any]],
) -> list[genai_types.Tool]:
    """Convert tool definitions to Gemini Tool format.

    Args:
        tool_definitions: List of tool definition dicts with 'name', 'description', 'parameters'.

    Returns:
        List of Gemini Tool objects for caching.
    """
    function_declarations = []
    for tool_def in tool_definitions:
        # Sanitize the parameters schema for Gemini compatibility
        sanitized_params = _sanitize_schema_for_gemini(tool_def["parameters"])

        # Build FunctionDeclaration from our tool schema
        # Cast to Schema - Gemini accepts dict at runtime
        func_decl = genai_types.FunctionDeclaration(
            name=tool_def["name"],
            description=tool_def["description"],
            parameters=genai_types.Schema(**sanitized_params),
        )
        function_declarations.append(func_decl)

    # Wrap all functions in a single Tool
    return [genai_types.Tool(function_declarations=function_declarations)]


async def get_cached_content(
    prompt: str,
    model_name: str,
    tool_definitions: list[dict[str, Any]],
    redis_client: Any | None = None,
    extend_on_use: bool = True,
) -> str | None:
    """Get or create cached content (system prompt + tools) for reduced cost.

    Uses Gemini's CachedContent API to cache both system prompt and tool definitions
    server-side. This satisfies Gemini's requirement that cached content must include
    ALL of: system_instruction, tools, and tool_config together.

    Active sessions have their TTL extended automatically.
    On failure, returns None and logs a warning (graceful degradation).

    Args:
        prompt: The system prompt text.
        model_name: Gemini model name.
        tool_definitions: List of tool definition dicts from get_tool_definitions().
        redis_client: Redis client for cache key storage.
        extend_on_use: Whether to extend TTL on cache hit.

    Returns:
        The cache name for use in requests, or None if caching failed/unavailable.
    """
    if not redis_client:
        logger.debug("Redis client not available, skipping content caching")
        return None

    if not tool_definitions:
        logger.warning("No tool definitions provided, skipping content caching")
        return None

    # Cache key includes both prompt hash and tools hash
    tools_hash = _hash_tools(tool_definitions)
    cache_key = f"arachne:cached_content:{model_name}:{_hash_prompt(prompt)}:{tools_hash}"

    try:
        cached_name = await redis_client.get(cache_key)

        if cached_name:
            if extend_on_use:
                # Extend Redis TTL
                await redis_client.set(cache_key, cached_name, ttl=CACHE_TTL_SECONDS)

                # Extend Gemini cache TTL
                try:
                    client = _get_genai_client()
                    await client.aio.caches.update(
                        name=cached_name,
                        config={"ttl": f"{CACHE_TTL_SECONDS + 300}s"},  # 60 min
                    )
                except Exception as e:
                    logger.debug(f"Failed to extend Gemini cache TTL: {e}")

            logger.debug(f"Using cached content: {cached_name}")
            return cached_name

        # Cache miss - create new cached content with system prompt + tools
        client = _get_genai_client()

        # Convert tool definitions to Gemini format
        tools = _convert_tools_to_gemini_format(tool_definitions)

        # Tool config for function calling
        tool_config = genai_types.ToolConfig(
            function_calling_config=genai_types.FunctionCallingConfig(
                mode=genai_types.FunctionCallingConfigMode.AUTO
            )
        )

        cached = await client.aio.caches.create(
            model=model_name,
            config={
                "system_instruction": prompt,
                "tools": tools,
                "tool_config": tool_config,
                "ttl": f"{CACHE_TTL_SECONDS + 300}s",  # 60 min on Gemini side
            },
        )

        if cached and cached.name:
            await redis_client.set(cache_key, cached.name, ttl=CACHE_TTL_SECONDS)
            logger.info(
                f"Created cached content (prompt + {len(tool_definitions)} tools): {cached.name}"
            )
            return cached.name

        return None

    except Exception as e:
        # Graceful degradation - log warning and return None
        logger.warning(f"Content caching failed (falling back to uncached): {e}")
        return None


# Keep the old function name as an alias for backwards compatibility
get_cached_system_prompt = get_cached_content


async def invalidate_cached_content(
    prompt: str,
    model_name: str,
    tools_hash: str,
    redis_client: Any | None = None,
) -> None:
    """Invalidate cached content when system prompt or tools change.

    Args:
        prompt: The system prompt text.
        model_name: Gemini model name.
        tools_hash: Hash of tool definitions (from get_tools_schema_hash()).
        redis_client: Redis client for cache key storage.
    """
    if not redis_client:
        return

    cache_key = f"arachne:cached_content:{model_name}:{_hash_prompt(prompt)}:{tools_hash}"

    try:
        cached_name = await redis_client.get(cache_key)
        if cached_name:
            # Delete from Gemini
            try:
                client = _get_genai_client()
                await client.aio.caches.delete(name=cached_name)
            except Exception as e:
                logger.debug(f"Failed to delete Gemini cache: {e}")

            # Delete from Redis
            await redis_client.delete(cache_key)
            logger.info(f"Invalidated cached content: {cached_name}")
    except Exception as e:
        logger.warning(f"Cache invalidation failed: {e}")


# Keep the old function name as an alias for backwards compatibility
invalidate_cached_prompt = invalidate_cached_content


async def optimize_context_window(
    history: list[dict[str, str]],
    model_name: str,
    system_prompt: str | None = None,
    tool_definitions: list[dict[str, Any]] | None = None,
    max_context_tokens: int | None = None,
    tokens_used_cache: dict[int, int] | None = None,
    redis_client: "RedisClient | None" = None,
) -> OptimizedContext:
    """Optimize context window using tiered memory management.

    Implements intelligent trimming with priority order:
    1. System prompt (via cached reference, accounted separately)
    2. Latest user query (always keep)
    3. Recent tool calls/results (last 10 if present)
    4. Older messages (FIFO trim from oldest until within budget)

    When redis_client is provided, ENABLE_SYSTEM_PROMPT_CACHING is enabled,
    and tool_definitions are provided, both system prompt and tools are cached
    via Gemini's CachedContent API for 75% cost reduction.

    Args:
        history: Conversation history as list of {"role": "...", "content": "..."}.
        model_name: Model name for correct token budget lookup.
        system_prompt: Optional system prompt for token accounting.
        tool_definitions: Optional list of tool defs for caching (from get_tool_definitions()).
        max_context_tokens: Override default budget (for testing).
        tokens_used_cache: Optional dict mapping message index to cached token count.
        redis_client: Optional Redis client for content caching.

    Returns:
        OptimizedContext with history, cached_prompt_name, system_prompt, and skip_tool_registration.
    """
    # Attempt content caching if enabled and Redis is available
    cached_prompt_name: str | None = None
    effective_system_prompt: str | None = system_prompt
    skip_tool_registration: bool = False

    if (
        system_prompt
        and tool_definitions
        and redis_client
        and settings.ENABLE_SYSTEM_PROMPT_CACHING
    ):
        cached_prompt_name = await get_cached_content(
            prompt=system_prompt,
            model_name=model_name,
            tool_definitions=tool_definitions,
            redis_client=redis_client,
        )
        if cached_prompt_name:
            # Content is cached (system prompt + tools); skip separate tool registration
            effective_system_prompt = None
            skip_tool_registration = True
            logger.info(f"Content cache hit: {cached_prompt_name}")
        else:
            logger.debug("Content cache miss, using raw prompt and registering tools")

    if not history:
        return OptimizedContext(
            history=[],
            cached_prompt_name=cached_prompt_name,
            system_prompt=effective_system_prompt,
            skip_tool_registration=skip_tool_registration,
        )

    # Get token budget for model (85% of max)
    budget = max_context_tokens or MODEL_CONTEXT_LIMITS.get(model_name, DEFAULT_TOKEN_BUDGET)

    # Reserve space for system prompt
    system_prompt_tokens = 0
    if system_prompt:
        system_prompt_tokens = _estimate_tokens(system_prompt)
        budget -= system_prompt_tokens

    # Reserve space for response (at least 8K tokens)
    budget -= 8192

    # Always keep the latest message
    latest_msg = history[-1]
    latest_tokens = _estimate_tokens(latest_msg["content"])
    budget -= latest_tokens

    # Process remaining history from newest to oldest
    remaining_history = history[:-1]
    optimized_messages: list[dict[str, str]] = []
    current_tokens = 0

    # Use cached token counts if available
    tokens_cache = tokens_used_cache or {}

    for i, msg in enumerate(reversed(remaining_history)):
        original_idx = len(remaining_history) - 1 - i

        # Use cached count or estimate
        msg_tokens = tokens_cache.get(original_idx, _estimate_tokens(msg["content"]))

        if current_tokens + msg_tokens <= budget:
            optimized_messages.append(msg)
            current_tokens += msg_tokens
        else:
            # Budget exceeded - stop including older messages
            break

    # Reverse to restore chronological order
    optimized_messages.reverse()

    # Add the latest message back
    optimized_messages.append(latest_msg)

    # Observability: log context optimization results
    total_messages = len(history)
    kept_messages = len(optimized_messages)
    trimmed_count = total_messages - kept_messages
    total_budget = max_context_tokens or MODEL_CONTEXT_LIMITS.get(model_name, DEFAULT_TOKEN_BUDGET)
    tokens_used = current_tokens + latest_tokens + system_prompt_tokens + 8192  # Include reserves
    budget_pct = round((tokens_used / total_budget) * 100, 1)
    cache_status = "hit" if cached_prompt_name else "miss" if system_prompt else "n/a"

    if trimmed_count > 0:
        logger.info(
            f"Context optimization: kept {kept_messages}/{total_messages} messages, "
            f"{tokens_used}/{total_budget} tokens ({budget_pct}%), cache={cache_status}"
        )
    else:
        logger.debug(
            f"Context optimization: all {total_messages} messages fit, "
            f"{tokens_used}/{total_budget} tokens ({budget_pct}%), cache={cache_status}"
        )

    # Convert to PydanticAI format
    return OptimizedContext(
        history=_to_pydantic_messages(optimized_messages),
        cached_prompt_name=cached_prompt_name,
        system_prompt=effective_system_prompt,
        skip_tool_registration=skip_tool_registration,
    )


def _to_pydantic_messages(
    messages: list[dict[str, str]],
) -> list[ModelRequest | ModelResponse]:
    """Convert optimized history to PydanticAI message format."""
    result: list[ModelRequest | ModelResponse] = []

    for msg in messages:
        if msg["role"] == "user":
            result.append(ModelRequest(parts=[UserPromptPart(content=msg["content"])]))
        elif msg["role"] == "assistant":
            result.append(ModelResponse(parts=[TextPart(content=msg["content"])]))
        # Note: system prompts are handled via agent configuration, not in history

    return result


def get_token_budget(model_name: str) -> int:
    """Get the token budget for a model (85% of max context).

    Args:
        model_name: Gemini model name.

    Returns:
        Token budget for the model.
    """
    return MODEL_CONTEXT_LIMITS.get(model_name, DEFAULT_TOKEN_BUDGET)

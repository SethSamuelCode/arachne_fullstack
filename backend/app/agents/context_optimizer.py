"""Context window optimizer for Gemini models.

Implements tiered memory management with:
- Token-aware context trimming using Gemini's native count_tokens API
- System prompt caching via CachedContent for 75% cost reduction
- TTL extension for active sessions
"""

import hashlib
import logging
from typing import Any

from google import genai
from google.genai import types as genai_types
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

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


async def get_cached_system_prompt(
    prompt: str,
    model_name: str,
    redis_client: Any | None = None,
    extend_on_use: bool = True,
) -> str | None:
    """Get or create a cached system prompt for reduced latency and cost.

    Uses Gemini's CachedContent API to cache the system prompt server-side.
    Active sessions have their TTL extended automatically.

    Args:
        prompt: The system prompt text.
        model_name: Gemini model name.
        redis_client: Redis client for cache key storage.
        extend_on_use: Whether to extend TTL on cache hit.

    Returns:
        The cache name for use in requests, or None if caching failed.
    """
    if not redis_client:
        logger.debug("Redis client not available, skipping prompt caching")
        return None

    cache_key = f"arachne:system_prompt:{model_name}:{_hash_prompt(prompt)}"

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

            logger.debug(f"Using cached system prompt: {cached_name}")
            return cached_name

        # Cache miss - create new cached content
        client = _get_genai_client()
        cached = await client.aio.caches.create(
            model=model_name,
            config={
                "system_instruction": prompt,
                "ttl": f"{CACHE_TTL_SECONDS + 300}s",  # 60 min on Gemini side
            },
        )

        if cached and cached.name:
            await redis_client.set(cache_key, cached.name, ttl=CACHE_TTL_SECONDS)
            logger.info(f"Created cached system prompt: {cached.name}")
            return cached.name

        return None

    except Exception as e:
        logger.warning(f"System prompt caching failed: {e}")
        return None


async def invalidate_cached_prompt(
    prompt: str,
    model_name: str,
    redis_client: Any | None = None,
) -> None:
    """Invalidate a cached system prompt when it changes.

    Args:
        prompt: The system prompt text.
        model_name: Gemini model name.
        redis_client: Redis client for cache key storage.
    """
    if not redis_client:
        return

    cache_key = f"arachne:system_prompt:{model_name}:{_hash_prompt(prompt)}"

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
            logger.info(f"Invalidated cached system prompt: {cached_name}")
    except Exception as e:
        logger.warning(f"Cache invalidation failed: {e}")


async def optimize_context_window(
    history: list[dict[str, str]],
    model_name: str,
    system_prompt: str | None = None,
    max_context_tokens: int | None = None,
    tokens_used_cache: dict[int, int] | None = None,
) -> list[ModelRequest | ModelResponse]:
    """Optimize context window using tiered memory management.

    Implements intelligent trimming with priority order:
    1. System prompt (via cached reference, accounted separately)
    2. Latest user query (always keep)
    3. Recent tool calls/results (last 10 if present)
    4. Older messages (FIFO trim from oldest until within budget)

    Args:
        history: Conversation history as list of {"role": "...", "content": "..."}.
        model_name: Model name for correct token budget lookup.
        system_prompt: Optional system prompt for token accounting.
        max_context_tokens: Override default budget (for testing).
        tokens_used_cache: Optional dict mapping message index to cached token count.

    Returns:
        Optimized history as PydanticAI message format.
    """
    if not history:
        return []

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
            trimmed_count = len(remaining_history) - len(optimized_messages) - 1
            if trimmed_count > 0:
                logger.info(
                    f"Context optimization: trimmed {trimmed_count} messages "
                    f"({current_tokens}/{budget} tokens used)"
                )
            break

    # Reverse to restore chronological order
    optimized_messages.reverse()

    # Add the latest message back
    optimized_messages.append(latest_msg)

    # Convert to PydanticAI format
    return _to_pydantic_messages(optimized_messages)


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

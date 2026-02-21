"""Cache manager for Gemini CachedContent API.

Handles validation, warming, and invalidation of cached content
(system prompts + tools) for 75% cost reduction.
"""

import logging

from app.clients.redis import RedisClient
from app.core.config import settings

logger = logging.getLogger(__name__)

# Redis key for storing the current tools schema hash
TOOLS_HASH_KEY = "arachne:tools_schema_hash"

# Default sub-agent system prompt (must match tool_register.py)
DEFAULT_SUBAGENT_PROMPT = "You are a helpful AI assistant."

# Global cache for sub-agent cached content names (model -> cached_content_name)
_subagent_cache: dict[str, str] = {}

# Global reference to Redis client (set during initialization)
_global_redis_client: RedisClient | None = None


async def validate_tools_cache(redis_client: RedisClient) -> bool:
    """Validate that cached content is still valid for current tool definitions.

    Compares the stored tools schema hash with the current hash.
    If they differ, invalidates all cached content.

    Args:
        redis_client: Redis client for cache operations.

    Returns:
        True if cache is valid, False if invalidated.
    """
    from app.agents.tools import get_tools_schema_hash

    current_hash = get_tools_schema_hash()
    stored_hash = await redis_client.get(TOOLS_HASH_KEY)

    if stored_hash == current_hash:
        logger.info(f"Tools cache valid (hash: {current_hash})")
        return True

    # Hash mismatch - need to invalidate all cached content
    if stored_hash:
        logger.warning(
            f"Tools schema changed ({stored_hash} -> {current_hash}), "
            "invalidating all cached content"
        )
        await _invalidate_all_cached_content(redis_client)
    else:
        logger.info(f"No stored tools hash, initializing with: {current_hash}")

    # Store the new hash
    await redis_client.set(TOOLS_HASH_KEY, current_hash)
    return False


async def _invalidate_all_cached_content(redis_client: RedisClient) -> None:
    """Invalidate all cached content in Redis and Gemini.

    Scans for all keys matching the cached content pattern and deletes them.
    Also attempts to delete the corresponding Gemini caches.
    """
    from app.agents.context_optimizer import _get_genai_client

    # Scan for all cached content keys
    pattern = "arachne:cached_content:*"
    keys_to_delete: list[str] = []

    try:
        # Get all matching keys using the raw Redis client
        cursor = 0
        while True:
            cursor, keys = await redis_client.raw.scan(cursor=cursor, match=pattern, count=100)
            for key in keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                keys_to_delete.append(key_str)
            if cursor == 0:
                break
    except Exception as e:
        logger.warning(f"Failed to scan Redis keys for invalidation: {e}")
        return

    if not keys_to_delete:
        logger.debug("No cached content keys found to invalidate")
        return

    # Delete each cache

    client = _get_genai_client()
    deleted_count = 0

    for key in keys_to_delete:
        try:
            # Get the Gemini cache name from Redis
            cached_name = await redis_client.get(key)
            if cached_name:
                # Try to delete from Gemini
                try:
                    await client.aio.caches.delete(name=cached_name)
                except Exception as e:
                    logger.debug(f"Failed to delete Gemini cache {cached_name}: {e}")

            # Delete from Redis
            await redis_client.delete(key)
            deleted_count += 1
        except Exception as e:
            logger.warning(f"Failed to delete cache key {key}: {e}")

    logger.info(f"Invalidated {deleted_count} cached content entries")

    # Clear the in-memory sub-agent cache
    _subagent_cache.clear()


async def warm_subagent_cache(
    model_name: str,
    redis_client: RedisClient,
) -> str | None:
    """Pre-create cached content for the default sub-agent prompt.

    This allows spawn_agent calls with the default prompt to benefit
    from caching without waiting for the first cache miss.

    Args:
        model_name: Gemini model name to cache for.
        redis_client: Redis client for cache operations.

    Returns:
        The cached content name, or None if caching failed.
    """
    if not settings.ENABLE_SYSTEM_PROMPT_CACHING:
        logger.debug("System prompt caching disabled, skipping sub-agent cache warming")
        return None

    from app.agents.context_optimizer import get_cached_content
    from app.agents.tools import get_tool_definitions

    tool_definitions = get_tool_definitions()

    cached_name = await get_cached_content(
        prompt=DEFAULT_SUBAGENT_PROMPT,
        model_name=model_name,
        tool_definitions=tool_definitions,
        redis_client=redis_client,
    )

    if cached_name:
        # Store in memory for quick lookup
        _subagent_cache[model_name] = cached_name
        logger.info(f"Warmed sub-agent cache for {model_name}: {cached_name}")

    return cached_name


async def get_subagent_cached_content(model_name: str) -> str | None:
    """Get cached content name for sub-agent with default prompt.

    First checks in-memory cache, then falls back to Redis lookup.

    Args:
        model_name: Gemini model name.

    Returns:
        Cached content name if available, None otherwise.
    """
    if not settings.ENABLE_SYSTEM_PROMPT_CACHING:
        return None

    # Check in-memory cache first
    if model_name in _subagent_cache:
        return _subagent_cache[model_name]

    # Try to get from Redis using the global redis client
    from app.agents.context_optimizer import _hash_prompt
    from app.agents.tools import get_tools_schema_hash

    # Get redis client from global reference (set during lifespan)
    redis_client = _global_redis_client
    if not redis_client:
        return None

    tools_hash = get_tools_schema_hash()
    prompt_hash = _hash_prompt(DEFAULT_SUBAGENT_PROMPT)
    cache_key = f"arachne:cached_content:{model_name}:{prompt_hash}:{tools_hash}"

    try:
        cached_name = await redis_client.get(cache_key)
        if cached_name:
            # Store in memory for next time
            _subagent_cache[model_name] = cached_name
            return cached_name
    except Exception as e:
        logger.debug(f"Failed to get sub-agent cache from Redis: {e}")

    return None


async def initialize_cache_manager(redis_client: RedisClient) -> None:
    """Initialize the cache manager on application startup.

    Validates existing caches and optionally warms sub-agent caches.

    Args:
        redis_client: Redis client for cache operations.
    """
    global _global_redis_client
    _global_redis_client = redis_client

    logger.info("Initializing cache manager...")

    # Validate tools cache (invalidate if tools changed)
    await validate_tools_cache(redis_client)

    if settings.ENABLE_SYSTEM_PROMPT_CACHING:
        # Warm sub-agent caches for common models
        from app.agents.providers.registry import DEFAULT_MODEL_ID

        default_model = DEFAULT_MODEL_ID

        # Only warm if cache was valid or just invalidated (fresh start)
        await warm_subagent_cache(default_model, redis_client)

        logger.info("Cache manager initialized with caching enabled")
    else:
        logger.info("Cache manager initialized (caching disabled)")

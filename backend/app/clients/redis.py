"""Redis client wrapper.

Provides a class-based Redis client for connection management and operations.
"""

from redis import asyncio as aioredis

from app.core.config import settings


class RedisClient:
    """Redis client wrapper for connection lifecycle management.

    Usage in FastAPI lifespan:
        async with contextmanager():
            redis = RedisClient(settings.REDIS_URL)
            await redis.connect()
            yield {"redis": redis}
            await redis.close()
    """

    def __init__(self, url: str | None = None):
        self.url = url or settings.REDIS_URL
        self.client: aioredis.Redis | None = None

    async def connect(self) -> None:
        """Connect to Redis server."""
        self.client = aioredis.from_url(
            self.url,
            encoding="utf-8",
            decode_responses=True,
        )

    async def close(self) -> None:
        """Close Redis connection."""
        if self.client:
            await self.client.close()
            self.client = None

    async def get(self, key: str) -> str | None:
        """Get a value by key."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return await self.client.get(key)

    async def set(
        self,
        key: str,
        value: str,
        ttl: int | None = None,
    ) -> None:
        """Set a value with optional TTL (in seconds)."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        await self.client.set(key, value, ex=ttl)

    async def delete(self, key: str) -> int:
        """Delete a key. Returns number of keys deleted."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return await self.client.delete(key)

    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return bool(await self.client.exists(key))

    async def ping(self) -> bool:
        """Ping Redis server. Returns True if connected."""
        if not self.client:
            return False
        try:
            await self.client.ping()
            return True
        except Exception:
            return False

    async def xadd(self, key: str, fields: dict[str, str]) -> str:
        """Add an entry to a Redis Stream. Returns the stream entry ID."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return await self.client.xadd(key, fields)

    async def xread(
        self,
        streams: dict[str, str],
        block: int | None = None,
        count: int | None = None,
    ) -> list | None:
        """Read from one or more Redis Streams.

        Args:
            streams: Mapping of stream key to last-seen ID (use "0" for start).
            block: Block for this many milliseconds (None = non-blocking).
            count: Max entries to return per stream.

        Returns:
            List of [stream_key, [(id, fields), ...]] or None on timeout.
        """
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return await self.client.xread(streams=streams, block=block, count=count)

    async def expire(self, key: str, seconds: int) -> bool:
        """Set a TTL on a key. Returns True if the timeout was set."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return await self.client.expire(key, seconds)

    async def hset(self, key: str, mapping: dict[str, str]) -> int:
        """Set fields in a hash. Returns number of fields added."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return await self.client.hset(key, mapping=mapping)

    async def hgetall(self, key: str) -> dict[str, str]:
        """Get all fields from a hash."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return await self.client.hgetall(key)

    @property
    def raw(self) -> aioredis.Redis:
        """Access the underlying aioredis client for advanced operations."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return self.client

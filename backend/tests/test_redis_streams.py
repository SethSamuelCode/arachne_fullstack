"""Tests for Redis Stream operations on RedisClient."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.clients.redis import RedisClient


@pytest.fixture
def redis_client():
    """Create a RedisClient with mocked underlying client."""
    client = RedisClient("redis://localhost:6379")
    mock_raw = AsyncMock()
    client.client = mock_raw
    return client, mock_raw


@pytest.mark.anyio
async def test_xadd(redis_client):
    client, mock_raw = redis_client
    mock_raw.xadd = AsyncMock(return_value="1234567890-0")
    result = await client.xadd("stream:key", {"type": "text_delta", "data": '{"content":"hi"}'})
    mock_raw.xadd.assert_called_once_with("stream:key", {"type": "text_delta", "data": '{"content":"hi"}'})
    assert result == "1234567890-0"


@pytest.mark.anyio
async def test_xread_with_block(redis_client):
    client, mock_raw = redis_client
    mock_raw.xread = AsyncMock(return_value=[
        ["stream:key", [("1234-0", {"type": "text_delta", "data": "{}"})]],
    ])
    result = await client.xread({"stream:key": "0"}, block=5000, count=50)
    mock_raw.xread.assert_called_once_with(streams={"stream:key": "0"}, block=5000, count=50)
    assert len(result) == 1


@pytest.mark.anyio
async def test_xread_returns_none_on_timeout(redis_client):
    client, mock_raw = redis_client
    mock_raw.xread = AsyncMock(return_value=None)
    result = await client.xread({"stream:key": "0"}, block=1000)
    assert result is None


@pytest.mark.anyio
async def test_expire(redis_client):
    client, mock_raw = redis_client
    mock_raw.expire = AsyncMock(return_value=True)
    result = await client.expire("stream:key", 3600)
    mock_raw.expire.assert_called_once_with("stream:key", 3600)
    assert result is True


@pytest.mark.anyio
async def test_hset_and_hgetall(redis_client):
    client, mock_raw = redis_client
    mock_raw.hset = AsyncMock()
    mock_raw.hgetall = AsyncMock(return_value={"status": "running", "job_id": "abc"})
    await client.hset("job:meta", mapping={"status": "running", "job_id": "abc"})
    result = await client.hgetall("job:meta")
    assert result["status"] == "running"


@pytest.mark.anyio
async def test_stream_methods_raise_when_not_connected():
    client = RedisClient("redis://localhost:6379")
    with pytest.raises(RuntimeError, match="not connected"):
        await client.xadd("key", {"data": "x"})
    with pytest.raises(RuntimeError, match="not connected"):
        await client.xread({"key": "0"})
    with pytest.raises(RuntimeError, match="not connected"):
        await client.expire("key", 60)

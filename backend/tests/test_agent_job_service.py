"""Tests for AgentJobService."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.agent_job import AgentJobService, JobStatus


@pytest.fixture
def mock_redis():
    mock = MagicMock()
    mock.xadd = AsyncMock(return_value="1234-0")
    mock.hset = AsyncMock()
    mock.hgetall = AsyncMock(return_value={})
    mock.expire = AsyncMock(return_value=True)
    mock.set = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.exists = AsyncMock(return_value=False)
    mock.xread = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def service(mock_redis):
    return AgentJobService(mock_redis)


@pytest.mark.anyio
async def test_create_job(service, mock_redis):
    job_id = "test-job-123"
    await service.create_job(job_id, conversation_id="conv-1", user_id="user-1")
    mock_redis.hset.assert_called_once()
    call_args = mock_redis.hset.call_args
    assert call_args[1]["key"] == f"agent:job:{job_id}:meta"
    mapping = call_args[1]["mapping"]
    assert mapping["status"] == "running"
    assert mapping["conversation_id"] == "conv-1"


@pytest.mark.anyio
async def test_publish_event(service, mock_redis):
    await service.publish_event("job-1", "text_delta", {"content": "hello"})
    mock_redis.xadd.assert_called_once()
    call_args = mock_redis.xadd.call_args[0]
    assert call_args[0] == "agent:job:job-1:events"
    fields = call_args[1]
    assert fields["type"] == "text_delta"
    assert json.loads(fields["data"])["content"] == "hello"


@pytest.mark.anyio
async def test_complete_job_sets_status_and_ttl(service, mock_redis):
    await service.complete_job("job-1", status=JobStatus.COMPLETED)
    mock_redis.hset.assert_called()
    assert mock_redis.expire.call_count == 2  # meta + events


@pytest.mark.anyio
async def test_request_cancellation(service, mock_redis):
    await service.request_cancellation("job-1")
    mock_redis.set.assert_called_once()
    call_args = mock_redis.set.call_args
    assert call_args[0][0] == "agent:job:job-1:cancel"


@pytest.mark.anyio
async def test_is_cancellation_requested(service, mock_redis):
    mock_redis.exists = AsyncMock(return_value=True)
    result = await service.is_cancellation_requested("job-1")
    assert result is True


@pytest.mark.anyio
async def test_get_job_status(service, mock_redis):
    mock_redis.hgetall = AsyncMock(return_value={
        "status": "running",
        "conversation_id": "conv-1",
        "user_id": "user-1",
    })
    status = await service.get_job_status("job-1")
    assert status["status"] == "running"


@pytest.mark.anyio
async def test_get_job_status_not_found(service, mock_redis):
    mock_redis.hgetall = AsyncMock(return_value={})
    status = await service.get_job_status("nonexistent")
    assert status is None


@pytest.mark.anyio
async def test_read_events(service, mock_redis):
    mock_redis.xread = AsyncMock(return_value=[
        ["agent:job:job-1:events", [
            ("1-0", {"type": "text_delta", "data": '{"content":"hi"}'}),
            ("2-0", {"type": "complete", "data": '{}'}),
        ]],
    ])
    events = await service.read_events("job-1", last_id="0", block=5000, count=50)
    assert len(events) == 2
    assert events[0]["stream_id"] == "1-0"
    assert events[0]["type"] == "text_delta"

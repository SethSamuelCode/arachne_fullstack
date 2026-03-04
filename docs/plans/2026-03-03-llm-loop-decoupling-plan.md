# LLM Loop Decoupling Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Decouple the LLM agent execution loop from the WebSocket connection so the agent keeps running when the client disconnects, with Redis Streams for event buffering and SSE for client delivery.

**Architecture:** Client POSTs to start an agent run, which enqueues a Celery task. The Celery worker runs PydanticAI's `agent.iter()` and publishes events to a Redis Stream. A new SSE endpoint reads from the stream and delivers events to the client. Browser-native `Last-Event-ID` provides automatic catch-up on reconnect.

**Tech Stack:** Celery (existing Redis broker), Redis Streams (XADD/XREAD), FastAPI StreamingResponse (SSE), EventSource API (frontend)

**Design doc:** `docs/plans/2026-03-03-llm-loop-decoupling-design.md`

---

## Task 1: Add Redis Stream helper methods to RedisClient

**Files:**
- Modify: `backend/app/clients/redis.py`
- Create: `backend/tests/test_redis_streams.py`

The existing `RedisClient` only exposes basic get/set/delete. We need `xadd`, `xread`, and `expire` for Redis Streams.

**Step 1: Write failing tests for Redis Stream methods**

```python
# backend/tests/test_redis_streams.py
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
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_redis_streams.py -v`
Expected: FAIL — methods `xadd`, `xread`, `expire`, `hset`, `hgetall` don't exist on `RedisClient`

**Step 3: Implement Redis Stream methods**

Add these methods to `RedisClient` in `backend/app/clients/redis.py` after the `ping` method (before the `raw` property):

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_redis_streams.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add backend/app/clients/redis.py backend/tests/test_redis_streams.py
git commit -m "feat: add Redis Stream and hash methods to RedisClient"
```

---

## Task 2: Create the agent job event publisher

**Files:**
- Create: `backend/app/services/agent_job.py`
- Create: `backend/tests/test_agent_job_service.py`

This service encapsulates all Redis Stream operations for agent jobs: publishing events, managing job metadata, checking cancellation.

**Step 1: Write failing tests**

```python
# backend/tests/test_agent_job_service.py
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
    # Should update meta status
    mock_redis.hset.assert_called()
    # Should set TTL on both keys
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
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_agent_job_service.py -v`
Expected: FAIL — module `app.services.agent_job` does not exist

**Step 3: Implement AgentJobService**

```python
# backend/app/services/agent_job.py
"""Agent job management service using Redis Streams."""

import json
import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.clients.redis import RedisClient

logger = logging.getLogger(__name__)

# Redis key prefixes
_EVENTS_KEY = "agent:job:{job_id}:events"
_META_KEY = "agent:job:{job_id}:meta"
_CANCEL_KEY = "agent:job:{job_id}:cancel"

# TTLs
_COMPLETED_JOB_TTL = 3600  # 1 hour
_CANCEL_FLAG_TTL = 300  # 5 minutes


class JobStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentJobService:
    """Manages agent job lifecycle via Redis Streams and hashes."""

    def __init__(self, redis: RedisClient) -> None:
        self.redis = redis

    async def create_job(
        self,
        job_id: str,
        *,
        conversation_id: str,
        user_id: str,
        celery_task_id: str | None = None,
    ) -> None:
        """Initialize job metadata in Redis."""
        meta_key = _META_KEY.format(job_id=job_id)
        await self.redis.hset(
            key=meta_key,
            mapping={
                "status": JobStatus.RUNNING,
                "conversation_id": conversation_id,
                "user_id": user_id,
                "celery_task_id": celery_task_id or "",
                "started_at": datetime.now(UTC).isoformat(),
            },
        )

    async def publish_event(
        self,
        job_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> str:
        """Publish an event to the job's Redis Stream. Returns stream ID."""
        events_key = _EVENTS_KEY.format(job_id=job_id)
        return await self.redis.xadd(
            events_key,
            {"type": event_type, "data": json.dumps(data)},
        )

    async def complete_job(
        self,
        job_id: str,
        *,
        status: JobStatus = JobStatus.COMPLETED,
    ) -> None:
        """Mark a job as complete and set TTLs for cleanup."""
        meta_key = _META_KEY.format(job_id=job_id)
        events_key = _EVENTS_KEY.format(job_id=job_id)

        await self.redis.hset(
            key=meta_key,
            mapping={
                "status": status,
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )
        # Set TTLs for automatic cleanup
        await self.redis.expire(meta_key, _COMPLETED_JOB_TTL)
        await self.redis.expire(events_key, _COMPLETED_JOB_TTL)

    async def request_cancellation(self, job_id: str) -> None:
        """Set the cancellation flag for a job."""
        cancel_key = _CANCEL_KEY.format(job_id=job_id)
        await self.redis.set(cancel_key, "1", ttl=_CANCEL_FLAG_TTL)

    async def is_cancellation_requested(self, job_id: str) -> bool:
        """Check if cancellation has been requested for a job."""
        cancel_key = _CANCEL_KEY.format(job_id=job_id)
        return await self.redis.exists(cancel_key)

    async def get_job_status(self, job_id: str) -> dict[str, str] | None:
        """Get job metadata. Returns None if job not found."""
        meta_key = _META_KEY.format(job_id=job_id)
        meta = await self.redis.hgetall(meta_key)
        return meta if meta else None

    async def read_events(
        self,
        job_id: str,
        *,
        last_id: str = "0",
        block: int | None = None,
        count: int | None = None,
    ) -> list[dict[str, Any]]:
        """Read events from the job's stream after last_id.

        Returns list of dicts with keys: stream_id, type, data.
        """
        events_key = _EVENTS_KEY.format(job_id=job_id)
        result = await self.redis.xread(
            {events_key: last_id},
            block=block,
            count=count,
        )

        if not result:
            return []

        events = []
        for _stream_key, entries in result:
            for stream_id, fields in entries:
                events.append({
                    "stream_id": stream_id,
                    "type": fields["type"],
                    "data": json.loads(fields["data"]) if "data" in fields else {},
                })
        return events
```

**Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_agent_job_service.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add backend/app/services/agent_job.py backend/tests/test_agent_job_service.py
git commit -m "feat: add AgentJobService for Redis Stream event publishing"
```

---

## Task 3: Create the Celery agent task

**Files:**
- Create: `backend/app/worker/tasks/agent_run.py`
- Modify: `backend/app/worker/tasks/__init__.py`
- Create: `backend/tests/test_agent_run_task.py`

This is the core task that runs the PydanticAI agent loop in a Celery worker.

**Step 1: Write failing tests**

```python
# backend/tests/test_agent_run_task.py
"""Tests for the Celery agent run task."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, ANY
from uuid import uuid4


@pytest.mark.anyio
async def test_run_agent_task_publishes_events():
    """Test that the task publishes events to Redis Stream."""
    from app.services.agent_job import AgentJobService

    mock_job_service = MagicMock(spec=AgentJobService)
    mock_job_service.publish_event = AsyncMock()
    mock_job_service.complete_job = AsyncMock()
    mock_job_service.is_cancellation_requested = AsyncMock(return_value=False)
    mock_job_service.create_job = AsyncMock()

    # We test the async inner function directly
    from app.worker.tasks.agent_run import _run_agent_async

    job_id = str(uuid4())
    conversation_id = str(uuid4())

    with (
        patch("app.worker.tasks.agent_run._get_redis_client") as mock_get_redis,
        patch("app.worker.tasks.agent_run.get_agent") as mock_get_agent,
        patch("app.worker.tasks.agent_run.get_provider") as mock_get_provider,
        patch("app.worker.tasks.agent_run.get_db_context") as mock_db_ctx,
        patch("app.worker.tasks.agent_run.AgentJobService", return_value=mock_job_service),
        patch("app.worker.tasks.agent_run.get_conversation_service") as mock_conv_svc,
    ):
        # Mock provider
        mock_provider = MagicMock()
        mock_provider.supports_streaming = False
        mock_get_provider.return_value = mock_provider

        # Mock agent with simple run result
        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.output = "Hello from agent"
        mock_result.all_messages.return_value = []
        mock_agent.agent = MagicMock()
        mock_agent.agent.run = AsyncMock(return_value=mock_result)
        mock_agent.model_name = "test-model"
        mock_get_agent.return_value = mock_agent

        # Mock Redis
        mock_redis = MagicMock()
        mock_redis.connect = AsyncMock()
        mock_redis.close = AsyncMock()
        mock_get_redis.return_value = mock_redis

        # Mock DB context
        mock_db = AsyncMock()
        mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        # Mock conversation service
        mock_svc = MagicMock()
        mock_svc.add_message = AsyncMock()
        mock_svc.generate_and_set_title = AsyncMock(return_value=None)
        mock_conv_svc.return_value = mock_svc

        await _run_agent_async(
            job_id=job_id,
            conversation_id=conversation_id,
            user_id="user-1",
            user_email="test@test.com",
            user_message="Hello",
            model_name="test-model",
            system_prompt="You are helpful",
            message_history=[],
            attachments=[],
        )

        # Verify events were published
        event_calls = mock_job_service.publish_event.call_args_list
        event_types = [call[0][1] for call in event_calls]
        assert "final_result" in event_types
        assert "complete" in event_types

        # Verify job was completed
        mock_job_service.complete_job.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_agent_run_task.py -v`
Expected: FAIL — module `app.worker.tasks.agent_run` does not exist

**Step 3: Implement the Celery task**

```python
# backend/app/worker/tasks/agent_run.py
"""Celery task for running the PydanticAI agent in the background."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from celery import shared_task

from app.agents.assistant import Deps, get_agent
from app.agents.context_optimizer import optimize_context_window
from app.agents.providers.registry import get_provider
from app.agents.tools import get_tool_definitions
from app.clients.redis import RedisClient
from app.core.config import settings
from app.core.utils import serialize_tool_result_for_db
from app.db.session import get_db_context
from app.services.agent_job import AgentJobService, JobStatus

logger = logging.getLogger(__name__)


def _get_redis_client() -> RedisClient:
    """Create a new Redis client for the worker."""
    return RedisClient(settings.REDIS_URL)


def get_conversation_service(db):
    """Get conversation service instance."""
    from app.services.conversation import ConversationService
    from app.repositories.conversation import ConversationRepository

    return ConversationService(ConversationRepository(db))


async def _run_agent_async(
    *,
    job_id: str,
    conversation_id: str,
    user_id: str,
    user_email: str,
    user_message: str,
    model_name: str,
    system_prompt: str,
    message_history: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
) -> None:
    """Async inner function that runs the agent and publishes events."""
    redis = _get_redis_client()
    await redis.connect()

    try:
        job_service = AgentJobService(redis)
        await job_service.create_job(
            job_id,
            conversation_id=conversation_id,
            user_id=user_id,
        )

        provider = get_provider(model_name)
        deps = Deps(user_id=user_id, user_name=user_email)

        # Build multimodal input if attachments present
        from app.api.routes.v1.agent import build_multimodal_input
        from app.schemas.attachment import AttachmentInMessage

        parsed_attachments = [AttachmentInMessage(**a) for a in attachments] if attachments else []
        agent_input = await build_multimodal_input(user_message, parsed_attachments, user_id)

        # Optimize context window
        tool_definitions = get_tool_definitions()
        optimized = await optimize_context_window(
            history=message_history,
            provider=provider,
            system_prompt=system_prompt,
            tool_definitions=tool_definitions,
            redis_client=redis,
        )
        model_history = optimized["history"]

        # Create the agent
        assistant = get_agent(
            system_prompt=optimized["system_prompt"],
            provider=provider,
            cached_prompt_name=optimized["cached_prompt_name"],
            skip_tool_registration=optimized["skip_tool_registration"],
        )

        from pydantic_ai import UsageLimits

        assistant_message_id: UUID | None = None
        tool_call_mapping: dict[str, UUID] = {}
        thinking_content_buffer: list[str] = []

        if not provider.supports_streaming:
            # Non-streaming path
            async with get_db_context() as agent_db:
                deps.db = agent_db
                result = await assistant.agent.run(
                    agent_input,
                    deps=deps,
                    message_history=model_history,
                    usage_limits=UsageLimits(
                        request_limit=settings.AGENT_MAX_REQUESTS,
                        tool_calls_limit=settings.AGENT_MAX_TOOL_CALLS,
                    ),
                )

            await job_service.publish_event(job_id, "model_request_start", {})

            # Walk result messages and publish events
            from pydantic_ai.messages import ModelRequest, ModelResponse, ThinkingPart, ToolCallPart, ToolReturnPart
            from app.api.routes.v1.agent import serialize_tool_content
            from app.schemas.conversation import MessageCreate, ToolCallCreate, ToolCallComplete

            for message in result.all_messages():
                # Check cancellation between messages
                if await job_service.is_cancellation_requested(job_id):
                    await _handle_cancellation(job_service, job_id, conversation_id, assistant_message_id, thinking_content_buffer)
                    return

                if isinstance(message, ModelResponse):
                    for part in message.parts:
                        if isinstance(part, ThinkingPart) and part.content:
                            thinking_content_buffer.append(part.content)
                            if settings.AGENT_STREAM_THINKING:
                                await job_service.publish_event(job_id, "thinking_delta", {"index": 0, "content": part.content})
                        elif isinstance(part, ToolCallPart):
                            args = part.args if isinstance(part.args, dict) else {}
                            await job_service.publish_event(job_id, "tool_call", {
                                "tool_name": part.tool_name,
                                "args": args,
                                "tool_call_id": part.tool_call_id,
                            })
                            # Persist tool call
                            if assistant_message_id is None:
                                async with get_db_context() as db:
                                    conv_svc = get_conversation_service(db)
                                    assistant_msg = await conv_svc.add_message(
                                        UUID(conversation_id),
                                        MessageCreate(role="assistant", content="", model_name=getattr(assistant, "model_name", None)),
                                    )
                                    assistant_message_id = assistant_msg.id
                            async with get_db_context() as db:
                                conv_svc = get_conversation_service(db)
                                tc = await conv_svc.start_tool_call(
                                    assistant_message_id,
                                    ToolCallCreate(tool_call_id=part.tool_call_id, tool_name=part.tool_name, args=args, started_at=datetime.now(UTC)),
                                )
                                tool_call_mapping[part.tool_call_id] = tc.id

                elif isinstance(message, ModelRequest):
                    for part in message.parts:
                        if isinstance(part, ToolReturnPart):
                            content_parts = serialize_tool_content(part.content)
                            await job_service.publish_event(job_id, "tool_result", {
                                "tool_call_id": part.tool_call_id,
                                "content": content_parts,
                            })
                            if part.tool_call_id in tool_call_mapping:
                                db_tc_id = tool_call_mapping[part.tool_call_id]
                                result_text = serialize_tool_result_for_db(part.content)
                                is_error = isinstance(part.content, dict) and part.content.get("error") is True
                                async with get_db_context() as db:
                                    conv_svc = get_conversation_service(db)
                                    await conv_svc.complete_tool_call(
                                        db_tc_id,
                                        ToolCallComplete(result=result_text, completed_at=datetime.now(UTC), success=not is_error),
                                    )

            # Publish final text
            await job_service.publish_event(job_id, "text_delta", {"index": 0, "content": result.output})
            await job_service.publish_event(job_id, "final_result", {"output": result.output})

            # Persist assistant response
            await _persist_result(conversation_id, result.output, assistant_message_id, thinking_content_buffer, getattr(assistant, "model_name", None), user_message, job_service, job_id)

        else:
            # Streaming path
            from pydantic_ai import Agent, PartStartEvent, PartDeltaEvent, FinalResultEvent, FunctionToolCallEvent, FunctionToolResultEvent, TextPartDelta, ThinkingPartDelta, ToolCallPartDelta
            from pydantic_ai.messages import TextPart, ThinkingPart as ThinkingPartMsg
            from app.schemas.conversation import MessageCreate, ToolCallCreate, ToolCallComplete

            async with get_db_context() as agent_db:
                deps.db = agent_db

                async with assistant.agent.iter(
                    agent_input,
                    deps=deps,
                    message_history=model_history,
                    usage_limits=UsageLimits(
                        request_limit=settings.AGENT_MAX_REQUESTS,
                        tool_calls_limit=settings.AGENT_MAX_TOOL_CALLS,
                    ),
                ) as agent_run:
                    async for node in agent_run:
                        # Check cancellation at each node
                        if await job_service.is_cancellation_requested(job_id):
                            await _handle_cancellation(job_service, job_id, conversation_id, assistant_message_id, thinking_content_buffer)
                            return

                        if Agent.is_model_request_node(node):
                            await job_service.publish_event(job_id, "model_request_start", {})

                            async with node.stream(agent_run.ctx) as request_stream:
                                async for event in request_stream:
                                    if isinstance(event, PartStartEvent):
                                        if isinstance(event.part, TextPart) and event.part.content:
                                            await job_service.publish_event(job_id, "text_delta", {"index": event.index, "content": event.part.content})
                                        elif isinstance(event.part, ThinkingPartMsg) and event.part.content:
                                            thinking_content_buffer.append(event.part.content)
                                            if settings.AGENT_STREAM_THINKING:
                                                await job_service.publish_event(job_id, "thinking_delta", {"index": event.index, "content": event.part.content})

                                    elif isinstance(event, PartDeltaEvent):
                                        if isinstance(event.delta, TextPartDelta):
                                            await job_service.publish_event(job_id, "text_delta", {"index": event.index, "content": event.delta.content_delta})
                                        elif isinstance(event.delta, ThinkingPartDelta) and event.delta.content_delta:
                                            thinking_content_buffer.append(event.delta.content_delta)
                                            if settings.AGENT_STREAM_THINKING:
                                                await job_service.publish_event(job_id, "thinking_delta", {"index": event.index, "content": event.delta.content_delta})
                                        elif isinstance(event.delta, ToolCallPartDelta):
                                            await job_service.publish_event(job_id, "tool_call_delta", {"index": event.index, "args_delta": event.delta.args_delta})

                                    elif isinstance(event, FinalResultEvent):
                                        await job_service.publish_event(job_id, "final_result_start", {"tool_name": event.tool_name})

                        elif Agent.is_call_tools_node(node):
                            await job_service.publish_event(job_id, "call_tools_start", {})

                            async with node.stream(agent_run.ctx) as handle_stream:
                                async for event in handle_stream:
                                    if isinstance(event, FunctionToolCallEvent):
                                        await job_service.publish_event(job_id, "tool_call", {
                                            "tool_name": event.part.tool_name,
                                            "args": event.part.args,
                                            "tool_call_id": event.part.tool_call_id,
                                        })
                                        # Persist tool call to DB
                                        if assistant_message_id is None:
                                            async with get_db_context() as db:
                                                conv_svc = get_conversation_service(db)
                                                assistant_msg = await conv_svc.add_message(
                                                    UUID(conversation_id),
                                                    MessageCreate(role="assistant", content="", model_name=getattr(assistant, "model_name", None)),
                                                )
                                                assistant_message_id = assistant_msg.id
                                        async with get_db_context() as db:
                                            conv_svc = get_conversation_service(db)
                                            tc = await conv_svc.start_tool_call(
                                                assistant_message_id,
                                                ToolCallCreate(
                                                    tool_call_id=event.part.tool_call_id,
                                                    tool_name=event.part.tool_name,
                                                    args=event.part.args if isinstance(event.part.args, dict) else {},
                                                    started_at=datetime.now(UTC),
                                                ),
                                            )
                                            tool_call_mapping[event.part.tool_call_id] = tc.id

                                    elif isinstance(event, FunctionToolResultEvent):
                                        content_parts = serialize_tool_content(event.result.content)
                                        await job_service.publish_event(job_id, "tool_result", {
                                            "tool_call_id": event.tool_call_id,
                                            "content": content_parts,
                                        })
                                        if event.tool_call_id in tool_call_mapping:
                                            db_tc_id = tool_call_mapping[event.tool_call_id]
                                            result_text = serialize_tool_result_for_db(event.result.content)
                                            is_error = isinstance(event.result.content, dict) and event.result.content.get("error") is True
                                            async with get_db_context() as db:
                                                conv_svc = get_conversation_service(db)
                                                await conv_svc.complete_tool_call(
                                                    db_tc_id,
                                                    ToolCallComplete(result=result_text, completed_at=datetime.now(UTC), success=not is_error),
                                                )

                        elif Agent.is_end_node(node) and agent_run.result is not None:
                            await job_service.publish_event(job_id, "final_result", {"output": agent_run.result.output})

                # Persist final result
                if agent_run.result:
                    await _persist_result(
                        conversation_id, agent_run.result.output, assistant_message_id,
                        thinking_content_buffer, getattr(assistant, "model_name", None),
                        user_message, job_service, job_id,
                    )
                elif assistant_message_id is not None:
                    # Agent didn't complete but we created a message
                    try:
                        async with get_db_context() as db:
                            from app.repositories.conversation import update_message_content
                            await update_message_content(db, assistant_message_id, "(Tool execution interrupted)")
                    except Exception as e:
                        logger.warning(f"Failed to update interrupted message: {e}")

        # Publish complete event and finalize job
        await job_service.publish_event(job_id, "complete", {"conversation_id": conversation_id})
        await job_service.complete_job(job_id, status=JobStatus.COMPLETED)

    except Exception as e:
        logger.exception(f"Agent run failed for job {job_id}: {e}")
        try:
            await job_service.publish_event(job_id, "error", {"message": str(e)})
            await job_service.complete_job(job_id, status=JobStatus.FAILED)
        except Exception:
            logger.exception("Failed to publish error event")
    finally:
        await redis.close()


async def _handle_cancellation(
    job_service: AgentJobService,
    job_id: str,
    conversation_id: str,
    assistant_message_id: UUID | None,
    thinking_content_buffer: list[str],
) -> None:
    """Handle a cancellation request: persist partial results and notify."""
    logger.info(f"Cancellation requested for job {job_id}")

    if assistant_message_id is not None:
        try:
            async with get_db_context() as db:
                from app.repositories.conversation import update_message_content
                partial_thinking = "".join(thinking_content_buffer) if thinking_content_buffer else None
                await update_message_content(db, assistant_message_id, "(Cancelled by user)", thinking_content=partial_thinking)
        except Exception as e:
            logger.warning(f"Failed to persist partial result on cancel: {e}")

    await job_service.publish_event(job_id, "cancelled", {"conversation_id": conversation_id})
    await job_service.complete_job(job_id, status=JobStatus.CANCELLED)


async def _persist_result(
    conversation_id: str,
    output: str,
    assistant_message_id: UUID | None,
    thinking_content_buffer: list[str],
    model_name: str | None,
    user_message: str,
    job_service: AgentJobService,
    job_id: str,
) -> None:
    """Persist the assistant response and generate title."""
    final_thinking = "".join(thinking_content_buffer) if thinking_content_buffer else None

    try:
        async with get_db_context() as db:
            conv_svc = get_conversation_service(db)
            if assistant_message_id is not None:
                from app.repositories.conversation import update_message_content
                await update_message_content(db, assistant_message_id, output, thinking_content=final_thinking)
            else:
                from app.schemas.conversation import MessageCreate
                await conv_svc.add_message(
                    UUID(conversation_id),
                    MessageCreate(role="assistant", content=output, thinking_content=final_thinking, model_name=model_name),
                )
    except Exception as e:
        logger.warning(f"Failed to persist assistant response: {e}")

    # Generate title
    try:
        async with get_db_context() as db:
            conv_svc = get_conversation_service(db)
            title = await conv_svc.generate_and_set_title(UUID(conversation_id), user_message, output)
            if title:
                await job_service.publish_event(job_id, "conversation_updated", {
                    "conversation_id": conversation_id,
                    "title": title,
                })
    except Exception as e:
        logger.warning(f"Failed to generate conversation title: {e}")


@shared_task(bind=True, name="agent.run", acks_late=True, max_retries=0)
def run_agent_task(
    self,
    job_id: str,
    conversation_id: str,
    user_id: str,
    user_email: str,
    user_message: str,
    model_name: str,
    system_prompt: str,
    message_history: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
) -> dict[str, str]:
    """Celery task wrapper — runs the async agent loop."""
    asyncio.run(
        _run_agent_async(
            job_id=job_id,
            conversation_id=conversation_id,
            user_id=user_id,
            user_email=user_email,
            user_message=user_message,
            model_name=model_name,
            system_prompt=system_prompt,
            message_history=message_history,
            attachments=attachments,
        )
    )
    return {"job_id": job_id, "status": "completed"}
```

**Step 4: Update `__init__.py` to export the new task**

In `backend/app/worker/tasks/__init__.py`, add:

```python
from app.worker.tasks.agent_run import run_agent_task
```

And update `__all__` to include `"run_agent_task"`.

**Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_agent_run_task.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add backend/app/worker/tasks/agent_run.py backend/app/worker/tasks/__init__.py backend/tests/test_agent_run_task.py
git commit -m "feat: add Celery task for background agent execution"
```

---

## Task 4: Add HTTP API endpoints for agent runs

**Files:**
- Modify: `backend/app/api/routes/v1/agent.py`
- Create: `backend/tests/test_agent_run_api.py`

Add POST /agent/run, GET /agent/run/{job_id}/stream (SSE), POST /agent/run/{job_id}/cancel, GET /agent/run/{job_id}/status.

**Step 1: Write failing tests**

```python
# backend/tests/test_agent_run_api.py
"""Tests for agent run HTTP endpoints."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from httpx import AsyncClient, ASGITransport

from app.main import app
from app.api.deps import get_redis, get_db_session, get_current_user
from app.db.models.user import User


@pytest.fixture
def mock_user():
    user = MagicMock(spec=User)
    user.id = uuid4()
    user.email = "test@example.com"
    user.default_model = "gpt-4o-mini"
    user.default_system_prompt = None
    return user


@pytest.fixture
def mock_redis():
    mock = MagicMock()
    mock.hgetall = AsyncMock(return_value={})
    mock.hset = AsyncMock()
    mock.xadd = AsyncMock(return_value="1-0")
    mock.set = AsyncMock()
    mock.exists = AsyncMock(return_value=False)
    mock.expire = AsyncMock(return_value=True)
    mock.xread = AsyncMock(return_value=None)
    return mock


@pytest.fixture
async def client(mock_user, mock_redis, mock_db_session):
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_start_agent_run(client, mock_redis):
    """Test POST /api/v1/agent/run returns 202 with job_id."""
    with patch("app.api.routes.v1.agent.run_agent_task") as mock_task:
        mock_task.delay = MagicMock()
        mock_task.delay.return_value.id = "celery-task-id"

        with patch("app.api.routes.v1.agent.get_conversation_service") as mock_conv:
            mock_svc = MagicMock()
            mock_conv.return_value = mock_svc
            mock_conversation = MagicMock()
            mock_conversation.id = uuid4()
            mock_conversation.system_prompt = "You are helpful"
            mock_svc.create_conversation = AsyncMock(return_value=mock_conversation)
            mock_svc.add_message = AsyncMock()

            response = await client.post("/api/v1/agent/run", json={
                "content": "Hello",
            })

    assert response.status_code == 202
    data = response.json()
    assert "job_id" in data
    assert "conversation_id" in data
    assert "stream_url" in data


@pytest.mark.anyio
async def test_cancel_agent_run(client, mock_redis):
    """Test POST /api/v1/agent/run/{job_id}/cancel."""
    job_id = str(uuid4())
    mock_redis.hgetall = AsyncMock(return_value={
        "status": "running",
        "user_id": str(client._transport._app.dependency_overrides[get_current_user]().id),
    })

    response = await client.post(f"/api/v1/agent/run/{job_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelling"


@pytest.mark.anyio
async def test_cancel_nonexistent_job(client, mock_redis):
    """Test cancel returns 404 for unknown job."""
    mock_redis.hgetall = AsyncMock(return_value={})
    response = await client.post(f"/api/v1/agent/run/{uuid4()}/cancel")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_get_job_status(client, mock_redis):
    """Test GET /api/v1/agent/run/{job_id}/status."""
    job_id = str(uuid4())
    mock_redis.hgetall = AsyncMock(return_value={
        "status": "running",
        "conversation_id": str(uuid4()),
        "user_id": str(client._transport._app.dependency_overrides[get_current_user]().id),
        "started_at": "2026-03-03T00:00:00+00:00",
    })

    response = await client.get(f"/api/v1/agent/run/{job_id}/status")
    assert response.status_code == 200
    assert response.json()["status"] == "running"
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_agent_run_api.py -v`
Expected: FAIL — endpoints don't exist

**Step 3: Add the HTTP endpoints to `agent.py`**

Add these imports at the top of `backend/app/api/routes/v1/agent.py`:

```python
import uuid as uuid_mod
from fastapi import Request
from fastapi.responses import StreamingResponse
from app.api.deps import get_current_user, get_redis
from app.services.agent_job import AgentJobService
from app.worker.tasks.agent_run import run_agent_task
```

Add endpoint schemas (Pydantic models) and the four new route handlers after the existing helper functions but before the `@router.websocket` handler:

```python
from pydantic import BaseModel, Field


class AgentRunRequest(BaseModel):
    """Request body for starting an agent run."""
    conversation_id: str | None = None
    content: str
    model: str | None = None
    system_prompt: str | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class AgentRunResponse(BaseModel):
    """Response from starting an agent run."""
    job_id: str
    conversation_id: str
    stream_url: str


@router.post("/agent/run", status_code=202, response_model=AgentRunResponse)
async def start_agent_run(
    body: AgentRunRequest,
    user: User = Depends(get_current_user),
    redis: RedisClient = Depends(get_redis),
) -> AgentRunResponse:
    """Start a background agent run. Returns job_id and SSE stream URL."""
    job_id = str(uuid_mod.uuid4())
    conversation_history: list[dict[str, str]] = []

    async with get_db_context() as db:
        conv_service_instance = get_conversation_service(db)

        if body.conversation_id:
            # Verify conversation exists and belongs to user
            await conv_service_instance.get_conversation(UUID(body.conversation_id))
            conversation_id = body.conversation_id

            # Restore history
            msgs, total = await conv_service_instance.list_messages(
                UUID(conversation_id), limit=1,
            )
            fetch_limit = 1000
            skip = max(0, total - fetch_limit)
            restored, _ = await conv_service_instance.list_messages(
                UUID(conversation_id), skip=skip, limit=fetch_limit, include_tool_calls=True,
            )
            for msg in restored:
                conversation_history.append({"role": msg.role, "content": msg.content or ""})
        else:
            # Create new conversation
            from app.agents.prompts import DEFAULT_SYSTEM_PROMPT

            conv_system_prompt = body.system_prompt or user.default_system_prompt or DEFAULT_SYSTEM_PROMPT
            from app.schemas.conversation import ConversationCreate

            conv = await conv_service_instance.create_conversation(
                ConversationCreate(user_id=user.id, title=None, system_prompt=conv_system_prompt),
            )
            conversation_id = str(conv.id)

        # Save user message
        await conv_service_instance.add_message(
            UUID(conversation_id), MessageCreate(role="user", content=body.content),
        )

    # Retrieve system prompt
    system_prompt_text: str
    from app.agents.prompts import DEFAULT_SYSTEM_PROMPT

    async with get_db_context() as db:
        conv_service_instance = get_conversation_service(db)
        conv_obj = await conv_service_instance.get_conversation(UUID(conversation_id))
        if conv_obj and conv_obj.system_prompt:
            system_prompt_text = conv_obj.system_prompt
        elif user.default_system_prompt:
            system_prompt_text = user.default_system_prompt
        else:
            system_prompt_text = DEFAULT_SYSTEM_PROMPT

    # Enrich history with tool calls
    from app.api.routes.v1.agent import enrich_history_with_tool_calls
    conversation_history = await enrich_history_with_tool_calls(conversation_history, UUID(conversation_id))

    # Enqueue Celery task
    model_name = body.model or user.default_model or "gpt-4o-mini"
    celery_result = run_agent_task.delay(
        job_id=job_id,
        conversation_id=conversation_id,
        user_id=str(user.id),
        user_email=user.email,
        user_message=body.content,
        model_name=model_name,
        system_prompt=system_prompt_text,
        message_history=conversation_history,
        attachments=[a.model_dump() if hasattr(a, "model_dump") else a for a in body.attachments],
    )

    # Store celery task ID in job meta
    job_service = AgentJobService(redis)
    await job_service.create_job(
        job_id,
        conversation_id=conversation_id,
        user_id=str(user.id),
        celery_task_id=celery_result.id,
    )

    return AgentRunResponse(
        job_id=job_id,
        conversation_id=conversation_id,
        stream_url=f"/api/v1/agent/run/{job_id}/stream",
    )


@router.get("/agent/run/{job_id}/stream")
async def stream_agent_run(
    job_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    redis: RedisClient = Depends(get_redis),
) -> StreamingResponse:
    """SSE endpoint for streaming agent run events. Supports Last-Event-ID for reconnection."""
    job_service = AgentJobService(redis)
    job_meta = await job_service.get_job_status(job_id)

    if not job_meta:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Job not found"}, status_code=404)

    # Verify job belongs to this user
    if job_meta.get("user_id") != str(user.id):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Not authorized"}, status_code=403)

    # Get last event ID from header (browser sends this on reconnect)
    last_event_id = request.headers.get("Last-Event-ID", "0")

    async def event_generator():
        cursor = last_event_id
        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                return

            events = await job_service.read_events(
                job_id, last_id=cursor, block=5000, count=50,
            )

            if events:
                for event in events:
                    cursor = event["stream_id"]
                    yield f"id: {event['stream_id']}\nevent: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"

                    if event["type"] in ("complete", "cancelled", "error"):
                        return
            else:
                # No events — check if job already finished
                meta = await job_service.get_job_status(job_id)
                if meta and meta.get("status") in ("completed", "failed", "cancelled"):
                    return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/agent/run/{job_id}/cancel")
async def cancel_agent_run(
    job_id: str,
    user: User = Depends(get_current_user),
    redis: RedisClient = Depends(get_redis),
):
    """Cancel a running agent job."""
    job_service = AgentJobService(redis)
    job_meta = await job_service.get_job_status(job_id)

    if not job_meta:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Job not found"}, status_code=404)

    if job_meta.get("user_id") != str(user.id):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Not authorized"}, status_code=403)

    await job_service.request_cancellation(job_id)
    return {"status": "cancelling"}


@router.get("/agent/run/{job_id}/status")
async def get_agent_run_status(
    job_id: str,
    user: User = Depends(get_current_user),
    redis: RedisClient = Depends(get_redis),
):
    """Get the status of an agent run."""
    job_service = AgentJobService(redis)
    job_meta = await job_service.get_job_status(job_id)

    if not job_meta:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Job not found"}, status_code=404)

    if job_meta.get("user_id") != str(user.id):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Not authorized"}, status_code=403)

    return job_meta
```

**Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_agent_run_api.py -v`
Expected: All PASS

**Step 5: Run existing tests to verify no regressions**

Run: `cd backend && python -m pytest tests/ -v --ignore=tests/test_agents.py`
Expected: All existing tests still pass

**Step 6: Commit**

```bash
git add backend/app/api/routes/v1/agent.py backend/tests/test_agent_run_api.py
git commit -m "feat: add HTTP endpoints for agent run, stream, cancel, status"
```

---

## Task 5: Add Next.js API route proxies for agent endpoints

**Files:**
- Create: `frontend/src/app/api/agent/run/route.ts`
- Create: `frontend/src/app/api/agent/run/[jobId]/stream/route.ts`
- Create: `frontend/src/app/api/agent/run/[jobId]/cancel/route.ts`
- Create: `frontend/src/app/api/agent/run/[jobId]/status/route.ts`

Next.js API routes proxy requests to the FastAPI backend, handling auth cookies.

**Step 1: Create the POST /api/agent/run proxy**

```typescript
// frontend/src/app/api/agent/run/route.ts
import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError, buildBackendHeaders } from "@/lib/server-api";

export async function POST(request: NextRequest) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    const csrfToken = request.cookies.get("csrf_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    const body = await request.json();

    const data = await backendFetch("/api/v1/agent/run", {
      method: "POST",
      headers: {
        ...buildBackendHeaders(accessToken, csrfToken),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    return NextResponse.json(data, { status: 202 });
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json(
        { detail: error.message || "Failed to start agent run" },
        { status: error.status }
      );
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
```

**Step 2: Create the SSE stream proxy**

```typescript
// frontend/src/app/api/agent/run/[jobId]/stream/route.ts
import { NextRequest } from "next/server";
import { buildBackendHeaders } from "@/lib/server-api";

const BACKEND_URL = process.env.BACKEND_URL || "http://srv.fluffyb.net:8550";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ jobId: string }> }
) {
  const { jobId } = await params;
  const accessToken = request.cookies.get("access_token")?.value;

  if (!accessToken) {
    return new Response(JSON.stringify({ detail: "Not authenticated" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  const headers: Record<string, string> = {
    ...buildBackendHeaders(accessToken),
    Accept: "text/event-stream",
  };

  // Forward Last-Event-ID header for reconnection
  const lastEventId = request.headers.get("Last-Event-ID");
  if (lastEventId) {
    headers["Last-Event-ID"] = lastEventId;
  }

  const backendResponse = await fetch(
    `${BACKEND_URL}/api/v1/agent/run/${jobId}/stream`,
    { headers }
  );

  if (!backendResponse.ok) {
    const errorData = await backendResponse.json().catch(() => ({}));
    return new Response(JSON.stringify(errorData), {
      status: backendResponse.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  // Pass through the SSE stream
  return new Response(backendResponse.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
```

**Step 3: Create cancel and status proxies**

```typescript
// frontend/src/app/api/agent/run/[jobId]/cancel/route.ts
import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError, buildBackendHeaders } from "@/lib/server-api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ jobId: string }> }
) {
  try {
    const { jobId } = await params;
    const accessToken = request.cookies.get("access_token")?.value;
    const csrfToken = request.cookies.get("csrf_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    const data = await backendFetch(`/api/v1/agent/run/${jobId}/cancel`, {
      method: "POST",
      headers: buildBackendHeaders(accessToken, csrfToken),
    });

    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json(
        { detail: error.message || "Failed to cancel" },
        { status: error.status }
      );
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
```

```typescript
// frontend/src/app/api/agent/run/[jobId]/status/route.ts
import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError, buildBackendHeaders } from "@/lib/server-api";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ jobId: string }> }
) {
  try {
    const { jobId } = await params;
    const accessToken = request.cookies.get("access_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    const data = await backendFetch(`/api/v1/agent/run/${jobId}/status`, {
      headers: buildBackendHeaders(accessToken),
    });

    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json(
        { detail: error.message || "Failed to get status" },
        { status: error.status }
      );
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
```

**Step 4: Commit**

```bash
git add frontend/src/app/api/agent/
git commit -m "feat: add Next.js API route proxies for agent run endpoints"
```

---

## Task 6: Create the SSE-based chat hook

**Files:**
- Create: `frontend/src/hooks/use-agent-run.ts`
- Modify: `frontend/src/types/chat.ts` (add new event types)

**Step 1: Update chat types**

Add `"cancelled"` to `WSEventType` in `frontend/src/types/chat.ts`:

```typescript
// Add to WSEventType union:
| "cancelled"
```

**Step 2: Create the new hook**

```typescript
// frontend/src/hooks/use-agent-run.ts
"use client";

import { useCallback, useRef, useState } from "react";
import { nanoid } from "nanoid";
import { useChatStore, useConversationStore } from "@/stores";
import { apiClient } from "@/lib/api-client";
import type { ChatMessage, ChatAttachment, ToolCall } from "@/types";

interface UseAgentRunOptions {
  conversationId?: string | null;
  onConversationCreated?: (conversationId: string) => void;
  ensureConversation?: () => Promise<string | null>;
}

interface AgentRunResponse {
  job_id: string;
  conversation_id: string;
  stream_url: string;
}

interface SSEEvent {
  type: string;
  data: Record<string, unknown>;
  id?: string;
}

/**
 * Attachment payload format sent to backend.
 * Matches backend AttachmentInMessage schema.
 */
interface AttachmentPayload {
  s3_key: string;
  mime_type: string;
  size_bytes: number;
  filename?: string;
}

export function useAgentRun(options: UseAgentRunOptions = {}) {
  const { conversationId, onConversationCreated, ensureConversation } = options;
  const { setCurrentConversationId } = useConversationStore();
  const {
    messages,
    addMessage,
    updateMessage,
    addToolCall,
    updateToolCall,
    clearMessages,
  } = useChatStore();

  const [isProcessing, setIsProcessing] = useState(false);
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const currentMessageIdRef = useRef<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  const handleSSEEvent = useCallback(
    (event: SSEEvent) => {
      const currentMessageId = currentMessageIdRef.current;

      switch (event.type) {
        case "conversation_created": {
          const { conversation_id } = event.data as { conversation_id: string };
          setCurrentConversationId(conversation_id);
          onConversationCreated?.(conversation_id);
          break;
        }

        case "conversation_updated": {
          const { conversation_id, title } = event.data as {
            conversation_id: string;
            title: string;
          };
          useConversationStore.getState().updateConversation(conversation_id, { title });
          break;
        }

        case "model_request_start": {
          const newMsgId = nanoid();
          currentMessageIdRef.current = newMsgId;
          addMessage({
            id: newMsgId,
            role: "assistant",
            content: "",
            timestamp: new Date(),
            isStreaming: true,
            isThinkingStreaming: false,
            thinkingContent: "",
            toolCalls: [],
          });
          break;
        }

        case "thinking_delta": {
          if (currentMessageId) {
            const content = (event.data as { content: string }).content;
            updateMessage(currentMessageId, (msg) => ({
              ...msg,
              thinkingContent: (msg.thinkingContent || "") + content,
              isThinkingStreaming: true,
            }));
          }
          break;
        }

        case "text_delta": {
          if (currentMessageId) {
            const content = (event.data as { content: string }).content;
            updateMessage(currentMessageId, (msg) => ({
              ...msg,
              content: msg.content + content,
            }));
          }
          break;
        }

        case "tool_call": {
          if (currentMessageId) {
            const { tool_name, args, tool_call_id } = event.data as {
              tool_name: string;
              args: Record<string, unknown>;
              tool_call_id: string;
            };
            const toolCall: ToolCall = {
              id: tool_call_id,
              name: tool_name,
              args,
              status: "running",
            };
            addToolCall(currentMessageId, toolCall);
          }
          break;
        }

        case "tool_result": {
          if (currentMessageId) {
            const { tool_call_id, content } = event.data as {
              tool_call_id: string;
              content: string;
            };
            updateToolCall(currentMessageId, tool_call_id, {
              result: content,
              status: "completed",
            });
          }
          break;
        }

        case "final_result": {
          if (currentMessageId) {
            updateMessage(currentMessageId, (msg) => ({
              ...msg,
              isStreaming: false,
              isThinkingStreaming: false,
            }));
          }
          break;
        }

        case "error": {
          if (currentMessageId) {
            updateMessage(currentMessageId, (msg) => ({
              ...msg,
              content: msg.content + "\n\n[Error occurred]",
              isStreaming: false,
            }));
          }
          cleanup();
          break;
        }

        case "cancelled": {
          if (currentMessageId) {
            updateMessage(currentMessageId, (msg) => ({
              ...msg,
              content: msg.content + "\n\n[Cancelled]",
              isStreaming: false,
            }));
          }
          cleanup();
          break;
        }

        case "complete": {
          cleanup();
          break;
        }
      }
    },
    [addMessage, updateMessage, addToolCall, updateToolCall, setCurrentConversationId, onConversationCreated]
  );

  const cleanup = useCallback(() => {
    setIsProcessing(false);
    setCurrentJobId(null);
    currentMessageIdRef.current = null;
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  const connectToStream = useCallback(
    (streamUrl: string) => {
      const eventSource = new EventSource(`/api${streamUrl}`, {
        withCredentials: true,
      });
      eventSourceRef.current = eventSource;

      // Listen for all event types
      const eventTypes = [
        "conversation_created", "conversation_updated",
        "model_request_start", "thinking_delta", "text_delta",
        "tool_call_delta", "call_tools_start",
        "tool_call", "tool_result",
        "final_result_start", "final_result",
        "complete", "cancelled", "error",
      ];

      for (const type of eventTypes) {
        eventSource.addEventListener(type, (e: MessageEvent) => {
          try {
            const data = JSON.parse(e.data);
            handleSSEEvent({ type, data, id: e.lastEventId });
          } catch {
            handleSSEEvent({ type, data: {}, id: e.lastEventId });
          }
        });
      }

      eventSource.onerror = () => {
        // EventSource auto-reconnects with Last-Event-ID.
        // If the job is done, the reconnect will get a 404 and stop.
        console.warn("SSE connection error, auto-reconnecting...");
      };
    },
    [handleSSEEvent]
  );

  const sendMessage = useCallback(
    async (content: string, attachments?: ChatAttachment[], systemPrompt?: string) => {
      // Ensure a conversation exists before sending
      let activeConversationId = conversationId || null;
      if (!activeConversationId && ensureConversation) {
        activeConversationId = await ensureConversation();
      }

      // Only include uploaded attachments
      const uploadedAttachments = attachments?.filter((a) => a.status === "uploaded") || [];

      // Add user message to local store
      const userMessage: ChatMessage = {
        id: nanoid(),
        role: "user",
        content,
        timestamp: new Date(),
        attachments: uploadedAttachments.length > 0 ? uploadedAttachments : undefined,
      };
      addMessage(userMessage);

      // Build attachment payload
      const attachmentPayloads: AttachmentPayload[] = uploadedAttachments.map((a) => ({
        s3_key: a.s3Key,
        mime_type: a.mimeType,
        size_bytes: a.sizeBytes,
        filename: a.filename,
      }));

      setIsProcessing(true);

      try {
        // Start agent run via HTTP POST
        const response = await apiClient.post<AgentRunResponse>("/agent/run", {
          content,
          conversation_id: activeConversationId,
          system_prompt: systemPrompt,
          attachments: attachmentPayloads.length > 0 ? attachmentPayloads : undefined,
        });

        setCurrentJobId(response.job_id);

        // If this created a new conversation, notify
        if (!activeConversationId && response.conversation_id) {
          setCurrentConversationId(response.conversation_id);
          onConversationCreated?.(response.conversation_id);
        }

        // Connect to SSE stream
        connectToStream(response.stream_url);
      } catch (error) {
        console.error("Failed to start agent run:", error);
        setIsProcessing(false);
      }
    },
    [addMessage, conversationId, ensureConversation, connectToStream, setCurrentConversationId, onConversationCreated]
  );

  const cancelRun = useCallback(async () => {
    if (!currentJobId) return;
    try {
      await apiClient.post(`/agent/run/${currentJobId}/cancel`);
    } catch (error) {
      console.error("Failed to cancel agent run:", error);
    }
  }, [currentJobId]);

  return {
    messages,
    isProcessing,
    sendMessage,
    cancelRun,
    clearMessages,
    currentJobId,
  };
}
```

**Step 3: Commit**

```bash
git add frontend/src/hooks/use-agent-run.ts frontend/src/types/chat.ts
git commit -m "feat: add SSE-based useAgentRun hook for decoupled chat"
```

---

## Task 7: Integrate the new hook into the chat UI

**Files:**
- Modify: `frontend/src/components/chat/chat-container.tsx` (or wherever `useChat` is consumed)
- Find the component that uses `useChat` and switch it to `useAgentRun`

**Step 1: Find where useChat is consumed**

Run: `grep -rn "useChat" frontend/src/components/ frontend/src/app/`
Identify the component(s) that import and call `useChat()`.

**Step 2: Replace useChat with useAgentRun**

In each consuming component:

1. Change import from `use-chat` to `use-agent-run`
2. Replace `useChat(...)` call with `useAgentRun(...)`
3. Remove `isConnected`, `connect`, `disconnect` from destructured return (no longer needed)
4. Add `cancelRun` to destructured return
5. Add a cancel button that calls `cancelRun()` when `isProcessing` is true
6. Disable the input field while `isProcessing` is true

**Step 3: Verify the UI works**

Start the dev stack (`make docker-up`) and test:
1. Send a message — should POST and start SSE stream
2. Receive streaming response — text should appear incrementally
3. Cancel mid-run — should stop the agent
4. Refresh page during agent run — agent should keep running, conversation shows final result on reload

**Step 4: Commit**

```bash
git add frontend/src/components/chat/
git commit -m "feat: switch chat UI from WebSocket to SSE-based agent runs"
```

---

## Task 8: Deprecate the WebSocket agent handler

**Files:**
- Modify: `backend/app/api/routes/v1/agent.py`

**Step 1: Add deprecation warning to WebSocket handler**

Add a log warning at the top of `agent_websocket()`:

```python
logger.warning("WebSocket agent handler is deprecated. Use POST /agent/run + SSE instead.")
```

**Step 2: Remove WebSocket URL from frontend constants**

In `frontend/src/lib/constants.ts`, remove or comment out `WS_URL` if no longer used elsewhere.

**Step 3: Clean up unused imports in frontend**

Remove `use-websocket` import from `use-chat.ts` if `use-chat.ts` is no longer used.

**Step 4: Commit**

```bash
git add backend/app/api/routes/v1/agent.py frontend/src/lib/constants.ts
git commit -m "chore: deprecate WebSocket agent handler in favor of SSE"
```

---

## Task 9: End-to-end integration testing

**Files:**
- Create: `backend/tests/test_agent_run_integration.py`

**Step 1: Write integration test for the full flow**

```python
# backend/tests/test_agent_run_integration.py
"""Integration tests for the agent run flow (POST -> Celery -> SSE)."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from httpx import AsyncClient, ASGITransport

from app.main import app
from app.api.deps import get_redis, get_db_session, get_current_user
from app.db.models.user import User
from app.services.agent_job import AgentJobService, JobStatus


@pytest.fixture
def mock_user():
    user = MagicMock(spec=User)
    user.id = uuid4()
    user.email = "test@example.com"
    user.default_model = "gpt-4o-mini"
    user.default_system_prompt = None
    return user


@pytest.fixture
def mock_redis():
    """Mock Redis with stream support."""
    mock = MagicMock()
    mock.hgetall = AsyncMock(return_value={})
    mock.hset = AsyncMock()
    mock.xadd = AsyncMock(return_value="1-0")
    mock.set = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.exists = AsyncMock(return_value=False)
    mock.expire = AsyncMock(return_value=True)
    mock.xread = AsyncMock(return_value=None)
    return mock


@pytest.mark.anyio
async def test_full_agent_run_lifecycle(mock_user, mock_redis, mock_db_session):
    """Test: POST to start -> check status -> cancel -> verify cancelled."""
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. Start a run
            with patch("app.api.routes.v1.agent.run_agent_task") as mock_task:
                mock_task.delay = MagicMock()
                mock_task.delay.return_value.id = "celery-id"

                with patch("app.api.routes.v1.agent.get_conversation_service") as mock_conv:
                    mock_svc = MagicMock()
                    mock_conv.return_value = mock_svc
                    mock_conversation = MagicMock()
                    mock_conversation.id = uuid4()
                    mock_conversation.system_prompt = "test prompt"
                    mock_svc.create_conversation = AsyncMock(return_value=mock_conversation)
                    mock_svc.add_message = AsyncMock()

                    response = await client.post("/api/v1/agent/run", json={"content": "Hello"})

            assert response.status_code == 202
            job_id = response.json()["job_id"]

            # 2. Check status
            mock_redis.hgetall = AsyncMock(return_value={
                "status": "running",
                "user_id": str(mock_user.id),
                "conversation_id": str(uuid4()),
            })
            status_response = await client.get(f"/api/v1/agent/run/{job_id}/status")
            assert status_response.status_code == 200
            assert status_response.json()["status"] == "running"

            # 3. Cancel
            cancel_response = await client.post(f"/api/v1/agent/run/{job_id}/cancel")
            assert cancel_response.status_code == 200
            assert cancel_response.json()["status"] == "cancelling"
    finally:
        app.dependency_overrides.clear()
```

**Step 2: Run integration tests**

Run: `cd backend && python -m pytest tests/test_agent_run_integration.py -v`
Expected: All PASS

**Step 3: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests pass (except pre-existing known failure `test_sanitize_preserves_required_fields`)

**Step 4: Commit**

```bash
git add backend/tests/test_agent_run_integration.py
git commit -m "test: add integration tests for agent run lifecycle"
```

---

## Summary of all files changed

### New files:
- `backend/app/services/agent_job.py` — AgentJobService (Redis Streams)
- `backend/app/worker/tasks/agent_run.py` — Celery task
- `backend/tests/test_redis_streams.py` — Redis Stream method tests
- `backend/tests/test_agent_job_service.py` — AgentJobService tests
- `backend/tests/test_agent_run_task.py` — Celery task tests
- `backend/tests/test_agent_run_api.py` — API endpoint tests
- `backend/tests/test_agent_run_integration.py` — Integration tests
- `frontend/src/hooks/use-agent-run.ts` — SSE-based chat hook
- `frontend/src/app/api/agent/run/route.ts` — Next.js proxy
- `frontend/src/app/api/agent/run/[jobId]/stream/route.ts` — SSE proxy
- `frontend/src/app/api/agent/run/[jobId]/cancel/route.ts` — Cancel proxy
- `frontend/src/app/api/agent/run/[jobId]/status/route.ts` — Status proxy

### Modified files:
- `backend/app/clients/redis.py` — Add stream/hash methods
- `backend/app/worker/tasks/__init__.py` — Export new task
- `backend/app/api/routes/v1/agent.py` — Add HTTP endpoints, deprecate WS
- `frontend/src/types/chat.ts` — Add "cancelled" event type
- `frontend/src/components/chat/chat-container.tsx` — Switch to useAgentRun
- `frontend/src/lib/constants.ts` — Remove/deprecate WS_URL

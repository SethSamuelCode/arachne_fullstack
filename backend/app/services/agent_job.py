"""Agent job management service using Redis Streams."""

import json
import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.clients.redis import RedisClient

logger = logging.getLogger(__name__)

# Redis key templates
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

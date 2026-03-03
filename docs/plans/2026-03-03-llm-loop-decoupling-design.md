# LLM Loop Decoupling Design

**Date:** 2026-03-03
**Status:** Approved
**Branch:** feat/improve-llm-handling

## Problem

The LLM/agent execution loop is currently tied to the WebSocket connection. If the client disconnects (network drop, tab close, mobile switch), the agent run dies immediately. Partial results may be lost, and there's no way to reconnect and resume.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Execution host | Celery worker | Infra already configured (Redis broker, late ACK, prefetch=1). Independent scaling. |
| Event buffer | Redis Streams | Native support for consumer catch-up via stream IDs. Built-in ordering and TTL. |
| Client transport | SSE + HTTP POST | Browser-native `Last-Event-ID` reconnect. Simpler than WebSocket for unidirectional streaming. |
| Reconnect behavior | Catch-up + live | Client replays missed events on reconnect, then continues live. |
| Concurrency | Block input | Frontend disables input while agent runs. User must wait or cancel. |
| Cancellation | Cooperative | Worker checks Redis flag between steps. Persists partial results on cancel. |

## Architecture

```
┌─────────┐  POST /agent/run   ┌──────────┐  enqueue    ┌──────────────┐
│  Client  │ ─────────────────→ │ FastAPI  │ ──────────→ │ Celery Worker│
│ (React)  │                    │          │             │              │
│          │  ← 202 {job_id}   │          │             │  PydanticAI  │
│          │                    │          │             │  agent.iter()│
│          │  GET /agent/run/   │          │  XADD       │      │       │
│          │  {job_id}/stream   │  XREAD   │ ←───────────│  publish     │
│          │  Accept: text/     │  ───→    │             │  events to   │
│          │  event-stream      │          │             │  Redis Stream│
│          │  ← SSE events     │          │             │              │
└─────────┘                    └──────────┘             └──────────────┘
                                                               │
                                                         ┌─────┴─────┐
                                                         │ PostgreSQL│
                                                         │ (persist  │
                                                         │  messages)│
                                                         └───────────┘
```

### Cancellation Flow

```
Client  ──POST /agent/run/{job_id}/cancel──→  FastAPI
                                                 │
                                          1. Set Redis cancel flag
                                          2. Worker detects at next breakpoint
                                          3. Worker persists partial results
                                          4. Worker publishes {type: "cancelled"}
                                                 │
Client  ←── SSE: {type: "cancelled"} ──────────┘
```

## API Endpoints

### POST /api/v1/agent/run — Start agent run

Request:
```json
{
    "conversation_id": "uuid | null",
    "content": "string",
    "model": "string | null",
    "system_prompt": "string | null",
    "attachments": [...]
}
```

Response (202 Accepted):
```json
{
    "job_id": "uuid",
    "conversation_id": "uuid",
    "stream_url": "/api/v1/agent/run/{job_id}/stream"
}
```

### GET /api/v1/agent/run/{job_id}/stream — SSE event stream

- Content-Type: `text/event-stream`
- Supports `Last-Event-ID` header for reconnection
- Each event: `id: <stream_id>\nevent: <type>\ndata: <json>\n\n`
- Closes on terminal events (`complete`, `cancelled`, `error`)

### POST /api/v1/agent/run/{job_id}/cancel — Cancel running job

Response: `200 {status: "cancelling"}` or `404`

### GET /api/v1/agent/run/{job_id}/status — Poll job status

Response:
```json
{
    "status": "running | completed | failed | cancelled",
    "conversation_id": "uuid",
    "events_count": 42,
    "started_at": "iso8601",
    "completed_at": "iso8601 | null"
}
```

## Redis Stream Events

Stream key: `agent:job:{job_id}:events`

| Event Type | Data Fields |
|------------|-------------|
| `thinking_delta` | `{content}` |
| `text_delta` | `{content}` |
| `tool_call` | `{id, name, args}` |
| `tool_result` | `{id, name, result, duration_ms}` |
| `final_result` | `{message_id, content, tokens_used}` |
| `complete` | `{conversation_id}` |
| `cancelled` | `{partial_content}` |
| `error` | `{message, code}` |

## Celery Task Design

**File:** `backend/app/worker/tasks/agent_run.py`

```python
@celery_app.task(bind=True, name="agent.run", acks_late=True, max_retries=0)
def run_agent(self, job_id, conversation_id, user_message_id,
              model_name, system_prompt, message_history, ...):
```

- **Sync wrapper + async internals**: `asyncio.run()` inside the task to run async PydanticAI agent
- **Event publishing**: Each PydanticAI event → `XADD` to Redis Stream
- **Cancellation check**: Between each agent iteration step, check `agent:job:{job_id}:cancel` key
- **DB persistence**: Tool calls inline, assistant message on completion, partial on cancel
- **Job metadata**: Redis hash `agent:job:{job_id}:meta` with status, timestamps, task ID

## Redis Key Layout

| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `agent:job:{job_id}:events` | Stream | 1h after completion | Event buffer for SSE |
| `agent:job:{job_id}:meta` | Hash | 1h after completion | Job status and metadata |
| `agent:job:{job_id}:cancel` | String | 5 min | Cancellation flag |

## SSE Endpoint Design

```python
async def event_generator(job_id, last_event_id, redis):
    cursor = last_event_id or "0"
    while True:
        events = await redis.xread(
            {"agent:job:{job_id}:events": cursor},
            block=5000, count=50
        )
        if events:
            for stream_id, event_data in events:
                cursor = stream_id
                yield f"id: {stream_id}\nevent: {event_data['type']}\ndata: {json.dumps(event_data)}\n\n"
                if event_data["type"] in ("complete", "cancelled", "error"):
                    return
        if await request.is_disconnected():
            return
        # Check if job finished and we missed terminal event
        job_meta = await redis.hgetall(f"agent:job:{job_id}:meta")
        if job_meta.get("status") in ("completed", "failed", "cancelled"):
            return
```

## Frontend Changes

### New hook: `use-agent-run.ts`

Replaces WebSocket-based chat messaging:

- `startRun(message, conversationId?)` → POST + open EventSource
- `cancelRun(jobId)` → POST cancel endpoint
- EventSource handles `text_delta`, `thinking_delta`, `tool_call`, `tool_result`, `complete`, `cancelled`, `error`
- Auto-reconnect with `Last-Event-ID` is handled natively by `EventSource`
- Input disabled while `jobId` is active

### Auth

SSE uses HTTP-only cookies (same as other API routes). Native `EventSource` with `withCredentials: true` works without custom headers.

## Error Handling

| Scenario | Handling |
|----------|----------|
| Worker crashes mid-run | `acks_late=True` re-delivers task. New worker detects existing stream, handles idempotently. |
| Client never connects to SSE | Agent runs to completion. Results in DB. Stream expires after 1h. |
| Multiple SSE connections to same job | Allowed — each reader has independent cursor. |
| Job expired / not found | SSE returns 404. Client loads conversation from DB. |
| DB failure in worker | Retry 3x with backoff. On final failure, publish `error` event. |
| Redis Stream cleanup | `EXPIRE` set on stream + meta after terminal event. |

## Migration Strategy

1. Build new endpoints and Celery task alongside existing WebSocket handler
2. Update frontend to use SSE-based hook
3. Deprecate WebSocket agent handler
4. Remove WebSocket handler after transition period

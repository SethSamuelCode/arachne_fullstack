# LLM Agent Execution Loop - Current Architecture & Decoupling Findings

## 1. WebSocket Handler (`backend/app/api/routes/v1/agent.py`)

### Main Handler: `agent_websocket()`
- **Location**: `@router.websocket("/ws/agent")` at line 565
- **Purpose**: Real-time AI agent chat with full event streaming
- **Current Coupling**: Agent execution is completely blocking within the WebSocket connection

### Connection Flow:
1. Client connects via WebSocket at `/api/v1/ws/agent`
2. `AgentConnectionManager` accepts and tracks connection
3. Loop waits for incoming JSON messages with format:
   ```json
   {
     "message": "user message",
     "conversation_id": "optional-uuid",
     "system_prompt": "optional",
     "attachments": [...],
     "history": [...]
   }
   ```

### Key Current Operations:
- **Message Reception** (line ~700): `data = await websocket.receive_json()`
- **Conversation Management**: Creates/retrieves conversation from DB, saves user message
- **Context Optimization**: Retrieves up to last 1000 messages from DB for context window
- **Provider Resolution**: Gets model provider (Gemini, OpenAI, Vertex AI)
- **Agent Execution**: Two branching paths:

#### Path 1: Streaming (default, lines ~820+)
- Uses `async with assistant.agent.iter(...)` for streaming events
- Wraps in `async with get_db_context() as agent_db:` for database access
- Event loop processes:
  - `PartStartEvent` → `text_delta`, `thinking_delta`
  - `PartDeltaEvent` → streaming text/thinking/tool deltas
  - `FunctionToolCallEvent` → tool invocation (persists to DB)
  - `FunctionToolResultEvent` → tool result (persists to DB)
- **CRITICAL**: All events sent to client via `manager.send_event(websocket, event_type, data)`
- **CRITICAL**: Agent DB context lives for entire iteration

#### Path 2: Non-Streaming (line 824, for providers without streaming support)
- Uses `_run_agent_non_streaming()` helper (line 383)
- Calls `agent.run()` for full result, then emulates streaming events to client
- Same event types sent to client

### Message Persistence:
- User message: Saved at line ~737
- Tool call start: Saved inline within streaming loop (line ~1012)
- Tool call result: Saved inline within streaming loop (line ~1062)
- Assistant response: Saved after agent completion via `_persist_assistant_result()` (line 313)
  - Updates existing message if tools were used
  - Creates new message if no tools
  - Also generates conversation title

### Disconnection Handling:
- `WebSocketDisconnect` caught at line 1192 during processing → logs and breaks
- `finally` block: `manager.disconnect(websocket)` at line 1202
- **Problem**: If client disconnects while agent is running, execution stops

## 2. Agent Execution (`backend/app/agents/assistant.py`)

### Core Classes:
- **`AssistantAgent`**: Wrapper around PydanticAI agent
- **`Deps`**: Runtime dependencies injected into agent (from `app/schemas/assistant.py`)

### Two Execution Methods:

#### `run()` method (line ~80)
- Non-streaming: `result = await self.agent.run(user_input, deps=agent_deps, message_history=model_history)`
- Returns: `(output_text, tool_events, deps)`
- Blocks until complete

#### `iter()` method (line ~110)
- Streaming: `async with self.agent.iter(...)` context manager
- Yields events for streaming to client
- Wraps in `UsageLimits` for controlling tool chains:
  - `request_limit`: Max model requests (default 100)
  - `tool_calls_limit`: Max tool calls (default 200)

### Provider Abstraction:
- Delegates model creation to `ModelProvider.create_pydantic_model()`
- Provider can supply cached prompt name for system prompt caching
- Provider specifies `supports_streaming` boolean

### Tool Registration:
- `register_tools(agent)` called after agent creation
- Tools always registered locally (even if cached in API) so PydanticAI can handle responses

## 3. Celery Infrastructure (`backend/app/worker/celery_app.py`)

### Configuration:
- **Broker**: Redis (via `settings.CELERY_BROKER_URL` = `REDIS_URL`)
- **Backend**: Redis (via `settings.CELERY_RESULT_BACKEND` = `REDIS_URL`)
- **Serializer**: JSON
- **Timezone**: Pacific/Auckland
- **Task ACK**: Late ACK (`task_acks_late=True`) - task acked after completion
- **Concurrency**: 4 workers default
- **Result TTL**: 1 hour

### Task Configuration:
- `task_serializer="json"`
- `task_reject_on_worker_lost=True` → task requeued if worker dies
- `worker_prefetch_multiplier=1` → worker takes 1 task at a time (good for long-running tasks)

### Autodiscovery:
- Tasks auto-discovered from `app.worker.tasks` module

### Beat Schedule:
- Example periodic task runs every 60 seconds
- Uses crontab for scheduled tasks

### Existing Task Example (`backend/app/worker/tasks/examples.py`):
```python
@shared_task(bind=True, max_retries=3)
def example_task(self, message: str):
    # Can use self.update_state(state="PROGRESS", meta={...}) for progress
    # Can retry with exponential backoff
    return result_dict
```

## 4. Message/Conversation Persistence

### Database Models (`backend/app/db/models/conversation.py`):

#### Conversation Model:
- `id`: UUID
- `user_id`: UUID (FK to users)
- `title`: Auto-generated or manual
- `system_prompt`: Conversation-specific system prompt
- `is_archived`: Boolean
- `created_at`, `updated_at`: Timestamps

#### Message Model:
- `id`: UUID
- `conversation_id`: UUID (FK)
- `role`: "user" | "assistant" | "system"
- `content`: Text (full response)
- `thinking_content`: Text (Claude/Gemini thinking traces)
- `model_name`: Model used for this message
- `tokens_used`: Token count
- `tool_calls`: Relationship to ToolCall records

#### ToolCall Model:
- `id`: UUID
- `message_id`: UUID (FK)
- `tool_call_id`: String (PydanticAI ID)
- `tool_name`: Tool name
- `args`: JSONB dict
- `result`: Text (serialized result, max ~5000 chars)
- `status`: "pending" | "running" | "completed" | "failed"
- `started_at`, `completed_at`: Timestamps
- `duration_ms`: Execution time

### Conversation Service (`backend/app/services/conversation.py`):

Key methods:
- `get_conversation()`, `list_conversations()`, `create_conversation()`
- `add_message()` → creates Message record
- `start_tool_call()` → creates ToolCall with `status="running"`
- `complete_tool_call()` → updates ToolCall with result and status
- `generate_and_set_title()` → uses LLM to auto-generate title (non-blocking)

### Persistence Pattern:
- **Repositories** use `db.flush()` not `db.commit()` (transactions managed by FastAPI dependency layer)
- **Timing**: Messages/tool calls persisted **during** agent execution
  - User message: Before agent starts
  - Tool calls: As they're invoked (start & completion)
  - Assistant response: After agent completes
- **Atomicity**: Each operation is its own DB transaction (via `async with get_db_context()`)

## 5. Redis Usage

### Current Uses:
1. **Celery Broker**: Task queue (REDIS_URL)
2. **Celery Result Backend**: Task result storage
3. **Rate Limiting**: Via slowapi (configured but not shown)
4. **Cache**: Generic key-value store (RedisClient wrapper)
5. **System Prompt Caching**: Stores Gemini `CachedContent` metadata/keys

### RedisClient Wrapper (`backend/app/clients/redis.py`):
```python
class RedisClient:
    async def get(key) → str | None
    async def set(key, value, ttl) → None
    async def delete(key) → int
    async def exists(key) → bool
    async def ping() → bool
    @property raw → aioredis.Redis  # Access underlying client
```

### Configuration:
- **Connection Pool**: Via `aioredis.from_url()` with `encode="utf-8"`
- **TTL Support**: `set()` accepts `ex` (expiration in seconds)
- **Pub/Sub**: Raw client supports `.subscribe()`, `.psubscribe()`, `.pubsub()`

## 6. SSE Infrastructure (Frontend)

### SSE Utility (`frontend/src/lib/sse.ts`):
- Function `consumeSSE(url, params, options)` for server-sent events
- Handlers: `onEvent`, `onComplete`, `onError`, `signal` (AbortController)
- Currently used for file operations (folder rename progress)
- **Not used** for agent communication (uses WebSocket instead)

### Event Format:
```
event: <type>
data: <json>

```

## 7. Frontend Chat Hook (`frontend/src/hooks/use-chat.ts`)

### useChat() Hook:
- Manages chat state (messages, isProcessing, isConnected)
- Uses WebSocket via `useWebSocket()` hook
- Connects to `/api/v1/ws/agent?token=<jwt>`

### WebSocket Message Handlers:
- `conversation_created`: New conversation ID from server
- `model_request_start`: Model inference starting
- `thinking_delta`: Streaming thinking traces
- `text_delta`: Streaming text
- `tool_call`: Tool invoked with args
- `tool_result`: Tool completed with result
- `final_result`: Agent finished
- `complete`: Processing done
- `error`: Error occurred

### Client-Side State:
- Uses Zustand stores: `useChatStore`, `useConversationStore`
- Builds local message objects with:
  - `id`, `role`, `content`, `timestamp`
  - `isStreaming`, `isThinkingStreaming`
  - `thinkingContent`, `toolCalls`

## 8. Provider System (`backend/app/agents/providers/`)

### Base Provider (`base.py`):
- Property `supports_streaming`: bool (default True)
- Property `supports_thinking`: bool
- Property `modalities`: Input modalities (text, image, etc.)
- Method `create_pydantic_model()`: Create configured PydanticAI Model
- Method `create_cached_content()`: Optional system prompt caching

### Known Providers:
1. **Gemini** (`gemini.py`): 
   - `supports_streaming=True`
   - Implements system prompt caching via CachedContent API

2. **OpenAI** (`openai.py`):
   - `supports_streaming=True`

3. **Vertex AI** (`vertex.py`):
   - `supports_streaming=False` (429 rate limits on streaming endpoint)
   - Uses non-streaming path

## Current Coupling Points - Summary

### Critical Coupling to WebSocket:
1. **Agent execution blocks on WebSocket context** (line ~820)
   - If WS closes during `agent.iter()`, execution stops
   - All events sent to client via `manager.send_event(websocket, ...)`
   - No fallback mechanism if network drops

2. **Database context lives for entire agent run** (line ~816)
   - `async with get_db_context() as agent_db:` wraps full iteration
   - Tools have access to DB via `deps.db`
   - Single connection per agent execution

3. **Tool calls persisted inline** during streaming
   - Cannot be retried if DB operation fails
   - No queue of pending tool results

4. **Conversation history restored on each request**
   - Fetches up to 1000 messages from DB
   - No pagination or incremental loading

### What's Missing for Decoupling:
- No job ID tracking for long-running tasks
- No progress reporting mechanism outside WebSocket
- No way to reconnect to ongoing execution
- No way to poll for results if WS drops
- No background task queue integration
- No message queue for streaming results

## Recommendations for Decoupling:

### Option 1: HTTP + Polling (Simple)
- POST /api/v1/agent/execute → returns job_id
- GET /api/v1/agent/jobs/{job_id} → returns status + accumulated results
- WebSocket optional for real-time (falls back to polling)
- Requires: Job storage (Redis/DB), result buffering

### Option 2: Celery + Redis Pub/Sub (Robust)
- POST /api/v1/agent/execute → returns job_id, submits to Celery
- Celery task runs agent in worker process
- Results published to Redis channel: `agent:{job_id}:{user_id}:*`
- WebSocket subscribes to channel, consumes events
- GET /api/v1/agent/jobs/{job_id} for polling
- Requires: Celery integration, Redis pub/sub wiring

### Option 3: Hybrid (Best UX)
- HTTP endpoint returns job_id + WebSocket upgrade URL
- Celery handles execution, publishes to Redis pub/sub
- WebSocket consumes live events from Redis
- Stores accumulated results in DB for later retrieval
- Supports reconnection via polling

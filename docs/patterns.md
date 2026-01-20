# Code Patterns

## Dependency Injection

Use FastAPI's `Depends()` for injecting dependencies:

```python
from app.api.deps import get_db, get_current_user

@router.get("/items")
async def list_items(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ItemService(db)
    return await service.get_multi()
```

Available dependencies in `app/api/deps.py`:
- `get_db` - Database session
- `get_current_user` - Authenticated user (raises 401 if not authenticated)
- `get_current_user_optional` - User or None
- `get_redis` - Redis connection

## Service Layer Pattern

Services contain business logic:

```python
class ItemService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ItemRepository()

    async def create(self, item_in: ItemCreate) -> Item:
        # Business validation
        if await self.repo.exists_by_name(self.db, item_in.name):
            raise AlreadyExistsError(message="Item already exists")

        # Create via repository
        return await self.repo.create(self.db, **item_in.model_dump())

    async def get_or_raise(self, id: UUID) -> Item:
        item = await self.repo.get_by_id(self.db, id)
        if not item:
            raise NotFoundError(message="Item not found", details={"id": str(id)})
        return item
```

## Repository Layer Pattern

Repositories handle data access only:

```python
class ItemRepository:
    async def get_by_id(self, db: AsyncSession, id: UUID) -> Item | None:
        return await db.get(Item, id)

    async def create(self, db: AsyncSession, **kwargs) -> Item:
        item = Item(**kwargs)
        db.add(item)
        await db.flush()  # Not commit! Let dependency manage transaction
        await db.refresh(item)
        return item

    async def get_multi(
        self, db: AsyncSession, skip: int = 0, limit: int = 100
    ) -> list[Item]:
        result = await db.execute(
            select(Item).offset(skip).limit(limit)
        )
        return list(result.scalars().all())
```

## Exception Handling

Use domain exceptions in services:

```python
from app.core.exceptions import NotFoundError, AlreadyExistsError, ValidationError

# In service
if not item:
    raise NotFoundError(
        message="Item not found",
        details={"id": str(id)}
    )

if await self.repo.exists_by_email(self.db, email):
    raise AlreadyExistsError(
        message="User with this email already exists"
    )
```

Exception handlers convert to HTTP responses automatically.

## Schema Patterns

Separate schemas for different operations:

```python
# Base with shared fields
class ItemBase(BaseModel):
    name: str
    description: str | None = None

# For creation (input)
class ItemCreate(ItemBase):
    pass

# For updates (all optional)
class ItemUpdate(BaseModel):
    name: str | None = None
    description: str | None = None

# For responses (with DB fields)
class ItemResponse(ItemBase):
    id: UUID
    created_at: datetime
    updated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
```

## Frontend Patterns

### Authentication (HTTP-only cookies)

```typescript
import { useAuth } from '@/hooks/use-auth';

function Component() {
    const { user, isAuthenticated, login, logout } = useAuth();
}
```

### State Management (Zustand)

```typescript
import { useAuthStore } from '@/stores/auth-store';

const { user, setUser, logout } = useAuthStore();
```

### WebSocket Chat

```typescript
import { useChat } from '@/hooks/use-chat';

function ChatPage() {
    const { messages, sendMessage, isStreaming } = useChat();
}
```

## AI Agent Pattern (PydanticAI)

Agents wrap PydanticAI for conversational AI with tool support:

```python
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel

from app.agents.tool_register import register_tools
from app.schemas.assistant import Deps

class AssistantAgent:
    """Assistant agent wrapper for conversational AI."""

    def __init__(self, model_name: str | None = None, system_prompt: str | None = None):
        self.model_name = model_name or "gemini-2.0-flash"
        self.system_prompt = system_prompt or "You are a helpful assistant."
        self._agent: Agent[Deps, str] | None = None

    def _create_agent(self) -> Agent[Deps, str]:
        model = GoogleModel(model_name=self.model_name)
        agent = Agent[Deps, str](
            model=model,
            deps_type=Deps,
            system_prompt=self.system_prompt,
            retries=3,
        )
        register_tools(agent)
        return agent

    @property
    def agent(self) -> Agent[Deps, str]:
        if self._agent is None:
            self._agent = self._create_agent()
        return self._agent
```

### Agent Tool Pattern

```python
from pydantic_ai import RunContext
from app.schemas.assistant import Deps

@agent.tool
async def my_tool(ctx: RunContext[Deps], param: str) -> dict:
    """
    Tool description for LLM - be specific about what it does.

    ARGS:
        param: Description of what this parameter controls

    RETURNS:
        Dictionary with result data

    USE WHEN:
        - User asks for X
        - Need to perform Y operation
    """
    # Access dependencies via ctx.deps
    db = ctx.deps.db
    user = ctx.deps.user

    result = await some_operation(param)
    return {"result": result}
```

## Celery Task Pattern

Background tasks with retry support:

```python
from celery import shared_task
import logging

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3)
def process_data(self, data_id: str) -> dict:
    """
    Process data asynchronously.

    Args:
        data_id: ID of data to process

    Returns:
        Result dictionary with status
    """
    logger.info(f"Processing data: {data_id}")

    try:
        # Your processing logic
        result = {"status": "completed", "data_id": data_id}
        return result

    except Exception as exc:
        logger.error(f"Task failed: {exc}")
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=2**self.request.retries) from exc
```

### Calling Tasks

```python
from app.worker.tasks.my_tasks import process_data

# Async call (returns immediately)
result = process_data.delay("item-123")

# Get result later (blocking)
task_result = result.get(timeout=30)

# Check status
if result.ready():
    print(result.result)
```

## WebSocket Route Pattern

```python
from fastapi import APIRouter, WebSocket

router = APIRouter()

class ConnectionManager:
    """WebSocket connection manager."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket) -> None:
        await websocket.send_text(message)

    async def broadcast(self, message: str) -> None:
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time communication."""
    await manager.connect(websocket)
    try:
        async for data in websocket.iter_text():
            await manager.broadcast(f"Message: {data}")
    finally:
        manager.disconnect(websocket)
```

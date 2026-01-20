# Adding New Features

## Adding a New API Endpoint

1. **Create schema** in `schemas/`
   ```python
   # schemas/item.py
   class ItemCreate(BaseModel):
       name: str
       description: str | None = None

   class ItemResponse(BaseModel):
       id: UUID
       name: str
       created_at: datetime
   ```

2. **Create model** in `db/models/` (if new entity)
   ```python
   # db/models/item.py
   class Item(Base):
       __tablename__ = "items"
       id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
       name: Mapped[str] = mapped_column(String(255))
   ```

3. **Create repository** in `repositories/`
   ```python
   # repositories/item.py
   class ItemRepository:
       async def create(self, db: AsyncSession, **kwargs) -> Item:
           item = Item(**kwargs)
           db.add(item)
           await db.flush()
           await db.refresh(item)
           return item
   ```

4. **Create service** in `services/`
   ```python
   # services/item.py
   class ItemService:
       def __init__(self, db: AsyncSession):
           self.db = db
           self.repo = ItemRepository()

       async def create(self, item_in: ItemCreate) -> Item:
           return await self.repo.create(self.db, **item_in.model_dump())
   ```

5. **Create route** in `api/routes/v1/`
   ```python
   # api/routes/v1/items.py
   router = APIRouter(prefix="/items", tags=["items"])

   @router.post("/", response_model=ItemResponse, status_code=201)
   async def create_item(
       item_in: ItemCreate,
       db: AsyncSession = Depends(get_db),
   ):
       service = ItemService(db)
       return await service.create(item_in)
   ```

6. **Register route** in `api/routes/v1/__init__.py`
   ```python
   from .items import router as items_router
   api_router.include_router(items_router)
   ```

## Adding a Custom CLI Command

Commands are auto-discovered from `app/commands/`.

```python
# app/commands/my_command.py
from app.commands import command, success, error
import click

@command("my-command", help="Description of what this does")
@click.option("--name", "-n", required=True, help="Name parameter")
def my_command(name: str):
    # Your logic here
    success(f"Done: {name}")
```

Run with: `uv run arachne_fullstack cmd my-command --name test`

## Adding an AI Agent Tool (PydanticAI)

```python
# app/agents/assistant.py
@agent.tool
async def my_tool(ctx: RunContext[Deps], param: str) -> dict:
    """Tool description for LLM - be specific about what it does."""
    # Access dependencies via ctx.deps
    result = await some_operation(param)
    return {"result": result}
```

## Adding a Database Migration

```bash
# Using make (recommended)
make db-migrate       # Create new migration (prompts for message)
make db-upgrade       # Apply migrations
make db-rollback      # Rollback last migration

# Via Docker (for LLMs)
docker compose exec app make db-migrate
docker compose exec app make db-upgrade

# Direct commands (from backend/)
uv run alembic revision --autogenerate -m "Add items table"
uv run alembic upgrade head

# Or use CLI
uv run arachne_fullstack db migrate -m "Add items table"
uv run arachne_fullstack db upgrade
```

## Adding a Celery Background Task

1. **Create task** in `worker/tasks/`
   ```python
   # worker/tasks/my_tasks.py
   from celery import shared_task
   import logging

   logger = logging.getLogger(__name__)

   @shared_task(bind=True, max_retries=3)
   def my_task(self, param: str) -> dict:
       """
       Task description.

       Args:
           param: Description of parameter

       Returns:
           Result dictionary
       """
       logger.info(f"Processing: {param}")

       try:
           # Your task logic here
           result = {"status": "completed", "param": param}
           return result

       except Exception as exc:
           logger.error(f"Task failed: {exc}")
           # Retry with exponential backoff
           raise self.retry(exc=exc, countdown=2**self.request.retries) from exc
   ```

2. **Import in tasks/__init__.py** (if not auto-discovered)
   ```python
   from .my_tasks import my_task
   ```

3. **Call task from service or route**
   ```python
   from app.worker.tasks.my_tasks import my_task

   # Async call (returns immediately)
   result = my_task.delay("value")

   # Get result later
   task_result = result.get(timeout=30)
   ```

4. **Run Celery worker**
   ```bash
   make celery-worker    # Start worker
   make celery-beat      # Start scheduler (for periodic tasks)
   make celery-flower    # Start monitoring UI
   ```

# CLAUDE.md

## Project Overview

**arachne_fullstack** - FastAPI application generated with [Full-Stack FastAPI + Next.js Template](https://github.com/vstorm-co/full-stack-fastapi-nextjs-llm-template).

**Stack:** FastAPI + Pydantic v2, PostgreSQL (async), JWT auth, Redis, PydanticAI, Celery, Next.js 15

## Commands

Use `make` shortcuts (run from project root):

```bash
# Development
make dev              # Start dev server with reload
make test             # Run pytest
make format           # Auto-format (ruff format + ruff check --fix)
make lint             # Check code quality (ruff + mypy)

# Database
make db-upgrade       # Apply migrations
make db-migrate       # Create new migration
make db-rollback      # Rollback last migration

# Docker
make docker-up        # Start backend services (postgres, redis, app)
make docker-down      # Stop all services
make docker-frontend  # Start frontend separately

# Celery
make celery-worker    # Start Celery worker
make celery-beat      # Start Celery beat scheduler

make help             # Show all available commands
```

### Running Commands via Docker (for LLMs)

When executing code as an LLM agent, use Docker exec:

```bash
docker compose exec app <command>        # Backend commands
docker compose exec frontend <command>   # Frontend commands

# Examples:
docker compose exec app pytest
docker compose exec app make db-upgrade
docker compose exec frontend bun test
```

### Raw Commands (alternative)

```bash
# Backend (from backend/)
uv run uvicorn app.main:app --reload --port 8000
pytest
ruff check . --fix && ruff format .

# Database migrations
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "Description"

# Frontend (from frontend/)
bun dev
bun test
```

## Project Structure

```
backend/app/
├── api/routes/v1/    # HTTP endpoints (REST + WebSocket)
├── services/         # Business logic
├── repositories/     # Data access layer
├── schemas/          # Pydantic models
├── db/models/        # SQLAlchemy models
├── core/             # Config, security, middleware, utils
│   ├── config.py     # Settings via pydantic-settings
│   ├── security.py   # JWT/API key utilities
│   ├── exceptions.py # Domain exceptions
│   ├── middleware.py # Request middleware
│   ├── rate_limit.py # Rate limiting
│   └── cache.py      # Caching utilities
├── agents/           # AI agents (PydanticAI)
│   └── tools/        # Agent tools
├── clients/          # External service clients
│   ├── redis.py      # Redis client
│   └── academic/     # Academic search APIs
├── commands/         # CLI commands (auto-discovered)
├── pipelines/        # Data processing pipelines
└── worker/           # Celery background tasks
    └── tasks/        # Task definitions
```

## Key Conventions

- Use `db.flush()` in repositories (not `commit`)
- Services raise domain exceptions (`NotFoundError`, `AlreadyExistsError`)
- Schemas: separate `Create`, `Update`, `Response` models
- Commands auto-discovered from `app/commands/`

## Where to Find More Info

Before starting complex tasks, read relevant docs:
- **Architecture details:** `docs/architecture.md`
- **Adding features:** `docs/adding_features.md`
- **Testing guide:** `docs/testing.md`
- **Code patterns:** `docs/patterns.md`
- **Frontend architecture:** `docs/frontend.md`

## Environment Variables

Key variables in `.env`:
```bash
ENVIRONMENT=local
POSTGRES_HOST=localhost
POSTGRES_PASSWORD=secret
SECRET_KEY=change-me-use-openssl-rand-hex-32
OPENAI_API_KEY=sk-...
LOGFIRE_TOKEN=your-token
```

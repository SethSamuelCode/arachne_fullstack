# AGENTS.md

This file provides guidance for AI coding agents (Codex, Copilot, Cursor, Zed, OpenCode).

## Project Overview

**arachne_fullstack** - FastAPI application.

**Stack:** FastAPI + Pydantic v2, PostgreSQL (async), JWT auth, Redis, PydanticAI, Celery, Next.js 15

## Commands

Use `make` shortcuts (run from project root):

```bash
make dev              # Start dev server with reload
make test             # Run tests
make format           # Auto-format code (ruff)
make lint             # Check code quality
make db-upgrade       # Apply migrations
make db-migrate       # Create new migration
make docker-up        # Start backend services
make help             # Show all commands
```

### Running Commands via Docker (for LLMs)

```bash
docker compose exec app <command>        # Backend commands
docker compose exec frontend <command>   # Frontend commands

# Examples:
docker compose exec app pytest
docker compose exec app make db-upgrade
docker compose exec frontend bun test
```

## Project Structure

```
backend/app/
├── api/routes/v1/    # HTTP endpoints
├── services/         # Business logic
├── repositories/     # Data access layer
├── schemas/          # Pydantic models
├── db/models/        # SQLAlchemy models
├── core/             # Config, security, middleware, utils
├── agents/           # AI agents (PydanticAI)
│   └── tools/        # Agent tools
├── clients/          # External service clients (Redis, APIs)
├── commands/         # CLI commands (auto-discovered)
├── pipelines/        # Data processing pipelines
└── worker/           # Celery background tasks
    └── tasks/        # Task definitions
```

## Key Conventions

- `db.flush()` in repositories, not `commit()`
- Services raise `NotFoundError`, `AlreadyExistsError`
- Separate `Create`, `Update`, `Response` schemas
- Commands auto-discovered from `app/commands/`

## More Info

- `docs/architecture.md` - Architecture details
- `docs/adding_features.md` - How to add features
- `docs/testing.md` - Testing guide
- `docs/patterns.md` - Code patterns
- `docs/frontend.md` - Frontend architecture

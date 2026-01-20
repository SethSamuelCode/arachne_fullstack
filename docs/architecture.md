# Architecture Guide

This project follows a **Repository + Service** layered architecture.

## Request Flow

```
HTTP Request → API Route → Service → Repository → Database
                  ↓
              Response ← Service ← Repository ←
```

## Directory Structure (`backend/app/`)

| Directory | Purpose |
|-----------|---------|
| `api/routes/v1/` | HTTP endpoints, request validation, auth, WebSocket routes |
| `api/deps.py` | Dependency injection (db session, current user, services) |
| `services/` | Business logic, orchestration |
| `repositories/` | Data access layer, database queries |
| `schemas/` | Pydantic models for request/response |
| `db/models/` | SQLAlchemy models |
| `core/` | Configuration, security, middleware, utilities (see below) |
| `agents/` | AI agents (PydanticAI) and tools |
| `clients/` | External service clients (Redis, academic APIs) |
| `commands/` | CLI commands (auto-discovered) |
| `pipelines/` | Data processing pipelines |
| `worker/` | Celery background tasks |
| `worker/tasks/` | Task definitions |

## Core Utilities (`core/`)

| File | Purpose |
|------|---------|
| `config.py` | Settings via pydantic-settings |
| `security.py` | JWT/API key utilities, password hashing |
| `exceptions.py` | Domain exceptions (`NotFoundError`, `AlreadyExistsError`) |
| `middleware.py` | Request logging, correlation IDs |
| `rate_limit.py` | API rate limiting |
| `cache.py` | Caching utilities |
| `csrf.py` | CSRF protection |
| `sanitize.py` | Input sanitization |

## Layer Responsibilities

### API Routes (`api/routes/v1/`)
- HTTP request/response handling
- Input validation via Pydantic schemas
- Authentication/authorization checks
- Delegates to services for business logic

### Services (`services/`)
- Business logic and validation
- Orchestrates repository calls
- Raises domain exceptions (NotFoundError, etc.)
- Transaction boundaries

### Repositories (`repositories/`)
- Database operations only
- No business logic
- Uses `db.flush()` not `commit()` (let dependency manage transactions)
- Returns domain models

## AI Agents (`agents/`)

Uses PydanticAI for conversational AI with tool support:
- `assistant.py` - Main conversational agent wrapper
- `tool_register.py` - Registers tools with the agent
- `prompts.py` - System prompts
- `tools/` - Individual tool implementations

Agents access dependencies via `RunContext[Deps]` for database, Redis, and user context.

## Background Tasks (`worker/`)

Uses Celery for async task processing:
- `celery_app.py` - Celery app configuration
- `tasks/` - Task definitions using `@shared_task`
- Supports retries, progress tracking, scheduled tasks

## Key Files

- Entry point: `app/main.py`
- Configuration: `app/core/config.py`
- Dependencies: `app/api/deps.py`
- Auth utilities: `app/core/security.py`
- Exception handlers: `app/api/exception_handlers.py`

## Frontend Architecture

See `docs/frontend.md` for frontend structure and patterns.

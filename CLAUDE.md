# CLAUDE.md

## Project Overview

**arachne_fullstack** is an AI-powered chat application built on a full-stack FastAPI + Next.js architecture. The AI assistant ("Arachne") uses Google Gemini models via PydanticAI with tool support including academic search, web extraction, image generation, and Python code execution in sandboxed Docker containers.

**Stack:**
- **Backend:** FastAPI, Pydantic v2, PostgreSQL (async via asyncpg), JWT auth (EdDSA), Redis, PydanticAI, Celery, SQLAdmin
- **Frontend:** Next.js 15 (App Router), React 19, TypeScript, Zustand, Tailwind CSS 4, shadcn/ui, next-intl (i18n)
- **Infrastructure:** Docker Compose, MinIO (S3-compatible storage), Logfire (observability)
- **Python:** 3.13+, managed with `uv`
- **Node:** Bun runtime for frontend

## Commands

Use `make` shortcuts from the project root:

```bash
# Development
make install          # Install deps + pre-commit hooks
make run              # Start dev server (uvicorn with reload)
make test             # Run pytest
make format           # Auto-format (ruff format + ruff check --fix)
make lint             # Check code quality (ruff + mypy)

# Database
make db-init          # Start postgres + apply migrations
make db-upgrade       # Apply migrations
make db-migrate       # Create new migration (prompts for message)
make db-downgrade     # Rollback last migration
make db-current       # Show current migration revision
make db-history       # Show migration history

# Users
make create-admin     # Create admin user (for SQLAdmin access)
make user-create      # Create new user (interactive)
make user-list        # List all users

# Celery
make celery-worker    # Start Celery worker
make celery-beat      # Start Celery beat scheduler
make celery-flower    # Start Flower monitoring UI (port 5555)

# Docker (Development)
make docker-up        # Start all backend services (app, db, redis, celery, s3, frontend)
make docker-down      # Stop all services
make docker-logs      # View backend logs
make docker-build     # Build backend images
make docker-shell     # Shell into app container
make docker-frontend  # Start frontend separately (port 3552)
make docker-db        # Start only PostgreSQL (port 5432)
make docker-redis     # Start only Redis (port 6379)

# Docker (Production)
make docker-prod      # Start production stack
make docker-prod-down # Stop production stack
make docker-rebuild-and-deploy-all  # Rebuild + deploy all services

# Other
make routes           # Show all API routes
make clean            # Clean cache files (__pycache__, .pytest_cache, etc.)
make help             # Show all available commands
```

### Running Commands via Docker (for LLM agents)

```bash
docker compose exec app <command>        # Backend commands
docker compose exec frontend <command>   # Frontend commands

# Examples:
docker compose exec app pytest
docker compose exec app make db-upgrade
docker compose exec frontend bun test
```

### Raw Commands

```bash
# Backend (from backend/)
uv run uvicorn app.main:app --reload --port 8000
pytest
ruff check . --fix && ruff format .
uv run mypy app

# Database migrations (from backend/)
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "Description"

# CLI tool
uv run arachne_fullstack <subcommand>    # server, db, user, celery

# Frontend (from frontend/)
bun dev              # Dev server (port 3552)
bun build            # Production build
bun test             # Unit tests (Vitest)
bun test:e2e         # E2E tests (Playwright)
bun lint             # ESLint
bun format           # Prettier
bun type-check       # TypeScript check
```

## Project Structure

```
arachne_fullstack/
├── CLAUDE.md                      # This file
├── AGENTS.md                      # Guidance for other AI agents
├── Makefile                       # All dev/build/deploy commands
├── docker-compose.yml             # Dev services (app, db, redis, celery, s3, frontend, sandbox)
├── docker-compose.dev.yml         # Dev overrides
├── docker-compose.frontend.yml    # Frontend-only
├── docker-compose.prod.yml        # Production with Traefik
├── Dockerfile.sandbox             # Python sandbox container for code execution
├── docs/                          # Extended documentation
│
├── backend/
│   ├── pyproject.toml             # Python deps (hatchling build, ruff, mypy, pytest config)
│   ├── uv.lock                    # Dependency lock
│   ├── Dockerfile                 # Backend container
│   ├── alembic.ini                # Migration config
│   ├── alembic/versions/          # Migration files (YYYY-MM-DD_description.py)
│   ├── cli/commands.py            # CLI entry point (arachne_fullstack command)
│   ├── tests/                     # Backend tests (see Testing section)
│   └── app/                       # Main application (see below)
│
└── frontend/
    ├── package.json               # Node deps (bun)
    ├── next.config.ts             # Next.js config
    ├── tsconfig.json              # TypeScript config
    ├── vitest.config.ts           # Unit test config
    ├── playwright.config.ts       # E2E test config
    ├── middleware.ts              # Next.js middleware (auth, i18n)
    ├── src/                       # Source code (see Frontend section)
    └── e2e/                       # Playwright E2E tests
```

### Backend Application (`backend/app/`)

```
app/
├── main.py                # FastAPI app creation, lifespan, middleware stack
├── admin.py               # SQLAdmin panel configuration
│
├── api/
│   ├── router.py          # Main API router
│   ├── deps.py            # Dependency injection (DB, Redis, Services, Auth)
│   ├── exception_handlers.py  # Global exception handling
│   ├── versioning.py      # API versioning utilities
│   └── routes/v1/         # All HTTP endpoints (14 route modules)
│       ├── health.py      # GET /health
│       ├── auth.py        # /auth (login, register, refresh, OAuth)
│       ├── users.py       # /users (CRUD, profile)
│       ├── sessions.py    # /sessions (active login sessions)
│       ├── items.py       # /items (example CRUD)
│       ├── conversations.py  # /conversations (chat history)
│       ├── plans.py       # /plans (task/plan management)
│       ├── files.py       # /files (upload/download via S3)
│       ├── storage_proxy.py  # /storage (sandbox container proxy)
│       ├── webhooks.py    # /webhooks (event subscriptions)
│       ├── admin_settings.py  # /admin/settings
│       ├── agent.py       # AI agent endpoints
│       └── ws.py          # WebSocket routes
│
├── services/              # Business logic layer
│   ├── user.py            # User management
│   ├── conversation.py    # Conversation operations
│   ├── plan.py            # Plan/task management
│   ├── item.py            # Example CRUD
│   ├── session.py         # Login session management
│   ├── webhook.py         # Webhook delivery
│   ├── settings.py        # Runtime settings (Redis-backed)
│   ├── python.py          # Python sandbox execution
│   └── s3.py              # S3/MinIO file storage
│
├── repositories/          # Data access layer
│   ├── base.py            # Base repository class
│   ├── user.py            # User queries
│   ├── conversation.py    # Conversation queries
│   ├── plan.py            # Plan/task queries
│   ├── item.py            # Item queries
│   ├── session.py         # Session queries
│   └── webhook.py         # Webhook queries
│
├── schemas/               # Pydantic models (request/response)
│   ├── base.py            # Base schema classes
│   ├── user.py            # UserCreate, UserUpdate, UserResponse
│   ├── conversation.py    # Conversation schemas
│   ├── assistant.py       # Agent Deps, assistant schemas
│   ├── attachment.py      # File attachment schemas
│   ├── plan.py / planning.py  # Plan/task schemas
│   ├── item.py            # Item schemas
│   ├── token.py           # JWT token schemas
│   ├── file.py            # File operation schemas
│   ├── models.py          # AI model configuration
│   ├── academic.py        # Academic search schemas
│   ├── web_search.py      # Web search schemas
│   ├── extract_webpage.py # Webpage extraction schemas
│   ├── webhook.py         # Webhook schemas
│   ├── session.py         # Session schemas
│   └── spawn_agent_deps.py  # Agent dependency schemas
│
├── db/
│   ├── base.py            # SQLAlchemy declarative base
│   ├── session.py         # Async session management (get_db_session, get_db_context)
│   └── models/            # SQLAlchemy ORM models
│       ├── user.py        # User (with UserRole enum)
│       ├── conversation.py  # Conversation, Message, ToolCall
│       ├── attachment.py  # MessageAttachment
│       ├── plan.py        # Plan, PlanTask
│       ├── session.py     # Session (login sessions)
│       ├── webhook.py     # Webhook, WebhookDelivery
│       └── item.py        # Item (example CRUD entity)
│
├── core/                  # Configuration and utilities
│   ├── config.py          # Settings (pydantic-settings, env vars)
│   ├── security.py        # JWT creation/verification, password hashing
│   ├── exceptions.py      # Domain exception hierarchy (AppException base)
│   ├── middleware.py       # RequestIDMiddleware, SecurityHeadersMiddleware
│   ├── csrf.py            # CSRF protection middleware
│   ├── sanitize.py        # Input sanitization
│   ├── rate_limit.py      # Slowapi rate limiting
│   ├── cache.py           # Cache setup
│   ├── cache_manager.py   # Cache management (tool cache validation, warmup)
│   ├── user_scope.py      # User scope utilities
│   ├── docker.py          # Docker utilities (sandbox management)
│   ├── logfire_setup.py   # Logfire observability instrumentation
│   └── utils.py           # General utilities
│
├── agents/                # AI agent system (PydanticAI + Gemini)
│   ├── assistant.py       # AssistantAgent class (main agent wrapper)
│   ├── tool_register.py   # Tool registration (8+ tools)
│   ├── context_optimizer.py  # Context window optimization
│   ├── cached_google_model.py  # Cached Gemini model (75% cost reduction)
│   ├── prompts.py         # System prompts
│   └── tools/             # Individual tool implementations
│       ├── academic_search.py  # arXiv, OpenAlex, Semantic Scholar
│       ├── extract_webpage.py  # Webpage content extraction
│       ├── s3_image.py         # Image generation + S3 storage
│       ├── datetime_tool.py    # Date/time utilities
│       └── decorators.py       # Tool decorator utilities
│
├── clients/               # External service clients
│   ├── redis.py           # Redis client with connection pooling
│   └── academic/          # Academic API clients
│       ├── arxiv.py       # arXiv API (feedparser)
│       ├── openalex.py    # OpenAlex API
│       └── semantic_scholar.py  # Semantic Scholar API
│
├── worker/                # Celery background tasks
│   ├── celery_app.py      # Celery config (Redis broker)
│   └── tasks/
│       ├── examples.py    # Example tasks
│       └── schedules.py   # Periodic task schedules
│
├── pipelines/             # Data processing pipelines
│   └── base.py            # Base pipeline class
│
├── commands/              # CLI commands (auto-discovered)
│
└── sandbox_lib/           # Python sandbox support
    └── storage_client.py  # Sandbox-to-host storage client
```

### Frontend Application (`frontend/src/`)

```
src/
├── app/                       # Next.js App Router
│   ├── layout.tsx             # Root layout
│   ├── providers.tsx          # Context providers
│   ├── api/                   # API route handlers (proxy to backend)
│   │   ├── auth/              # /api/auth/* (login, logout, register, refresh, OAuth)
│   │   ├── conversations/     # /api/conversations/* (CRUD, messages)
│   │   ├── files/             # /api/files/* (upload, download, presign, folders)
│   │   ├── plans/             # /api/plans/* (CRUD, tasks, reorder)
│   │   ├── tasks/             # /api/tasks/*
│   │   ├── users/             # /api/users/me
│   │   ├── admin/             # /api/admin/* (settings, users)
│   │   └── health/            # /api/health
│   └── [locale]/              # i18n locale routes (en, pl)
│       ├── (auth)/            # Auth pages (login, register)
│       └── (dashboard)/       # Protected routes
│           ├── chat/          # Chat interface
│           ├── dashboard/     # Dashboard
│           ├── files/         # File manager
│           ├── plans/         # Plan/task management
│           ├── profile/       # User profile
│           └── admin/         # Admin (settings, users)
│
├── components/
│   ├── auth/                  # Login/register forms
│   ├── chat/                  # Chat UI (container, input, messages, markdown,
│   │                          #   thinking blocks, tool calls, sidebar, attachments)
│   ├── files/                 # File browser + sidebar
│   ├── layout/                # Header, sidebar, mobile menu
│   ├── ui/                    # shadcn/ui primitives (button, input, card, dialog, etc.)
│   ├── theme/                 # Theme provider + toggle (dark/light)
│   └── icons/                 # Custom icon components
│
├── hooks/                     # Custom React hooks
│   ├── use-auth.ts            # Authentication state + actions
│   ├── use-chat.ts            # Chat messaging with SSE streaming
│   ├── use-conversations.ts   # Conversation CRUD
│   ├── use-websocket.ts       # WebSocket connection management
│   ├── use-local-chat.ts      # Local-only chat (no persistence)
│   └── useFileTreeDnd.ts      # File tree drag-and-drop
│
├── stores/                    # Zustand state stores
│   ├── auth-store.ts          # User authentication state
│   ├── chat-store.ts          # Active chat messages
│   ├── conversation-store.ts  # Conversation list
│   ├── chat-sidebar-store.ts  # Chat sidebar toggle
│   ├── files-store.ts         # File upload state
│   ├── sidebar-store.ts       # Main sidebar visibility
│   ├── theme-store.ts         # Dark/light mode
│   └── local-chat-store.ts    # Local chat state
│
├── lib/                       # Utilities
│   ├── api-client.ts          # HTTP client for backend API
│   ├── server-api.ts          # Server-side API calls
│   ├── sse.ts                 # Server-Sent Events handling
│   ├── jwt.ts                 # JWT token utilities
│   ├── utils.ts               # General utilities (cn, etc.)
│   └── constants.ts           # App constants
│
├── types/                     # TypeScript type definitions
│   ├── auth.ts, api.ts, chat.ts, conversation.ts, plan.ts, filesystem.d.ts
│
├── i18n/                      # Internationalization config
│   ├── config.ts, routing.ts, navigation.ts
│
├── messages/                  # Locale message files
│   ├── en.json, pl.json
│
└── middleware.ts              # Next.js middleware (auth + i18n routing)
```

## Architecture

### Request Flow

```
HTTP Request -> API Route -> Service -> Repository -> Database
                   |
               Response  <-  Service <- Repository <-
```

### Layer Responsibilities

| Layer | Location | Responsibility |
|-------|----------|----------------|
| **API Routes** | `api/routes/v1/` | HTTP handling, input validation, auth checks, delegates to services |
| **Services** | `services/` | Business logic, orchestration, raises domain exceptions |
| **Repositories** | `repositories/` | Database operations only, uses `flush()` not `commit()` |
| **Schemas** | `schemas/` | Pydantic models for API input/output |
| **Models** | `db/models/` | SQLAlchemy ORM models |

### Dependency Injection

Dependencies are defined in `api/deps.py` using FastAPI's `Depends()` with type aliases:

```python
# Type aliases (use these in route function signatures)
DBSession       # AsyncSession
Redis           # RedisClient
CurrentUser     # Authenticated user (401 if not)
CurrentAdmin    # Admin role required (403 if not)
CurrentSuperuser # Superuser required (403 if not)

# Service aliases
UserSvc, SessionSvc, WebhookSvc, ItemSvc, ConversationSvc, RuntimeSettingsSvc, PlanSvc
```

## Key Conventions

### Backend

- **Repositories use `db.flush()`**, never `commit()`. Transaction management is handled by the dependency injection layer.
- **Services raise domain exceptions** from `core/exceptions.py`:
  - `NotFoundError` (404), `AlreadyExistsError` (409), `ValidationError` (422)
  - `AuthenticationError` (401), `AuthorizationError` (403), `RateLimitError` (429)
  - `BadRequestError` (400), `ExternalServiceError` (503), `DatabaseError` (500)
  - Academic: `ArxivError`, `OpenAlexError`, `SemanticScholarError`
- **Schemas follow the pattern**: `FooCreate` (input), `FooUpdate` (partial update), `FooResponse` (output with `model_config = ConfigDict(from_attributes=True)`)
- **CLI commands** are auto-discovered from `app/commands/`. Run with `uv run arachne_fullstack cmd <name>`.
- **Code style**: Ruff formatter + linter (line length 100), mypy strict mode. Ignore `E501` (handled by formatter) and `B008` (needed for FastAPI `Depends`).
- **Agent tools** use XML-formatted docstrings for better LLM performance. Tool definitions include `ARGS`, `RETURNS`, and `USE WHEN` sections.
- **Async throughout**: All database operations, service methods, and agent tools are async.

### Frontend

- **HTTP-only cookies** for authentication (not localStorage tokens)
- **Zustand** for client-side state management (not Redux/Context)
- **next-intl** for internationalization (locales: en, pl). Messages in `messages/*.json`.
- **shadcn/ui** components in `components/ui/` (Radix UI primitives + Tailwind)
- **API client pattern**: `apiClient` for client-side, `serverApi` for Server Components

### Database Migrations

Migration files in `backend/alembic/versions/` use the naming convention `YYYY-MM-DD_description.py`:
- `2025-12-31_init.py` - Initial schema
- `2026-01-07_add_system_prompt_to_conversation.py`
- `2026-01-08_add_default_model_to_user.py`
- `2026-01-08_add_default_system_prompt_to_user.py`
- `2026-01-12_add_message_attachments.py`
- `2026-01-23_add_plans_and_plan_tasks.py`

## Testing

### Backend Tests

```bash
make test                                   # Run all tests
pytest tests/ -v                            # Verbose
pytest tests/api/test_health.py -v          # Specific file
pytest tests/api/test_health.py::test_health_check -v  # Specific test
pytest -x                                   # Stop on first failure
pytest --cov=app --cov-report=term-missing  # With coverage
```

Test structure (`backend/tests/`):
```
tests/
├── conftest.py              # Fixtures: client (async), mock_redis, mock_db_session, JWT keys
├── api/                     # API endpoint tests
│   ├── test_auth.py         # Authentication
│   ├── test_health.py       # Health check
│   ├── test_items.py        # Item CRUD
│   ├── test_users.py        # User endpoints
│   ├── test_files.py        # File operations
│   ├── test_exceptions.py   # Exception handling
│   └── test_metrics.py      # Metrics
├── test_agents.py           # AI agent tests
├── test_services.py         # Service layer tests
├── test_repositories.py     # Repository layer tests
├── test_plan_repository.py  # Plan repo tests
├── test_security.py         # Security utilities
├── test_core.py             # Core utilities
├── test_clients.py          # External client tests
├── test_commands.py         # CLI command tests
├── test_pipelines.py        # Pipeline tests
├── test_storage_proxy.py    # Storage proxy tests
├── test_tool_schemas.py     # Tool schema tests
├── test_worker.py           # Celery task tests
└── test_admin.py            # Admin functionality
```

Key test conventions:
- Uses **anyio** (not pytest-asyncio) for async testing
- **HTTPX AsyncClient** with ASGITransport (not Starlette TestClient)
- Dependencies are overridden via `app.dependency_overrides`
- Ed25519 JWT keys auto-configured for all tests via `setup_test_jwt_keys` fixture

### Frontend Tests

```bash
bun test                # Unit tests (Vitest + React Testing Library)
bun test:run            # Single run (no watch)
bun test:coverage       # With coverage
bun test:e2e            # E2E tests (Playwright)
bun test:e2e --headed   # E2E in browser
```

## Docker Services

The `docker-compose.yml` defines these services:

| Service | Container | Port | Description |
|---------|-----------|------|-------------|
| `app` | arachne_fullstack_backend | 8550 | FastAPI backend |
| `db` | arachne_fullstack_db | 5432 | PostgreSQL 18 |
| `redis` | arachne_fullstack_redis | 6379 | Redis 7 |
| `celery_worker` | arachne_fullstack_celery_worker | - | Celery worker |
| `celery_beat` | arachne_fullstack_celery_beat | - | Celery scheduler |
| `flower` | arachne_fullstack_flower | 5555 | Celery monitoring |
| `s3` | arachne_fullstack_s3 | 9055/9011 | MinIO (S3-compatible) |
| `frontend` | arachne_fullstack_frontend | 3552 | Next.js frontend |
| `python_sandbox` | arachne_fullstack_python_sandbox | - | Python code execution sandbox |

## Environment Variables

Key variables configured in `backend/.env` (see `backend/.env.example`):

```bash
# Core
ENVIRONMENT=local                    # local | development | staging | production
SECRET_KEY=<32+ chars>               # JWT signing (HS256 fallback)
DEBUG=false

# Database
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=secret
POSTGRES_DB=arachne_fullstack

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# Auth (EdDSA - required in production)
JWT_PRIVATE_KEY=<Ed25519 PEM>        # Optional in local (falls back to HS256)
JWT_PUBLIC_KEY=<Ed25519 PEM>
INTERNAL_API_KEY=<key>               # Frontend-to-backend trusted communication

# AI / LLM
GOOGLE_API_KEY=<key>                 # Gemini models
OPENAI_API_KEY=<key>                 # OpenAI models
AI_MODEL=gpt-4o-mini
LLM_PROVIDER=openai

# Agent execution limits
AGENT_MAX_REQUESTS=100
AGENT_MAX_TOOL_CALLS=200
AGENT_STREAM_THINKING=true           # Stream thinking traces to client

# System prompt caching (Gemini)
ENABLE_SYSTEM_PROMPT_CACHING=true    # 75% cost reduction
GOOGLE_CACHE_TTL_SECONDS=900

# File Storage (S3/MinIO)
S3_ENDPOINT=<endpoint>
S3_ACCESS_KEY=<key>
S3_SECRET_KEY=<key>
S3_BUCKET=arachne_fullstack

# Web Search
TAVILY_API_KEY=<key>

# Academic APIs
OPENALEX_API_KEY=<key>               # Or OPENALEX_EMAIL for polite pool
SEMANTIC_SCHOLAR_API_KEY=<key>

# Observability
LOGFIRE_TOKEN=<token>

# CORS
CORS_ORIGINS=["http://localhost:3000","http://localhost:8080"]
```

## Where to Find More Info

Before starting complex tasks, read the relevant docs:

- **Architecture details:** `docs/architecture.md` - Layer responsibilities, request flow
- **Adding features:** `docs/adding_features.md` - Step-by-step for new endpoints, tools, tasks
- **Testing guide:** `docs/testing.md` - Fixtures, patterns, running tests
- **Code patterns:** `docs/patterns.md` - DI, services, repos, agents, Celery, WebSocket patterns
- **Frontend architecture:** `docs/frontend.md` - Components, hooks, stores, i18n
- **Security upgrade plan:** `docs/auth-security-upgrade-plan.md`
- **Prompt injection fixes:** `docs/system-prompt-injection-fix.md`

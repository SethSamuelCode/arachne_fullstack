# Arachne Fullstack

A full-stack AI assistant application built with FastAPI and Next.js.

## Tech Stack

- **Backend:** FastAPI + Pydantic v2, PostgreSQL (async), JWT auth, Redis, PydanticAI, Celery
- **Frontend:** Next.js 15, TypeScript, Zustand, Tailwind CSS
- **AI:** PydanticAI with Google Gemini models
- **Background Tasks:** Celery with Redis broker

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.12+ with [uv](https://docs.astral.sh/uv/)
- Node.js 20+ with [bun](https://bun.sh/)

### Development Setup

```bash
# Start all services (postgres, redis, backend, frontend)
make docker-up

# Or start backend services only and run locally
make docker-postgres
make docker-redis
make dev              # Backend dev server
cd frontend && bun dev  # Frontend dev server
```

### Running Commands

```bash
# Using make shortcuts (recommended)
make dev              # Start backend dev server
make test             # Run tests
make format           # Auto-format code
make lint             # Check code quality
make db-upgrade       # Apply migrations
make db-migrate       # Create new migration
make help             # Show all commands

# Via Docker (useful for CI/LLM agents)
docker compose exec app pytest
docker compose exec frontend bun test
```

## Project Structure

```
├── backend/
│   └── app/
│       ├── api/routes/v1/    # HTTP endpoints
│       ├── services/         # Business logic
│       ├── repositories/     # Data access layer
│       ├── schemas/          # Pydantic models
│       ├── db/models/        # SQLAlchemy models
│       ├── core/             # Config, security, middleware
│       ├── agents/           # AI agents (PydanticAI)
│       ├── clients/          # External service clients
│       ├── commands/         # CLI commands
│       ├── pipelines/        # Data processing
│       └── worker/           # Celery tasks
├── frontend/
│   └── src/
│       ├── app/              # Next.js App Router
│       ├── components/       # React components
│       ├── hooks/            # Custom hooks
│       ├── stores/           # Zustand stores
│       └── lib/              # Utilities
└── docs/                     # Documentation
```

## Documentation

- [Architecture Guide](docs/architecture.md) - System architecture and design
- [Adding Features](docs/adding_features.md) - How to add new features
- [Code Patterns](docs/patterns.md) - Common patterns and conventions
- [Testing Guide](docs/testing.md) - Testing strategies and examples
- [Frontend Guide](docs/frontend.md) - Frontend architecture and patterns

## Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
ENVIRONMENT=local
POSTGRES_HOST=localhost
POSTGRES_PASSWORD=secret
SECRET_KEY=change-me-use-openssl-rand-hex-32
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=your-google-api-key
```

## License

Private - All rights reserved.
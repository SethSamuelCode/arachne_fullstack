# Testing Guide

## Running Tests

```bash
# Using make (recommended)
make test             # Run all tests
make test-cov         # Run with coverage

# Via Docker (for LLMs)
docker compose exec app pytest
docker compose exec app pytest --cov=app --cov-report=term-missing

# Direct commands (from backend/)
pytest
pytest --cov=app --cov-report=term-missing

# Run specific test file
pytest tests/api/test_health.py -v

# Run specific test
pytest tests/api/test_health.py::test_health_check -v

# Run with verbose output
pytest -v

# Stop on first failure
pytest -x
```

## Test Structure

```
tests/
├── conftest.py           # Shared fixtures
├── api/                  # API endpoint tests
│   ├── test_auth.py
│   ├── test_exceptions.py
│   ├── test_files.py
│   ├── test_health.py
│   ├── test_items.py
│   ├── test_metrics.py
│   └── test_users.py
├── test_admin.py         # Admin functionality tests
├── test_agents.py        # AI agent tests
├── test_clients.py       # External client tests
├── test_commands.py      # CLI command tests
├── test_core.py          # Core utilities tests
├── test_pipelines.py     # Pipeline tests
├── test_repositories.py  # Repository tests
├── test_security.py      # Security tests
├── test_services.py      # Service tests
└── test_worker.py        # Celery task tests
```

## Key Fixtures (`conftest.py`)

```python
# Database session for tests
@pytest.fixture
async def db_session():
    async with async_session() as session:
        yield session
        await session.rollback()

# Test client
@pytest.fixture
def client():
    return TestClient(app)

# Authenticated client
@pytest.fixture
async def auth_client(client, test_user):
    token = create_access_token(test_user.id)
    client.headers["Authorization"] = f"Bearer {token}"
    return client
```

## Writing Tests

### API Endpoint Test
```python
def test_health_check(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
```

### Service Test
```python
async def test_create_item(db_session):
    service = ItemService(db_session)
    item = await service.create(ItemCreate(name="Test"))
    assert item.name == "Test"
```

### Test with Authentication
```python
def test_protected_endpoint(auth_client):
    response = auth_client.get("/api/v1/users/me")
    assert response.status_code == 200
```

## Frontend Tests

```bash
# Using bun (from frontend/)
bun test              # Run unit tests (Vitest)
bun test --watch      # Watch mode
bun test:e2e          # Run E2E tests (Playwright)
bun test:e2e --headed # E2E in headed mode (see browser)

# Via Docker (for LLMs)
docker compose exec frontend bun test
docker compose exec frontend bun test:e2e
```

## Test Database

Tests use a separate test database or SQLite in-memory:
- Configuration in `tests/conftest.py`
- Database is reset between tests
- Use fixtures for test data

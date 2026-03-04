"""Tests for agent run HTTP endpoints."""

from datetime import UTC, datetime

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from httpx import AsyncClient, ASGITransport

from app.main import app
from app.api.deps import get_redis, get_db_session, get_current_user
from app.db.models.user import UserRole


class MockUser:
    """Mock user for testing."""

    def __init__(self, id=None, email="test@example.com"):
        self.id = id or uuid4()
        self.email = email
        self.full_name = "Test User"
        self.is_active = True
        self.is_superuser = False
        self.role = UserRole.USER
        self.hashed_password = "hashed"
        self.created_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)
        self.default_model = "gpt-4o-mini"
        self.default_system_prompt = None
        self.theme = None


@pytest.fixture
def mock_user():
    return MockUser()


@pytest.fixture
def mock_redis_client():
    mock = MagicMock()
    mock.hgetall = AsyncMock(return_value={})
    mock.hset = AsyncMock()
    mock.xadd = AsyncMock(return_value="1-0")
    mock.set = AsyncMock()
    mock.exists = AsyncMock(return_value=False)
    mock.expire = AsyncMock(return_value=True)
    mock.xread = AsyncMock(return_value=None)
    return mock


@pytest.fixture
async def client(mock_user, mock_redis_client, mock_db_session, monkeypatch):
    from app.core import config

    # Bypass CSRF protection
    monkeypatch.setattr(config.settings, "INTERNAL_API_KEY", "test-key")

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_redis] = lambda: mock_redis_client
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Internal-API-Key": "test-key"},
    ) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_start_agent_run(client, mock_user, mock_redis_client):
    """Test POST /api/v1/agent/run returns 202 with job_id."""
    with (
        patch("app.api.routes.v1.agent.run_agent_task") as mock_task,
        patch("app.api.routes.v1.agent.get_db_context") as mock_db_ctx,
        patch("app.api.routes.v1.agent.get_conversation_service") as mock_conv,
        patch("app.api.routes.v1.agent.enrich_history_with_tool_calls") as mock_enrich,
    ):
        mock_task.delay = MagicMock()
        mock_task.delay.return_value.id = "celery-task-id"

        mock_svc = MagicMock()
        mock_conversation = MagicMock()
        mock_conversation.id = uuid4()
        mock_conversation.system_prompt = "You are helpful"
        mock_svc.create_conversation = AsyncMock(return_value=mock_conversation)
        mock_svc.add_message = AsyncMock()
        mock_svc.get_conversation = AsyncMock(return_value=mock_conversation)
        mock_conv.return_value = mock_svc

        mock_db = AsyncMock()
        mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_enrich.return_value = []

        response = await client.post("/api/v1/agent/run", json={
            "content": "Hello",
        })

    assert response.status_code == 202
    data = response.json()
    assert "job_id" in data
    assert "conversation_id" in data
    assert "stream_url" in data
    assert data["stream_url"].startswith("/api/v1/agent/run/")


@pytest.mark.anyio
async def test_cancel_agent_run(client, mock_user, mock_redis_client):
    """Test POST /api/v1/agent/run/{job_id}/cancel."""
    job_id = str(uuid4())
    mock_redis_client.hgetall = AsyncMock(return_value={
        "status": "running",
        "user_id": str(mock_user.id),
    })

    response = await client.post(f"/api/v1/agent/run/{job_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelling"


@pytest.mark.anyio
async def test_cancel_nonexistent_job(client, mock_redis_client):
    """Test cancel returns 404 for unknown job."""
    mock_redis_client.hgetall = AsyncMock(return_value={})
    response = await client.post(f"/api/v1/agent/run/{uuid4()}/cancel")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_cancel_unauthorized_job(client, mock_redis_client):
    """Test cancel returns 403 for other user's job."""
    job_id = str(uuid4())
    mock_redis_client.hgetall = AsyncMock(return_value={
        "status": "running",
        "user_id": str(uuid4()),  # Different user
    })

    response = await client.post(f"/api/v1/agent/run/{job_id}/cancel")
    assert response.status_code == 403


@pytest.mark.anyio
async def test_get_job_status(client, mock_user, mock_redis_client):
    """Test GET /api/v1/agent/run/{job_id}/status."""
    job_id = str(uuid4())
    mock_redis_client.hgetall = AsyncMock(return_value={
        "status": "running",
        "conversation_id": str(uuid4()),
        "user_id": str(mock_user.id),
        "started_at": "2026-03-03T00:00:00+00:00",
    })

    response = await client.get(f"/api/v1/agent/run/{job_id}/status")
    assert response.status_code == 200
    assert response.json()["status"] == "running"


@pytest.mark.anyio
async def test_get_status_not_found(client, mock_redis_client):
    """Test status returns 404 for unknown job."""
    mock_redis_client.hgetall = AsyncMock(return_value={})
    response = await client.get(f"/api/v1/agent/run/{uuid4()}/status")
    assert response.status_code == 404

"""Tests for the /models endpoint."""
import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_get_models_returns_list(client: AsyncClient):
    """GET /api/v1/models returns a list of available models."""
    response = await client.get("/api/v1/models")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 7


@pytest.mark.anyio
async def test_get_models_schema(client: AsyncClient):
    """Each model entry has the expected fields."""
    response = await client.get("/api/v1/models")
    models = response.json()
    for m in models:
        assert "id" in m
        assert "label" in m
        assert "provider" in m
        assert "supports_thinking" in m
        assert isinstance(m["supports_thinking"], bool)


@pytest.mark.anyio
async def test_get_models_includes_glm5(client: AsyncClient):
    """GLM-5 appears in the models list."""
    response = await client.get("/api/v1/models")
    ids = [m["id"] for m in response.json()]
    assert "glm-5" in ids


@pytest.mark.anyio
async def test_get_models_no_auth_required(client: AsyncClient):
    """The /models endpoint is public — no auth header needed."""
    # client fixture has no Authorization header by default
    response = await client.get("/api/v1/models")
    assert response.status_code == 200

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


@pytest.mark.anyio
async def test_models_response_has_modalities(client: AsyncClient):
    """Each model entry has a modalities object with images, audio, video fields."""
    response = await client.get("/api/v1/models")
    models = response.json()
    for m in models:
        assert "modalities" in m
        assert "images" in m["modalities"]
        assert "audio" in m["modalities"]
        assert "video" in m["modalities"]
        assert isinstance(m["modalities"]["images"], bool)
        assert isinstance(m["modalities"]["audio"], bool)
        assert isinstance(m["modalities"]["video"], bool)


@pytest.mark.anyio
async def test_glm5_modalities_all_false(client: AsyncClient):
    """GLM-5 modalities are all false — it's a text-only Vertex AI model."""
    response = await client.get("/api/v1/models")
    glm5 = next(m for m in response.json() if m["id"] == "glm-5")
    assert glm5["modalities"]["images"] is False
    assert glm5["modalities"]["audio"] is False
    assert glm5["modalities"]["video"] is False


@pytest.mark.anyio
async def test_gemini_modalities_all_true(client: AsyncClient):
    """Gemini 2.5 Flash modalities are all true — it supports multimodal input."""
    response = await client.get("/api/v1/models")
    gemini = next(m for m in response.json() if m["id"] == "gemini-2.5-flash")
    assert gemini["modalities"]["images"] is True
    assert gemini["modalities"]["audio"] is True
    assert gemini["modalities"]["video"] is True

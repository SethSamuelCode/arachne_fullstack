# Provider-Agnostic LLM Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rework the LLM loading pipeline into a provider-agnostic system, add GLM-5 via Vertex AI, and serve the model list from a backend endpoint so the frontend never needs updating when new models are added.

**Architecture:** A `ModelProvider` abstract base class in `backend/app/agents/providers/` captures all per-model knowledge (model construction, token counting, capability flags). A `MODEL_REGISTRY` dict maps user-facing model IDs to provider instances. `AssistantAgent` and `optimize_context_window` receive a resolved `ModelProvider` object — they have zero hardcoded Gemini logic after this change. A public `GET /api/v1/models` endpoint serves the model list from the registry, and the frontend profile page fetches it on mount.

**Tech Stack:** PydanticAI (`GoogleModel`, `GoogleProvider`, `GoogleModelSettings`), Google GenAI SDK (`google.genai`), FastAPI, Next.js API Routes, pytest/anyio

---

## Important: What Changes Where

`GeminiModelName` enum and `DEFAULT_GEMINI_MODEL` are currently used in **5 places** and must be migrated:
1. `schemas/models.py` — defines them (replace with `ModelInfo` + plain string constant)
2. `schemas/__init__.py` — re-exports them (update exports)
3. `schemas/spawn_agent_deps.py` — uses `GeminiModelName` as `model_name` type
4. `agents/tool_register.py` — uses `GeminiModelName` in `spawn_agent` tool + creates `GoogleModel` directly with hardcoded settings
5. `core/cache_manager.py` — imports `DEFAULT_GEMINI_MODEL` for cache warmup

`count_tokens_batch` in `context_optimizer.py` moves into `GeminiModelProvider.count_tokens()`.
`MODEL_CONTEXT_LIMITS` dict in `context_optimizer.py` is deleted — each provider exposes `context_limit`.

---

## Task 1: Add Vertex AI config fields

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Test: `backend/tests/test_core.py` (add to existing)

**Step 1: Write the failing test**

In `backend/tests/test_core.py`, add:
```python
def test_gcp_config_defaults():
    """GCP fields parse from settings with correct defaults."""
    from app.core.config import Settings
    s = Settings(
        SECRET_KEY="a" * 32,
        GCP_PROJECT=None,
        GCP_LOCATION="global",
        GOOGLE_APPLICATION_CREDENTIALS=None,
    )
    assert s.GCP_PROJECT is None
    assert s.GCP_LOCATION == "global"
    assert s.GOOGLE_APPLICATION_CREDENTIALS is None


def test_gcp_project_set(monkeypatch):
    """GCP_PROJECT reads from environment."""
    import os
    monkeypatch.setenv("GCP_PROJECT", "my-project-123")
    from app.core import config as cfg
    import importlib
    importlib.reload(cfg)
    assert cfg.settings.GCP_PROJECT == "my-project-123"
```

**Step 2: Run test to verify it fails**

```bash
cd backend && source .venv/bin/activate && pytest tests/test_core.py::test_gcp_config_defaults -v
```
Expected: `FAILED` — attribute `GCP_PROJECT` does not exist on `Settings`

**Step 3: Add the three fields to Settings**

In `backend/app/core/config.py`, after the `GOOGLE_CACHE_TTL_SECONDS` block (around line 252), add:
```python
    # === Google Cloud Platform (Vertex AI) ===
    # Required for Vertex AI model providers (e.g., GLM-5 via Vertex)
    GCP_PROJECT: str | None = None
    GCP_LOCATION: str = "global"
    # Path to service account JSON key file for Vertex AI authentication.
    # The Google SDK reads this from the environment automatically.
    GOOGLE_APPLICATION_CREDENTIALS: str | None = None
```

Also add `"GOOGLE_APPLICATION_CREDENTIALS"` to the `sanitize_sensitive_strings` validator field list (it's a file path, but sanitizing whitespace/quotes is still useful):
```python
    @field_validator(
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "REDIS_PASSWORD",
        "TAVILY_API_KEY",
        "OPENALEX_API_KEY",
        "SEMANTIC_SCHOLAR_API_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",  # add this line
        mode="before",
    )
```

**Step 4: Update .env.example**

In `backend/.env.example`, add a Vertex AI section (find an appropriate place near the Google API key block):
```bash
# === Google Cloud Platform (Vertex AI) ===
# Required only for Vertex AI models (e.g., GLM-5)
GCP_PROJECT=
GCP_LOCATION=global
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json
```

**Step 5: Run test to verify it passes**

```bash
pytest tests/test_core.py::test_gcp_config_defaults -v
```
Expected: `PASSED`

**Step 6: Commit**

```bash
git add backend/app/core/config.py backend/.env.example backend/tests/test_core.py
git commit -m "feat: add GCP Vertex AI config fields (GCP_PROJECT, GCP_LOCATION, GOOGLE_APPLICATION_CREDENTIALS)"
```

---

## Task 2: Create ModelProvider base class

**Files:**
- Create: `backend/app/agents/providers/__init__.py`
- Create: `backend/app/agents/providers/base.py`
- Create: `backend/tests/test_providers.py`

**Step 1: Write the failing test**

Create `backend/tests/test_providers.py`:
```python
"""Tests for the ModelProvider base class and provider infrastructure."""
import pytest


class _ConcreteProvider:
    """Minimal concrete implementation for testing the base class interface."""

    def __init__(self):
        from app.agents.providers.base import ModelProvider
        # Dynamically create a concrete subclass
        class _Impl(ModelProvider):
            def create_pydantic_model(self, using_cached_tools=False, cached_content_name=None):
                return "mock_model"

        self._impl = _Impl(
            model_id="test-model",
            api_model_id="test-model-api",
            display_name="Test Model",
            provider_label="Test Provider",
            context_limit=100_000,
        )

    def __getattr__(self, name):
        return getattr(self._impl, name)


def test_provider_default_capabilities():
    """Base ModelProvider returns False for caching and thinking by default."""
    p = _ConcreteProvider()
    assert p.supports_caching is False
    assert p.supports_thinking is False


def test_provider_context_limit():
    """ModelProvider exposes context_limit from constructor."""
    p = _ConcreteProvider()
    assert p.context_limit == 100_000


def test_provider_model_id():
    """ModelProvider exposes model_id and api_model_id."""
    p = _ConcreteProvider()
    assert p.model_id == "test-model"
    assert p.api_model_id == "test-model-api"


@pytest.mark.anyio
async def test_provider_default_count_tokens():
    """Default count_tokens uses char/4 estimation."""
    p = _ConcreteProvider()
    messages = [
        {"role": "user", "content": "Hello world"},          # 11 chars → 2 tokens
        {"role": "assistant", "content": "Hi there friend"},  # 15 chars → 3 tokens
    ]
    result = await p.count_tokens(messages, system_prompt="System")  # 6 chars → 1 token
    assert result == (11 // 4) + (15 // 4) + (6 // 4)


def test_provider_display_metadata():
    """ModelProvider exposes display_name and provider_label."""
    p = _ConcreteProvider()
    assert p.display_name == "Test Model"
    assert p.provider_label == "Test Provider"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_providers.py -v
```
Expected: `FAILED` — `ModuleNotFoundError: No module named 'app.agents.providers'`

**Step 3: Create the package and base class**

Create `backend/app/agents/providers/__init__.py`:
```python
"""LLM model provider abstractions."""

from app.agents.providers.base import ModelProvider

__all__ = ["ModelProvider"]
```

Create `backend/app/agents/providers/base.py`:
```python
"""Abstract base class for LLM model providers.

To add a new model:
1. If it's a new provider family → create a subclass in providers/
2. If it's the same family → instantiate the existing class with new params
3. Add an entry to MODEL_REGISTRY in providers/registry.py
No other files need changing.
"""

from abc import ABC, abstractmethod
from typing import Any


class ModelProvider(ABC):
    """Abstract base for all LLM model providers.

    Encapsulates everything provider-specific:
    - How to construct a PydanticAI model object
    - How to count tokens (API call or estimation)
    - What capabilities the model supports
    """

    def __init__(
        self,
        model_id: str,
        api_model_id: str,
        display_name: str,
        provider_label: str,
        context_limit: int = 850_000,
    ) -> None:
        """Initialise a model provider.

        Args:
            model_id: User-facing registry key (stored in DB), e.g. "gemini-2.5-flash".
            api_model_id: Actual model identifier sent to the API. May differ from
                model_id for Vertex AI models (e.g. "publishers/zai-org/models/glm-5-maas").
            display_name: Human-readable label shown in the UI.
            provider_label: Provider name shown in the UI, e.g. "Google Gemini".
            context_limit: Input token budget (typically 85% of model's max context).
        """
        self.model_id = model_id
        self.api_model_id = api_model_id
        self.display_name = display_name
        self.provider_label = provider_label
        self._context_limit = context_limit

    @abstractmethod
    def create_pydantic_model(
        self,
        using_cached_tools: bool = False,
        cached_content_name: str | None = None,
    ) -> Any:
        """Create and return the configured PydanticAI model object.

        Args:
            using_cached_tools: True when tools are stored in a Gemini CachedContent
                entry and must be stripped from the live request.
            cached_content_name: Gemini CachedContent name to attach to model settings.
                Ignored by providers that don't support caching.
        """
        ...

    async def count_tokens(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
    ) -> int:
        """Count tokens for the given messages.

        Default implementation uses a char/4 heuristic. Override in provider
        subclasses that have a native token-counting API.

        Args:
            messages: Conversation history as list of {"role": ..., "content": ...}.
            system_prompt: Optional system prompt to include in the count.

        Returns:
            Estimated total token count.
        """
        total = sum(len(m["content"]) // 4 for m in messages)
        if system_prompt:
            total += len(system_prompt) // 4
        return total

    @property
    def supports_caching(self) -> bool:
        """Whether this provider supports Gemini CachedContent API (75% cost reduction)."""
        return False

    @property
    def supports_thinking(self) -> bool:
        """Whether this provider produces thinking/reasoning traces."""
        return False

    @property
    def context_limit(self) -> int:
        """Token budget for context (input + history)."""
        return self._context_limit
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_providers.py -v
```
Expected: all 5 tests `PASSED`

**Step 5: Commit**

```bash
git add backend/app/agents/providers/ backend/tests/test_providers.py
git commit -m "feat: add ModelProvider abstract base class"
```

---

## Task 3: Create Gemini model providers

**Files:**
- Create: `backend/app/agents/providers/gemini.py`
- Modify: `backend/app/agents/providers/__init__.py`
- Modify: `backend/tests/test_providers.py`

**Step 1: Write the failing tests**

Add to `backend/tests/test_providers.py`:
```python
def test_gemini25_supports_caching():
    """Gemini 2.5 provider reports supports_caching=True."""
    from app.agents.providers.gemini import Gemini25ModelProvider
    p = Gemini25ModelProvider(
        model_id="gemini-2.5-flash",
        api_model_id="gemini-2.5-flash",
        display_name="Gemini 2.5 Flash",
        provider_label="Google Gemini",
        context_limit=891_289,
    )
    assert p.supports_caching is True
    assert p.supports_thinking is True


def test_gemini3_supports_caching():
    """Gemini 3 provider reports supports_caching=True."""
    from app.agents.providers.gemini import Gemini3ModelProvider
    p = Gemini3ModelProvider(
        model_id="gemini-3-pro-preview",
        api_model_id="gemini-3-pro-preview",
        display_name="Gemini 3 Pro (Preview)",
        provider_label="Google Gemini",
        context_limit=1_700_000,
    )
    assert p.supports_caching is True
    assert p.supports_thinking is True


@pytest.mark.anyio
async def test_gemini25_count_tokens_falls_back_on_error(monkeypatch):
    """Gemini 2.5 count_tokens falls back to estimation when API fails."""
    from app.agents.providers.gemini import Gemini25ModelProvider

    async def _fake_count(*args, **kwargs):
        raise RuntimeError("API unavailable")

    monkeypatch.setattr(
        "app.agents.providers.gemini._count_tokens_via_api",
        _fake_count,
    )

    p = Gemini25ModelProvider(
        model_id="gemini-2.5-flash",
        api_model_id="gemini-2.5-flash",
        display_name="Gemini 2.5 Flash",
        provider_label="Google Gemini",
        context_limit=891_289,
    )
    messages = [{"role": "user", "content": "Hello world"}]
    result = await p.count_tokens(messages, system_prompt="sys")
    # Should not raise; falls back to char/4
    assert isinstance(result, int)
    assert result > 0
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_providers.py::test_gemini25_supports_caching -v
```
Expected: `FAILED` — `ModuleNotFoundError: No module named 'app.agents.providers.gemini'`

**Step 3: Create `backend/app/agents/providers/gemini.py`**

```python
"""Gemini model providers (Google direct API).

Two concrete providers map to Gemini model generations:
- Gemini25ModelProvider: Gemini 2.5 family (flash-lite, flash, pro)
- Gemini3ModelProvider:  Gemini 3 family (flash-preview, pro-preview, 3.1-pro-preview)

Each generation has its own _build_model_settings() so generation-specific
API differences (thinking config, safety config, etc.) stay isolated.
"""

import logging
from abc import abstractmethod
from typing import Any

from google.genai.types import HarmBlockThreshold, HarmCategory, ThinkingLevel
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings

from app.agents.cached_google_model import CachedContentGoogleModel
from app.agents.providers.base import ModelProvider

logger = logging.getLogger(__name__)

# All harm categories disabled for maximum permissiveness
PERMISSIVE_SAFETY_SETTINGS: list[dict[str, Any]] = [
    {"category": HarmCategory.HARM_CATEGORY_HARASSMENT, "threshold": HarmBlockThreshold.OFF},
    {"category": HarmCategory.HARM_CATEGORY_HATE_SPEECH, "threshold": HarmBlockThreshold.OFF},
    {"category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, "threshold": HarmBlockThreshold.OFF},
    {"category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, "threshold": HarmBlockThreshold.OFF},
    {"category": HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY, "threshold": HarmBlockThreshold.OFF},
]

# Gemini count_tokens API limit per call (conservative)
_COUNT_TOKENS_CHUNK_LIMIT = 900_000


async def _count_tokens_via_api(
    messages: list[dict[str, str]],
    model_id: str,
    system_prompt: str | None = None,
) -> int:
    """Count tokens using Gemini's native count_tokens API.

    Handles chunking for contexts exceeding the 1M API limit.
    Extracted as a module-level function so tests can monkeypatch it.

    Args:
        messages: Conversation history.
        model_id: Gemini model name for accurate tokenisation.
        system_prompt: Optional system prompt to include in count.

    Returns:
        Total token count.
    """
    from google import genai
    from google.genai import types as genai_types

    from app.core.config import settings

    client = genai.Client(api_key=settings.GOOGLE_API_KEY)

    def _estimate(text: str) -> int:
        return len(text) // 4

    def _to_contents(msgs: list[dict[str, str]]) -> list[genai_types.Content]:
        return [
            genai_types.Content(
                role="user" if m["role"] == "user" else "model",
                parts=[genai_types.Part(text=m["content"])],
            )
            for m in msgs
        ]

    estimated_total = sum(_estimate(m["content"]) for m in messages)
    if system_prompt:
        estimated_total += _estimate(system_prompt)

    if estimated_total < _COUNT_TOKENS_CHUNK_LIMIT:
        contents = _to_contents(messages)
        config: dict[str, Any] = {}
        if system_prompt:
            config["system_instruction"] = system_prompt
        result = await client.aio.models.count_tokens(
            model=model_id,
            contents=contents,
            config=config if config else None,
        )
        return result.total_tokens or 0

    # Chunked counting for very large contexts
    total = 0
    if system_prompt:
        result = await client.aio.models.count_tokens(
            model=model_id,
            contents=[
                genai_types.Content(
                    role="user", parts=[genai_types.Part(text=system_prompt)]
                )
            ],
        )
        total += result.total_tokens or 0

    chunk: list[dict[str, str]] = []
    chunk_est = 0
    for msg in messages:
        msg_est = _estimate(msg["content"])
        if chunk_est + msg_est > _COUNT_TOKENS_CHUNK_LIMIT and chunk:
            result = await client.aio.models.count_tokens(
                model=model_id, contents=_to_contents(chunk)
            )
            total += result.total_tokens or 0
            chunk = []
            chunk_est = 0
        chunk.append(msg)
        chunk_est += msg_est

    if chunk:
        result = await client.aio.models.count_tokens(
            model=model_id, contents=_to_contents(chunk)
        )
        total += result.total_tokens or 0

    return total


class GeminiModelProvider(ModelProvider):
    """Base for all Google direct-API Gemini model providers.

    Subclasses implement _build_model_settings() with generation-specific config.
    Shared: CachedContent support, Gemini API token counting, provider label.
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("provider_label", "Google Gemini")
        super().__init__(**kwargs)

    @property
    def supports_caching(self) -> bool:
        return True

    @property
    def supports_thinking(self) -> bool:
        return True

    @abstractmethod
    def _build_model_settings(
        self,
        cached_content_name: str | None = None,
    ) -> GoogleModelSettings:
        """Return generation-specific GoogleModelSettings."""
        ...

    def create_pydantic_model(
        self,
        using_cached_tools: bool = False,
        cached_content_name: str | None = None,
    ) -> CachedContentGoogleModel:
        settings = self._build_model_settings(cached_content_name=cached_content_name)
        return CachedContentGoogleModel(
            model_name=self.api_model_id,
            settings=settings,
            using_cached_tools=using_cached_tools,
        )

    async def count_tokens(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
    ) -> int:
        """Count tokens via Gemini API with estimation fallback."""
        try:
            return await _count_tokens_via_api(messages, self.api_model_id, system_prompt)
        except Exception as e:
            logger.warning(f"Gemini token count API failed, using estimation: {e}")
            return await super().count_tokens(messages, system_prompt)


class Gemini25ModelProvider(GeminiModelProvider):
    """Provider for the Gemini 2.5 model family (flash-lite, flash, pro).

    Configuration: ThinkingLevel.HIGH with include_thoughts=True,
    all safety filters disabled, CachedContent support enabled.
    """

    def _build_model_settings(
        self,
        cached_content_name: str | None = None,
    ) -> GoogleModelSettings:
        return GoogleModelSettings(
            google_safety_settings=PERMISSIVE_SAFETY_SETTINGS,
            google_thinking_config={
                "thinking_level": ThinkingLevel.HIGH,
                "include_thoughts": True,
            },
            google_cached_content=cached_content_name,
        )


class Gemini3ModelProvider(GeminiModelProvider):
    """Provider for the Gemini 3 model family (flash-preview, pro-preview, 3.1-pro-preview).

    Add Gemini 3-specific config differences here (thinking API changes,
    different safety filter names, preview-specific params, etc.).
    """

    def _build_model_settings(
        self,
        cached_content_name: str | None = None,
    ) -> GoogleModelSettings:
        return GoogleModelSettings(
            google_safety_settings=PERMISSIVE_SAFETY_SETTINGS,
            google_thinking_config={
                "thinking_level": ThinkingLevel.HIGH,
                "include_thoughts": True,
            },
            google_cached_content=cached_content_name,
        )
```

**Step 4: Update `backend/app/agents/providers/__init__.py`**

```python
"""LLM model provider abstractions."""

from app.agents.providers.base import ModelProvider
from app.agents.providers.gemini import (
    Gemini25ModelProvider,
    Gemini3ModelProvider,
    GeminiModelProvider,
)

__all__ = [
    "ModelProvider",
    "GeminiModelProvider",
    "Gemini25ModelProvider",
    "Gemini3ModelProvider",
]
```

**Step 5: Run tests**

```bash
pytest tests/test_providers.py -v
```
Expected: all tests `PASSED`

**Step 6: Commit**

```bash
git add backend/app/agents/providers/gemini.py backend/app/agents/providers/__init__.py backend/tests/test_providers.py
git commit -m "feat: add Gemini25ModelProvider and Gemini3ModelProvider"
```

---

## Task 4: Create Vertex AI provider

**Files:**
- Create: `backend/app/agents/providers/vertex.py`
- Modify: `backend/app/agents/providers/__init__.py`
- Modify: `backend/tests/test_providers.py`

**Step 1: Write the failing tests**

Add to `backend/tests/test_providers.py`:
```python
def test_vertex_does_not_support_caching():
    """VertexModelProvider reports supports_caching=False."""
    from app.agents.providers.vertex import VertexModelProvider
    p = VertexModelProvider(
        model_id="glm-5",
        api_model_id="publishers/zai-org/models/glm-5-maas",
        display_name="GLM-5 (Vertex AI)",
        provider_label="Google Vertex AI",
        context_limit=128_000,
    )
    assert p.supports_caching is False
    assert p.supports_thinking is False


def test_vertex_create_model_raises_without_gcp_project(monkeypatch):
    """VertexModelProvider raises ExternalServiceError when GCP_PROJECT is unset."""
    from app.agents.providers.vertex import VertexModelProvider
    from app.core import config

    monkeypatch.setattr(config.settings, "GCP_PROJECT", None)
    monkeypatch.setattr(config.settings, "GOOGLE_APPLICATION_CREDENTIALS", "/creds.json")

    p = VertexModelProvider(
        model_id="glm-5",
        api_model_id="publishers/zai-org/models/glm-5-maas",
        display_name="GLM-5 (Vertex AI)",
        provider_label="Google Vertex AI",
        context_limit=128_000,
    )

    from app.core.exceptions import ExternalServiceError
    with pytest.raises(ExternalServiceError, match="GCP_PROJECT"):
        p.create_pydantic_model()


def test_vertex_create_model_raises_without_credentials(monkeypatch):
    """VertexModelProvider raises ExternalServiceError when credentials are unset."""
    from app.agents.providers.vertex import VertexModelProvider
    from app.core import config

    monkeypatch.setattr(config.settings, "GCP_PROJECT", "my-project")
    monkeypatch.setattr(config.settings, "GOOGLE_APPLICATION_CREDENTIALS", None)

    p = VertexModelProvider(
        model_id="glm-5",
        api_model_id="publishers/zai-org/models/glm-5-maas",
        display_name="GLM-5 (Vertex AI)",
        provider_label="Google Vertex AI",
        context_limit=128_000,
    )

    from app.core.exceptions import ExternalServiceError
    with pytest.raises(ExternalServiceError, match="GOOGLE_APPLICATION_CREDENTIALS"):
        p.create_pydantic_model()


@pytest.mark.anyio
async def test_vertex_count_tokens_uses_estimation():
    """VertexModelProvider.count_tokens uses char/4 estimation (no API call)."""
    from app.agents.providers.vertex import VertexModelProvider
    p = VertexModelProvider(
        model_id="glm-5",
        api_model_id="publishers/zai-org/models/glm-5-maas",
        display_name="GLM-5 (Vertex AI)",
        provider_label="Google Vertex AI",
        context_limit=128_000,
    )
    messages = [{"role": "user", "content": "1234"}]  # 4 chars → 1 token
    result = await p.count_tokens(messages)
    assert result == 1
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_providers.py::test_vertex_does_not_support_caching -v
```
Expected: `FAILED` — `ModuleNotFoundError: No module named 'app.agents.providers.vertex'`

**Step 3: Create `backend/app/agents/providers/vertex.py`**

```python
"""Vertex AI model provider.

Supports any model deployed on Google Vertex AI, including third-party models
like GLM-5 (ZhipuAI) via the Vertex AI Model Garden.

Authentication uses Application Default Credentials (ADC). Set
GOOGLE_APPLICATION_CREDENTIALS in your environment (or .env) to point
to a service account JSON key file.
"""

import logging
import os

from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from app.agents.providers.base import ModelProvider
from app.core.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)


class VertexModelProvider(ModelProvider):
    """Provider for models deployed on Google Vertex AI.

    Does NOT support:
    - Gemini CachedContent API (Vertex uses a different caching mechanism)
    - Gemini safety settings (HarmCategory is Gemini-specific)
    - Gemini ThinkingLevel (model-dependent; set to False for GLM-5)

    Token counting uses char/4 estimation (no Vertex token-counting endpoint
    in the current PydanticAI/GenAI SDK integration).
    """

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("provider_label", "Google Vertex AI")
        super().__init__(**kwargs)

    @property
    def supports_caching(self) -> bool:
        return False

    @property
    def supports_thinking(self) -> bool:
        return False

    def create_pydantic_model(
        self,
        using_cached_tools: bool = False,
        cached_content_name: str | None = None,
    ) -> GoogleModel:
        """Create a GoogleModel configured for Vertex AI.

        Args:
            using_cached_tools: Ignored — Vertex AI does not support CachedContent.
            cached_content_name: Ignored — Vertex AI does not support CachedContent.

        Raises:
            ExternalServiceError: If GCP_PROJECT or GOOGLE_APPLICATION_CREDENTIALS
                are not configured.
        """
        from app.core.config import settings

        if not settings.GCP_PROJECT:
            raise ExternalServiceError(
                "GCP_PROJECT must be set in your environment to use Vertex AI models. "
                "Add it to your .env file."
            )
        if not settings.GOOGLE_APPLICATION_CREDENTIALS:
            raise ExternalServiceError(
                "GOOGLE_APPLICATION_CREDENTIALS must be set to the path of your "
                "service account JSON key file to use Vertex AI models."
            )

        # Ensure the credentials path is visible to the Google SDK.
        # pydantic-settings reads .env into Settings but does not set os.environ,
        # so we propagate it explicitly for the Google SDK's ADC lookup.
        os.environ.setdefault(
            "GOOGLE_APPLICATION_CREDENTIALS", settings.GOOGLE_APPLICATION_CREDENTIALS
        )

        provider = GoogleProvider(
            vertexai=True,
            project=settings.GCP_PROJECT,
            location=settings.GCP_LOCATION,
        )
        logger.debug(
            f"Creating Vertex AI model: {self.api_model_id} "
            f"(project={settings.GCP_PROJECT}, location={settings.GCP_LOCATION})"
        )
        return GoogleModel(self.api_model_id, provider=provider)
```

**Step 4: Update `backend/app/agents/providers/__init__.py`**

```python
"""LLM model provider abstractions."""

from app.agents.providers.base import ModelProvider
from app.agents.providers.gemini import (
    Gemini25ModelProvider,
    Gemini3ModelProvider,
    GeminiModelProvider,
)
from app.agents.providers.vertex import VertexModelProvider

__all__ = [
    "ModelProvider",
    "GeminiModelProvider",
    "Gemini25ModelProvider",
    "Gemini3ModelProvider",
    "VertexModelProvider",
]
```

**Step 5: Run tests**

```bash
pytest tests/test_providers.py -v
```
Expected: all tests `PASSED`

**Step 6: Commit**

```bash
git add backend/app/agents/providers/vertex.py backend/app/agents/providers/__init__.py backend/tests/test_providers.py
git commit -m "feat: add VertexModelProvider for Vertex AI models (GLM-5)"
```

---

## Task 5: Create the model registry

**Files:**
- Create: `backend/app/agents/providers/registry.py`
- Modify: `backend/app/agents/providers/__init__.py`
- Modify: `backend/tests/test_providers.py`

**Step 1: Write the failing tests**

Add to `backend/tests/test_providers.py`:
```python
def test_registry_get_known_provider():
    """get_provider returns correct provider for a known model ID."""
    from app.agents.providers.registry import get_provider
    from app.agents.providers.gemini import Gemini25ModelProvider
    p = get_provider("gemini-2.5-flash")
    assert isinstance(p, Gemini25ModelProvider)
    assert p.model_id == "gemini-2.5-flash"


def test_registry_get_unknown_model_returns_default():
    """get_provider returns the default model when given an unknown ID."""
    from app.agents.providers.registry import get_provider, DEFAULT_MODEL_ID
    p = get_provider("totally-unknown-model-xyz")
    assert p.model_id == DEFAULT_MODEL_ID


def test_registry_get_glm5():
    """GLM-5 is registered and returns a VertexModelProvider."""
    from app.agents.providers.registry import get_provider
    from app.agents.providers.vertex import VertexModelProvider
    p = get_provider("glm-5")
    assert isinstance(p, VertexModelProvider)
    assert p.api_model_id == "publishers/zai-org/models/glm-5-maas"


def test_registry_get_model_list_structure():
    """get_model_list returns list of dicts with required keys."""
    from app.agents.providers.registry import get_model_list
    models = get_model_list()
    assert len(models) >= 7  # 6 Gemini + at least 1 Vertex
    for m in models:
        assert "id" in m
        assert "label" in m
        assert "provider" in m
        assert "supports_thinking" in m
        assert isinstance(m["supports_thinking"], bool)


def test_registry_all_gemini_models_registered():
    """All Gemini model IDs from the old GeminiModelName enum are registered."""
    from app.agents.providers.registry import MODEL_REGISTRY
    expected = {
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-3-flash-preview",
        "gemini-3-pro-preview",
        "gemini-3.1-pro-preview",
        "glm-5",
    }
    assert expected.issubset(MODEL_REGISTRY.keys())
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_providers.py::test_registry_get_known_provider -v
```
Expected: `FAILED` — `ModuleNotFoundError: No module named 'app.agents.providers.registry'`

**Step 3: Create `backend/app/agents/providers/registry.py`**

```python
"""Model registry — single source of truth for all available LLM models.

To add a new model:
1. Import (or create) the appropriate ModelProvider subclass.
2. Add an entry to MODEL_REGISTRY below.
3. That's it. The API endpoint, context optimizer, and agent will pick it up
   automatically — no other files need changing.
"""

import logging
from typing import Any

from app.agents.providers.gemini import Gemini25ModelProvider, Gemini3ModelProvider
from app.agents.providers.vertex import VertexModelProvider
from app.agents.providers.base import ModelProvider

logger = logging.getLogger(__name__)

# The default model used when the user has no preference set.
DEFAULT_MODEL_ID = "gemini-2.5-flash"

# Master model registry. Key = user-facing model ID (stored in DB and sent by frontend).
# Adding a new model: add one entry here. Nothing else needs changing.
MODEL_REGISTRY: dict[str, ModelProvider] = {
    # ── Gemini 2.5 family ────────────────────────────────────────────────────
    "gemini-2.5-flash-lite": Gemini25ModelProvider(
        model_id="gemini-2.5-flash-lite",
        api_model_id="gemini-2.5-flash-lite",
        display_name="Gemini 2.5 Flash Lite",
        context_limit=891_289,  # 1M × 0.85
    ),
    "gemini-2.5-flash": Gemini25ModelProvider(
        model_id="gemini-2.5-flash",
        api_model_id="gemini-2.5-flash",
        display_name="Gemini 2.5 Flash",
        context_limit=891_289,
    ),
    "gemini-2.5-pro": Gemini25ModelProvider(
        model_id="gemini-2.5-pro",
        api_model_id="gemini-2.5-pro",
        display_name="Gemini 2.5 Pro",
        context_limit=891_289,
    ),
    # ── Gemini 3 family ──────────────────────────────────────────────────────
    "gemini-3-flash-preview": Gemini3ModelProvider(
        model_id="gemini-3-flash-preview",
        api_model_id="gemini-3-flash-preview",
        display_name="Gemini 3 Flash (Preview)",
        context_limit=850_000,  # 1M × 0.85
    ),
    "gemini-3-pro-preview": Gemini3ModelProvider(
        model_id="gemini-3-pro-preview",
        api_model_id="gemini-3-pro-preview",
        display_name="Gemini 3 Pro (Preview)",
        context_limit=1_700_000,  # 2M × 0.85
    ),
    "gemini-3.1-pro-preview": Gemini3ModelProvider(
        model_id="gemini-3.1-pro-preview",
        api_model_id="gemini-3.1-pro-preview",
        display_name="Gemini 3.1 Pro (Preview)",
        context_limit=1_700_000,
    ),
    # ── Vertex AI models ─────────────────────────────────────────────────────
    "glm-5": VertexModelProvider(
        model_id="glm-5",
        api_model_id="publishers/zai-org/models/glm-5-maas",
        display_name="GLM-5 (Vertex AI)",
        context_limit=108_000,  # 128K × 0.85
    ),
}


def get_provider(model_id: str) -> ModelProvider:
    """Look up a model provider by ID.

    Falls back to the default model if the ID is not registered, so callers
    never have to handle a missing-key error.

    Args:
        model_id: User-facing model identifier (e.g. "gemini-2.5-flash", "glm-5").

    Returns:
        Configured ModelProvider instance.
    """
    provider = MODEL_REGISTRY.get(model_id)
    if provider is None:
        logger.warning(
            f"Unknown model ID '{model_id}', falling back to default '{DEFAULT_MODEL_ID}'"
        )
        return MODEL_REGISTRY[DEFAULT_MODEL_ID]
    return provider


def get_model_list() -> list[dict[str, Any]]:
    """Return the full model list for the /models API endpoint.

    Returns:
        List of dicts with keys: id, label, provider, supports_thinking.
        Order matches MODEL_REGISTRY insertion order.
    """
    return [
        {
            "id": p.model_id,
            "label": p.display_name,
            "provider": p.provider_label,
            "supports_thinking": p.supports_thinking,
        }
        for p in MODEL_REGISTRY.values()
    ]
```

**Step 4: Update `backend/app/agents/providers/__init__.py`**

```python
"""LLM model provider abstractions."""

from app.agents.providers.base import ModelProvider
from app.agents.providers.gemini import (
    Gemini25ModelProvider,
    Gemini3ModelProvider,
    GeminiModelProvider,
)
from app.agents.providers.vertex import VertexModelProvider
from app.agents.providers.registry import (
    DEFAULT_MODEL_ID,
    MODEL_REGISTRY,
    get_model_list,
    get_provider,
)

__all__ = [
    "ModelProvider",
    "GeminiModelProvider",
    "Gemini25ModelProvider",
    "Gemini3ModelProvider",
    "VertexModelProvider",
    "MODEL_REGISTRY",
    "DEFAULT_MODEL_ID",
    "get_provider",
    "get_model_list",
]
```

**Step 5: Run tests**

```bash
pytest tests/test_providers.py -v
```
Expected: all tests `PASSED`

**Step 6: Commit**

```bash
git add backend/app/agents/providers/registry.py backend/app/agents/providers/__init__.py backend/tests/test_providers.py
git commit -m "feat: add MODEL_REGISTRY with get_provider() and get_model_list()"
```

---

## Task 6: Update context_optimizer to use ModelProvider

**Files:**
- Modify: `backend/app/agents/context_optimizer.py`
- Modify: `backend/tests/test_core.py` (or wherever context optimizer tests live)

**Background:** `optimize_context_window` currently takes `model_name: str` and hard-codes Gemini assumptions. After this task it takes `provider: ModelProvider`. The `count_tokens_batch` function moves to `GeminiModelProvider.count_tokens()` (Task 3). The `MODEL_CONTEXT_LIMITS` dict is deleted.

**Step 1: Write the failing test**

Check where context optimizer tests currently live:
```bash
grep -r "optimize_context_window\|count_tokens_batch" backend/tests/ --include="*.py" -l
```

Add to whichever test file covers this (likely `tests/test_core.py` or create `tests/test_context_optimizer.py`):
```python
@pytest.mark.anyio
async def test_optimize_context_skips_caching_for_vertex(monkeypatch):
    """optimize_context_window does not attempt Gemini caching for Vertex providers."""
    from app.agents.providers.vertex import VertexModelProvider
    from app.agents.context_optimizer import optimize_context_window

    cache_calls = []

    async def _mock_get_cached(*args, **kwargs):
        cache_calls.append(args)
        return "fake-cache-name"

    monkeypatch.setattr(
        "app.agents.context_optimizer.get_cached_content", _mock_get_cached
    )
    # Enable caching in settings
    from app.core import config
    monkeypatch.setattr(config.settings, "ENABLE_SYSTEM_PROMPT_CACHING", True)

    provider = VertexModelProvider(
        model_id="glm-5",
        api_model_id="publishers/zai-org/models/glm-5-maas",
        display_name="GLM-5",
        provider_label="Google Vertex AI",
        context_limit=128_000,
    )
    mock_redis = object()  # any truthy object

    result = await optimize_context_window(
        history=[{"role": "user", "content": "hi"}],
        provider=provider,
        system_prompt="You are helpful.",
        tool_definitions=[{"name": "t", "description": "d", "parameters": {}}],
        redis_client=mock_redis,
    )

    # Vertex provider should never trigger Gemini caching
    assert len(cache_calls) == 0
    assert result["cached_prompt_name"] is None


@pytest.mark.anyio
async def test_optimize_context_uses_provider_context_limit():
    """optimize_context_window trims history based on provider.context_limit."""
    from app.agents.providers.gemini import Gemini25ModelProvider
    from app.agents.context_optimizer import optimize_context_window

    provider = Gemini25ModelProvider(
        model_id="gemini-2.5-flash",
        api_model_id="gemini-2.5-flash",
        display_name="Gemini 2.5 Flash",
        context_limit=100,  # tiny budget to force trimming
    )

    # Many messages that exceed the budget
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": "word " * 20}
        for i in range(20)
    ]

    result = await optimize_context_window(
        history=history,
        provider=provider,
        max_context_tokens=100,
    )
    # Should have trimmed; fewer messages than input
    assert len(result["history"]) < len(history)
```

**Step 2: Run to verify failure**

```bash
pytest -k "test_optimize_context" -v
```
Expected: `FAILED` — `optimize_context_window` still takes `model_name: str`

**Step 3: Update `context_optimizer.py`**

Make these targeted changes (search for the exact strings):

**3a. Update the `optimize_context_window` signature** — change `model_name: str` to `provider: "ModelProvider"`:

```python
# Remove this import at the top (if present as a TYPE_CHECKING import):
# from app.agents.providers.base import ModelProvider  ← add this

# Change function signature from:
async def optimize_context_window(
    history: list[dict[str, str]],
    model_name: str,
    ...

# To:
async def optimize_context_window(
    history: list[dict[str, str]],
    provider: "ModelProvider",
    ...
```

Add to the `TYPE_CHECKING` block at the top:
```python
if TYPE_CHECKING:
    from app.clients.redis import RedisClient
    from app.agents.providers.base import ModelProvider  # add this line
```

**3b. Replace the caching guard** — change the condition inside `optimize_context_window` from:
```python
    if (
        system_prompt
        and tool_definitions
        and redis_client
        and settings.ENABLE_SYSTEM_PROMPT_CACHING
    ):
```
to:
```python
    if (
        system_prompt
        and tool_definitions
        and redis_client
        and settings.ENABLE_SYSTEM_PROMPT_CACHING
        and provider.supports_caching
    ):
```

**3c. Replace token budget lookup** — change:
```python
    budget = max_context_tokens or MODEL_CONTEXT_LIMITS.get(model_name, DEFAULT_TOKEN_BUDGET)
```
to:
```python
    budget = max_context_tokens or provider.context_limit
```

**3d. Replace `count_tokens_batch` call in `optimize_context_window`** — find the call to `count_tokens_batch` inside `optimize_context_window` (it's used in the chunked counting path) and replace with:
```python
    # Token counting now delegated to the provider
    # (Gemini providers call the API; others use char/4 estimation)
```
Note: `count_tokens_batch` is not called from `optimize_context_window` directly — it's only called from within `get_cached_content()` indirectly and from the cache_manager. Check if it's directly called in `optimize_context_window`; if not, skip this sub-step.

**3e. Delete `MODEL_CONTEXT_LIMITS` dict and `DEFAULT_TOKEN_BUDGET` constant**, and delete the `count_tokens_batch` function (its logic moved to `GeminiModelProvider.count_tokens()`). Also delete `_get_genai_client` only if it's no longer used — check if `get_cached_content` still needs it (it does: keep `_get_genai_client`).

**3f. Update the logging line that references model_name** — change:
```python
    total_budget = max_context_tokens or MODEL_CONTEXT_LIMITS.get(model_name, DEFAULT_TOKEN_BUDGET)
```
to:
```python
    total_budget = max_context_tokens or provider.context_limit
```

Also update the log line that mentions `cache_status` and uses `model_name` if present.

**3g. Update `get_token_budget()`** — this exported function is now a thin wrapper. Change it to:
```python
def get_token_budget(model_name: str) -> int:
    """Get the token budget for a model by ID.

    Args:
        model_name: Model ID (e.g. "gemini-2.5-flash").

    Returns:
        Token budget for the model (from registry), or the default budget.
    """
    from app.agents.providers.registry import get_provider
    return get_provider(model_name).context_limit
```

**Step 4: Run tests**

```bash
pytest -k "test_optimize_context" -v
```
Expected: `PASSED`

```bash
pytest tests/ -v --ignore=tests/test_agents.py -x
```
Expected: no new failures

**Step 5: Commit**

```bash
git add backend/app/agents/context_optimizer.py backend/tests/
git commit -m "refactor: context_optimizer uses ModelProvider instead of hardcoded Gemini model_name"
```

---

## Task 7: Update AssistantAgent to use ModelProvider

**Files:**
- Modify: `backend/app/agents/assistant.py`

**Background:** `AssistantAgent.__init__` currently takes `model_name: str | None` and builds a hardcoded `CachedContentGoogleModel` with Gemini-specific settings in `_create_agent()`. After this task, it takes a `ModelProvider` and delegates model construction to `provider.create_pydantic_model()`. The `PERMISSIVE_SAFETY_SETTINGS` and `ThinkingLevel` imports are deleted from `assistant.py`.

**Step 1: No new test needed** — the existing `test_agents.py` suite covers the agent. Run it first to establish a baseline:
```bash
pytest tests/test_agents.py -v 2>&1 | head -40
```

**Step 2: Rewrite `assistant.py`**

Replace the entire file with:
```python
"""Assistant agent with PydanticAI.

The main conversational agent that can be extended with custom tools.
Model-specific behaviour (safety settings, thinking config, caching) is
encapsulated in ModelProvider subclasses — this module has no knowledge of
specific providers.
"""

import logging
from collections.abc import Sequence
from typing import Any

from pydantic_ai import Agent, BinaryContent, UsageLimits
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)

from app.agents.prompts import DEFAULT_SYSTEM_PROMPT
from app.agents.providers.base import ModelProvider
from app.agents.providers.registry import DEFAULT_MODEL_ID, get_provider
from app.agents.tool_register import register_tools
from app.core.config import settings
from app.schemas.assistant import Deps

logger = logging.getLogger(__name__)

UserContent = str | BinaryContent
MultimodalInput = str | Sequence[UserContent]


class AssistantAgent:
    """Assistant agent wrapper for conversational AI.

    Encapsulates agent creation and execution with tool support.
    Delegates all provider-specific concerns to the ModelProvider.
    """

    def __init__(
        self,
        provider: ModelProvider,
        system_prompt: str | None = None,
        cached_prompt_name: str | None = None,
        skip_tool_registration: bool = False,
    ):
        self.provider = provider
        self.model_name = provider.model_id  # exposed for DB persistence
        # If using cached prompt, don't pass system_prompt (it's in the cache)
        self.system_prompt = None if cached_prompt_name else (system_prompt or DEFAULT_SYSTEM_PROMPT)
        self.cached_prompt_name = cached_prompt_name
        self.skip_tool_registration = skip_tool_registration
        self._agent: Agent[Deps, str] | None = None

    def _create_agent(self) -> Agent[Deps, str]:
        """Create and configure the PydanticAI agent."""
        using_cached_tools = bool(self.cached_prompt_name)

        # Delegate model creation to the provider — no hardcoded Gemini logic here
        model = self.provider.create_pydantic_model(
            using_cached_tools=using_cached_tools,
            cached_content_name=self.cached_prompt_name,
        )

        agent_kwargs: dict[str, Any] = {
            "model": model,
            "deps_type": Deps,
            "retries": settings.AGENT_TOOL_RETRIES,
            "output_retries": settings.AGENT_OUTPUT_RETRIES,
        }
        if self.system_prompt:
            agent_kwargs["system_prompt"] = self.system_prompt

        agent = Agent[Deps, str](**agent_kwargs)

        register_tools(agent)

        if using_cached_tools:
            logger.debug("Tools registered locally (will be stripped from API request)")

        return agent

    @property
    def agent(self) -> Agent[Deps, str]:
        """Get or create the agent instance."""
        if self._agent is None:
            self._agent = self._create_agent()
        return self._agent

    async def run(
        self,
        user_input: MultimodalInput,
        history: list[dict[str, str]] | None = None,
        deps: Deps | None = None,
    ) -> tuple[str, list[Any], Deps]:
        """Run agent and return the output along with tool call events."""
        model_history: list[ModelRequest | ModelResponse] = []

        for msg in history or []:
            if msg["role"] == "user":
                model_history.append(ModelRequest(parts=[UserPromptPart(content=msg["content"])]))
            elif msg["role"] == "assistant":
                model_history.append(ModelResponse(parts=[TextPart(content=msg["content"])]))
            elif msg["role"] == "system":
                model_history.append(ModelRequest(parts=[SystemPromptPart(content=msg["content"])]))

        agent_deps = deps if deps is not None else Deps()

        if isinstance(user_input, str):
            logger.info(f"Running agent with user input: {user_input[:100]}...")
        else:
            text_parts = [p for p in user_input if isinstance(p, str)]
            image_count = sum(1 for p in user_input if isinstance(p, BinaryContent))
            logger.info(
                f"Running agent with multimodal input: "
                f"{text_parts[0][:50] if text_parts else '(no text)'}... ({image_count} image(s))"
            )

        result = await self.agent.run(user_input, deps=agent_deps, message_history=model_history)

        tool_events: list[Any] = []
        for message in result.all_messages():
            if hasattr(message, "parts"):
                for part in message.parts:
                    if hasattr(part, "tool_name"):
                        tool_events.append(part)

        logger.info(f"Agent run complete. Output length: {len(result.output)} chars")
        return result.output, tool_events, agent_deps

    async def iter(
        self,
        user_input: MultimodalInput,
        history: list[dict[str, str]] | None = None,
        deps: Deps | None = None,
    ):
        """Stream agent execution with full event access."""
        model_history: list[ModelRequest | ModelResponse] = []

        for msg in history or []:
            if msg["role"] == "user":
                model_history.append(ModelRequest(parts=[UserPromptPart(content=msg["content"])]))
            elif msg["role"] == "assistant":
                model_history.append(ModelResponse(parts=[TextPart(content=msg["content"])]))
            elif msg["role"] == "system":
                model_history.append(ModelRequest(parts=[SystemPromptPart(content=msg["content"])]))

        agent_deps = deps if deps is not None else Deps()

        async with self.agent.iter(
            user_input,
            deps=agent_deps,
            message_history=model_history,
            usage_limits=UsageLimits(
                request_limit=settings.AGENT_MAX_REQUESTS,
                tool_calls_limit=settings.AGENT_MAX_TOOL_CALLS,
            ),
        ) as run:
            async for event in run:
                yield event


def get_agent(
    system_prompt: str | None = None,
    model_name: str | None = None,
    provider: ModelProvider | None = None,
    cached_prompt_name: str | None = None,
    skip_tool_registration: bool = False,
) -> AssistantAgent:
    """Factory function to create an AssistantAgent.

    Accepts either a pre-resolved ModelProvider or a model_name string.
    If both are given, provider takes precedence.

    Args:
        system_prompt: Custom system prompt (ignored if cached_prompt_name is provided).
        model_name: Model ID to look up in the registry (e.g. "gemini-2.5-flash").
        provider: Pre-resolved ModelProvider (preferred over model_name).
        cached_prompt_name: Gemini cache name for the content (75% cost savings).
        skip_tool_registration: Unused parameter kept for backward compatibility.

    Returns:
        Configured AssistantAgent instance.
    """
    resolved_provider = provider or get_provider(model_name or DEFAULT_MODEL_ID)
    return AssistantAgent(
        provider=resolved_provider,
        system_prompt=system_prompt,
        cached_prompt_name=cached_prompt_name,
        skip_tool_registration=skip_tool_registration,
    )


async def run_agent(
    user_input: str,
    history: list[dict[str, str]],
    deps: Deps | None = None,
    system_prompt: str | None = None,
) -> tuple[str, list[Any], Deps]:
    """Convenience function for backwards compatibility."""
    agent = get_agent(system_prompt=system_prompt)
    return await agent.run(user_input, history, deps)
```

**Step 3: Run tests**

```bash
pytest tests/test_agents.py -v
```
Expected: all agent tests pass (or only the pre-existing failures remain)

**Step 4: Commit**

```bash
git add backend/app/agents/assistant.py
git commit -m "refactor: AssistantAgent delegates model creation to ModelProvider"
```

---

## Task 8: Remove GeminiModelName — update schemas, spawn_agent_deps, tool_register, cache_manager

**Files:**
- Modify: `backend/app/schemas/models.py`
- Modify: `backend/app/schemas/__init__.py`
- Modify: `backend/app/schemas/spawn_agent_deps.py`
- Modify: `backend/app/agents/tool_register.py`
- Modify: `backend/app/core/cache_manager.py`

**Background:** `GeminiModelName` is a Gemini-specific enum used as a type annotation in `spawn_agent_deps.py` and in `tool_register.py`'s `spawn_agent` tool. Replacing it with `str` plus registry validation makes it provider-agnostic. `DEFAULT_GEMINI_MODEL` becomes `DEFAULT_MODEL_ID` imported from the registry.

**Step 1: No new test needed** — run existing tests to establish a baseline:
```bash
pytest tests/test_agents.py tests/test_core.py tests/test_tool_schemas.py -v 2>&1 | tail -20
```

**Step 2: Update `backend/app/schemas/models.py`**

Replace the entire file:
```python
"""Shared schema primitives for model configuration."""

from pydantic import BaseModel


class ModelInfo(BaseModel):
    """Available model information returned by the /models endpoint."""

    id: str
    label: str
    provider: str
    supports_thinking: bool = False


# Backward-compatible alias. New code should import DEFAULT_MODEL_ID from
# app.agents.providers.registry. This string alias avoids circular imports
# while being importable from schemas.
DEFAULT_GEMINI_MODEL: str = "gemini-2.5-flash"
```

**Step 3: Update `backend/app/schemas/__init__.py`**

Replace the models import line:
```python
# Old:
from app.schemas.models import GeminiModelName, DEFAULT_GEMINI_MODEL

# New:
from app.schemas.models import ModelInfo, DEFAULT_GEMINI_MODEL
```

Update `__all__` — remove `"GeminiModelName"`, add `"ModelInfo"`:
```python
# Remove: "GeminiModelName",
# Keep:   "DEFAULT_GEMINI_MODEL",  (for backward compat)
# Add:    "ModelInfo",
```

**Step 4: Update `backend/app/schemas/spawn_agent_deps.py`**

```python
# Old:
from app.schemas.models import DEFAULT_GEMINI_MODEL, GeminiModelName
...
model_name: GeminiModelName = DEFAULT_GEMINI_MODEL

# New:
from app.schemas.models import DEFAULT_GEMINI_MODEL
...
model_name: str = DEFAULT_GEMINI_MODEL
```

**Step 5: Update `backend/app/agents/tool_register.py`**

5a. Remove old imports at the top of the file:
```python
# Remove these lines:
from app.schemas import DEFAULT_GEMINI_MODEL
from app.schemas.models import GeminiModelName
```

Add new imports:
```python
from app.agents.providers.registry import DEFAULT_MODEL_ID, get_provider
```

5b. In the `spawn_agent` tool function signature, change the `model_name` parameter type:
```python
# Old:
model_name: Annotated[GeminiModelName | None, Field(
    description="Model to use. 'gemini-2.5-flash' for standard tasks, ..."
)] = None,

# New:
model_name: Annotated[str | None, Field(
    description="Model ID to use. Options: 'gemini-2.5-flash-lite' (fast/cheap), "
                "'gemini-2.5-flash' (default, standard tasks), "
                "'gemini-2.5-pro' (complex reasoning), "
                "'gemini-3-flash-preview' (fast with reasoning), "
                "'gemini-3-pro-preview' (max reasoning), "
                "'glm-5' (Vertex AI). Use stronger models only when needed."
)] = None,
```

5c. Replace `effective_model` assignment:
```python
# Old:
effective_model = model_name if model_name is not None else DEFAULT_GEMINI_MODEL

# New:
effective_model = model_name if model_name is not None else DEFAULT_MODEL_ID
```

5d. Replace the hardcoded model creation block (lines ~212–226). Find:
```python
        # Model settings with safety filters disabled and thinking enabled
        model_settings_kwargs: dict[str, Any] = {
            "google_safety_settings": PERMISSIVE_SAFETY_SETTINGS,
            "google_thinking_config": {
                "thinking_level": ThinkingLevel.HIGH,
            },
        }
        # Add cached content if available
        if cached_content_name:
            model_settings_kwargs["google_cached_content"] = cached_content_name

        model_settings = GoogleModelSettings(**model_settings_kwargs)

        sub_model = GoogleModel(child_deps.model_name.value, settings=model_settings)
```

Replace with:
```python
        # Delegate sub-agent model creation to the registry provider
        sub_provider = get_provider(str(child_deps.model_name))
        sub_model = sub_provider.create_pydantic_model(
            using_cached_tools=skip_tool_registration,
            cached_content_name=cached_content_name,
        )
```

5e. Remove now-unused imports from `tool_register.py`:
```python
# Remove these imports (no longer needed):
from google.genai.types import ThinkingLevel
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings

# Also remove PERMISSIVE_SAFETY_SETTINGS if it was defined in this file
# (it moved to gemini.py). Check if it's imported from assistant.py or defined locally.
```
Check first with: `grep -n "PERMISSIVE_SAFETY_SETTINGS\|ThinkingLevel\|GoogleModel\|GoogleModelSettings" backend/app/agents/tool_register.py`

Also update `child_deps.model_name` access — since it's now `str` not an enum, change:
```python
# Old (in get_subagent_cached_content call):
model_name=effective_model.value if hasattr(effective_model, "value") else str(effective_model)

# New:
model_name=str(effective_model)
```

And in `SpawnAgentDeps` construction:
```python
model_name=effective_model,  # already a str, no change needed
```

**Step 6: Update `backend/app/core/cache_manager.py`**

Find the block around line 225:
```python
        from app.schemas.models import DEFAULT_GEMINI_MODEL

        default_model = (
            DEFAULT_GEMINI_MODEL.value
            if hasattr(DEFAULT_GEMINI_MODEL, "value")
            else str(DEFAULT_GEMINI_MODEL)
        )
```

Replace with:
```python
        from app.agents.providers.registry import DEFAULT_MODEL_ID

        default_model = DEFAULT_MODEL_ID
```

**Step 7: Run tests**

```bash
pytest tests/ -v -x --ignore=tests/test_agents.py
```
Expected: no new failures

```bash
pytest tests/test_agents.py -v
```
Expected: only pre-existing failures remain

**Step 8: Commit**

```bash
git add backend/app/schemas/models.py backend/app/schemas/__init__.py \
        backend/app/schemas/spawn_agent_deps.py backend/app/agents/tool_register.py \
        backend/app/core/cache_manager.py
git commit -m "refactor: replace GeminiModelName enum with str + provider registry"
```

---

## Task 9: Update the WebSocket handler to use provider

**Files:**
- Modify: `backend/app/api/routes/v1/agent.py`

**Step 1: Find the agent init block** (around line 474–531 in the current file):

```python
                model_name = user.default_model

                # ...

                optimized: OptimizedContext = await optimize_context_window(
                    history=conversation_history,
                    model_name=model_name or "gemini-2.5-flash",
                    ...
                )

                assistant = get_agent(
                    system_prompt=optimized["system_prompt"],
                    model_name=model_name,
                    cached_prompt_name=optimized["cached_prompt_name"],
                    skip_tool_registration=optimized["skip_tool_registration"],
                )
```

**Step 2: Replace with provider-aware code**

Add the import at the top of `agent.py`:
```python
from app.agents.providers.registry import DEFAULT_MODEL_ID, get_provider
```

Replace the agent init block:
```python
                # Resolve provider once — used by both optimize_context_window and get_agent
                provider = get_provider(user.default_model or DEFAULT_MODEL_ID)

                # Optimize context window with tiered memory management
                optimized: OptimizedContext = await optimize_context_window(
                    history=conversation_history,
                    provider=provider,
                    system_prompt=system_prompt,
                    tool_definitions=tool_definitions,
                    redis_client=redis_client,
                    pinned_content_hash=pinned_content_hash,
                    pinned_content_tokens=pinned_content_tokens,
                )

                # Create agent — skip_tool_registration=True when tools are in cached content
                assistant = get_agent(
                    system_prompt=optimized["system_prompt"],
                    provider=provider,
                    cached_prompt_name=optimized["cached_prompt_name"],
                    skip_tool_registration=optimized["skip_tool_registration"],
                )
```

Also remove the `model_name = user.default_model` line that was before this block.

**Step 3: Run tests**

```bash
pytest tests/ -v -x
```
Expected: all tests pass (modulo pre-existing failures)

**Step 4: Commit**

```bash
git add backend/app/api/routes/v1/agent.py
git commit -m "refactor: agent WebSocket handler uses get_provider() from registry"
```

---

## Task 10: Create `GET /api/v1/models` endpoint

**Files:**
- Create: `backend/app/api/routes/v1/models.py`
- Modify: `backend/app/api/routes/v1/__init__.py`
- Modify: `backend/tests/api/test_models.py` (new file)

**Step 1: Write the failing test**

Create `backend/tests/api/test_models.py`:
```python
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
```

**Step 2: Run to verify failure**

```bash
pytest tests/api/test_models.py -v
```
Expected: `FAILED` — 404 Not Found

**Step 3: Create `backend/app/api/routes/v1/models.py`**

```python
"""Models endpoint — returns the available LLM model list."""

from fastapi import APIRouter

from app.agents.providers.registry import get_model_list
from app.schemas.models import ModelInfo

router = APIRouter()


@router.get("/models", response_model=list[ModelInfo])
async def list_models() -> list[dict]:
    """Return all available LLM models.

    No authentication required — this is public configuration data,
    equivalent to a health check. The frontend uses this to populate
    the model selector on the profile page.

    Returns:
        List of model descriptors with id, label, provider, supports_thinking.
    """
    return get_model_list()
```

**Step 4: Register the router in `backend/app/api/routes/v1/__init__.py`**

Add at the bottom of the imports and registration block:
```python
from app.api.routes.v1 import models

# ... existing registrations ...

# Model list (public — no auth required)
v1_router.include_router(models.router, tags=["models"])
```

**Step 5: Run tests**

```bash
pytest tests/api/test_models.py -v
```
Expected: all 4 tests `PASSED`

**Step 6: Commit**

```bash
git add backend/app/api/routes/v1/models.py backend/app/api/routes/v1/__init__.py \
        backend/tests/api/test_models.py
git commit -m "feat: add GET /api/v1/models endpoint (public, registry-driven)"
```

---

## Task 11: Update frontend — Next.js proxy + profile page

**Files:**
- Create: `frontend/src/app/api/models/route.ts`
- Modify: `frontend/src/app/[locale]/(dashboard)/profile/page.tsx`

**Step 1: Create the Next.js proxy route**

Create `frontend/src/app/api/models/route.ts`:
```typescript
import { NextResponse } from "next/server";
import { backendFetch, BackendApiError } from "@/lib/server-api";

export async function GET() {
  try {
    const data = await backendFetch("/api/v1/models");
    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json(
        { detail: error.message || "Failed to fetch models" },
        { status: error.status }
      );
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
```

**Step 2: Update `frontend/src/app/[locale]/(dashboard)/profile/page.tsx`**

Remove the hardcoded `AVAILABLE_MODELS` array (lines 16–24).

Add a `ModelOption` type and `useEffect` to fetch models. Near the top of the file (after the imports), add the type:
```typescript
type ModelOption = {
  id: string;
  label: string;
  provider: string;
  supports_thinking: boolean;
};
```

Inside `ProfilePage`, add state and fetch:
```typescript
  const [availableModels, setAvailableModels] = useState<ModelOption[]>([]);

  useEffect(() => {
    fetch("/api/models")
      .then((r) => r.json())
      .then((data: ModelOption[]) => setAvailableModels(data))
      .catch(() => {
        // Fallback so the selector still works if the fetch fails
        setAvailableModels([
          { id: "", label: "Default (Backend Configured)", provider: "", supports_thinking: false },
        ]);
      });
  }, []);
```

Update the `<select>` in the JSX to use `availableModels`:
```tsx
              {/* Default option */}
              <option value="">Default (Backend Configured)</option>
              {availableModels.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.label}
                  {model.provider ? ` — ${model.provider}` : ""}
                </option>
              ))}
```

Remove the old `{AVAILABLE_MODELS.map(...)}` block.

**Step 3: Verify frontend builds**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -v "node_modules"
```
Expected: no new type errors

**Step 4: Commit**

```bash
git add frontend/src/app/api/models/route.ts \
        frontend/src/app/\[locale\]/\(dashboard\)/profile/page.tsx
git commit -m "feat: frontend fetches model list from API instead of hardcoded array"
```

---

## Task 12: Full test run + cleanup

**Step 1: Run the full backend test suite**

```bash
cd backend && source .venv/bin/activate && pytest tests/ -v 2>&1 | tail -30
```
Expected: all tests pass except the pre-existing `test_sanitize_preserves_required_fields` failure.

**Step 2: Check for any remaining GeminiModelName references**

```bash
grep -r "GeminiModelName" backend/ --include="*.py"
```
Expected: no output (fully removed)

**Step 3: Check for remaining hardcoded model_name string references in the optimizer/agent**

```bash
grep -n "gemini-2.5-flash\|MODEL_CONTEXT_LIMITS\|count_tokens_batch" \
  backend/app/agents/context_optimizer.py backend/app/agents/assistant.py
```
Expected: `context_optimizer.py` should have no `MODEL_CONTEXT_LIMITS` or `count_tokens_batch`. `gemini-2.5-flash` should only appear in `registry.py`.

**Step 4: Run linter**

```bash
cd backend && ruff check app/ --fix && ruff format app/
```
Fix any reported issues.

**Step 5: Final commit**

```bash
git add -u
git commit -m "chore: lint fixes after provider-agnostic LLM refactor"
```

---

## Extension Guide (for future models)

**Adding a new Gemini model:**
```python
# In registry.py, add one entry:
"gemini-4-pro": Gemini3ModelProvider(
    model_id="gemini-4-pro",
    api_model_id="gemini-4-pro",
    display_name="Gemini 4 Pro",
    context_limit=2_000_000,
),
```
Done. Frontend updates automatically via the `/models` endpoint.

**Adding a new Vertex AI model:**
```python
# In registry.py:
"llama-3-70b": VertexModelProvider(
    model_id="llama-3-70b",
    api_model_id="meta/llama-3-70b-instruct-maas",
    display_name="Llama 3 70B (Vertex AI)",
    context_limit=108_000,
),
```

**Adding a new provider family (e.g. OpenAI):**
1. Create `backend/app/agents/providers/openai.py` with `class OpenAIModelProvider(ModelProvider)`
2. Implement `create_pydantic_model()` using PydanticAI's `OpenAIModel`
3. Add entries to `MODEL_REGISTRY`
4. Add `OPENAI_API_KEY` to config if not already present

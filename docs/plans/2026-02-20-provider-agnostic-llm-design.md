# Provider-Agnostic LLM Pipeline Design

**Date:** 2026-02-20
**Status:** Approved
**Goal:** Rework the LLM loading pipeline so new models can be added without touching agent or optimizer code. Add GLM-5 via Google Vertex AI as the first non-Gemini model.

---

## Problem

The current pipeline has Gemini-specific assumptions baked into three places:

1. **`AssistantAgent._create_agent()`** — hardcodes Gemini safety settings (`HarmCategory`/`HarmBlockThreshold`), `ThinkingLevel.HIGH`, and always wraps the model in `CachedContentGoogleModel`.
2. **`context_optimizer.py`** — uses Gemini's `CachedContent` API for caching and Gemini's `count_tokens` API for token counting; neither is available for Vertex AI models.
3. **Frontend profile page** — `AVAILABLE_MODELS` is a hardcoded TypeScript array; adding a backend model requires a separate frontend deploy.

---

## Solution: ModelProvider Abstraction + Registry + Models Endpoint

### Provider Class Hierarchy

```
ModelProvider (ABC)                    base.py
├── GeminiModelProvider (ABC)          gemini.py  — Google direct API
│   ├── Gemini25ModelProvider          — ThinkingLevel.HIGH, safety filters, CachedContent
│   └── Gemini3ModelProvider           — generation-specific config differences
└── VertexModelProvider                vertex.py  — GoogleProvider(vertexai=True), no caching
```

Each class is responsible for:
- `create_pydantic_model(using_cached_tools, cached_content_name)` → PydanticAI model object
- `count_tokens(messages, system_prompt)` → Gemini subclasses use the API; Vertex falls back to char/4 estimation
- Properties: `supports_caching`, `supports_thinking`, `context_limit`, `display_name`, `provider_label`

`CachedContentGoogleModel` is retained; returned only by Gemini provider subclasses.

### Model Registry

`backend/app/agents/providers/registry.py` holds a single `MODEL_REGISTRY: dict[str, ModelProvider]` — the canonical source of truth for all available models.

```python
MODEL_REGISTRY: dict[str, ModelProvider] = {
    # Gemini 2.5 family
    "gemini-2.5-flash-lite": Gemini25ModelProvider(...),
    "gemini-2.5-flash":      Gemini25ModelProvider(...),
    "gemini-2.5-pro":        Gemini25ModelProvider(...),
    # Gemini 3 family
    "gemini-3-flash-preview":   Gemini3ModelProvider(...),
    "gemini-3-pro-preview":     Gemini3ModelProvider(...),
    "gemini-3.1-pro-preview":   Gemini3ModelProvider(...),
    # Vertex AI models
    "glm-5": VertexModelProvider(
        api_model_id="publishers/zai-org/models/glm-5-maas",
        display_name="GLM-5 (Vertex AI)",
        ...
    ),
}
```

`MODEL_CONTEXT_LIMITS` dict in `context_optimizer.py` is deleted — each provider exposes `context_limit` directly.

### New Models Endpoint

```
GET /api/v1/models
Auth: none required (public config data)

Response:
[
  {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash", "provider": "Google Gemini", "supports_thinking": true},
  {"id": "glm-5",            "label": "GLM-5 (Vertex AI)", "provider": "Google Vertex AI", "supports_thinking": false},
  ...
]
```

Frontend profile page calls this on mount and replaces the hardcoded `AVAILABLE_MODELS` array.

### AssistantAgent + optimize_context_window

Both receive a `ModelProvider` object instead of a raw `model_name` string:

```python
# In agent.py WebSocket handler:
provider = get_provider(user.default_model or "gemini-2.5-flash")
optimized = await optimize_context_window(provider=provider, ...)
assistant = get_agent(provider=provider, cached_prompt_name=optimized["cached_prompt_name"], ...)
```

Inside `optimize_context_window`:
- `provider.supports_caching` gates the CachedContent API attempt
- `provider.count_tokens(...)` replaces the raw Gemini API call
- `provider.context_limit` replaces the `MODEL_CONTEXT_LIMITS` dict lookup

### New Config Fields

```python
# backend/app/core/config.py
GCP_PROJECT: str | None = None                   # Required for Vertex AI models
GCP_LOCATION: str = "global"                     # Vertex AI region
GOOGLE_APPLICATION_CREDENTIALS: str | None = None  # Path to service account JSON key
```

`VertexModelProvider` reads all three from `settings`. If `GCP_PROJECT` or `GOOGLE_APPLICATION_CREDENTIALS` is missing when a Vertex model is requested, it raises `ExternalServiceError` with a clear message.

---

## File Map

| Action | File |
|--------|------|
| Create | `backend/app/agents/providers/__init__.py` |
| Create | `backend/app/agents/providers/base.py` |
| Create | `backend/app/agents/providers/gemini.py` |
| Create | `backend/app/agents/providers/vertex.py` |
| Create | `backend/app/agents/providers/registry.py` |
| Create | `backend/app/api/routes/v1/models.py` |
| Modify | `backend/app/agents/assistant.py` |
| Modify | `backend/app/agents/context_optimizer.py` |
| Modify | `backend/app/schemas/models.py` |
| Modify | `backend/app/api/routes/v1/agent.py` |
| Modify | `backend/app/api/router.py` |
| Modify | `backend/app/core/config.py` |
| Modify | `frontend/src/app/[locale]/(dashboard)/profile/page.tsx` |

---

## Extension Pattern

To add a new model in the future:
1. If it's a new provider family → create a new `ModelProvider` subclass in `providers/`
2. If it's the same provider family → instantiate the existing class with new parameters
3. Add an entry to `MODEL_REGISTRY` in `registry.py`
4. Add env vars to `.env.example` if new credentials are needed
5. No changes to `AssistantAgent`, `context_optimizer`, the WebSocket handler, or the frontend

# Model Capability Flags — Design

**Date:** 2026-02-21
**Status:** Approved

## Problem

GLM-5 (Vertex AI) does not support image, audio, or video inputs. The existing code sends `BinaryContent` objects to any model without checking whether it supports multimodal input. The frontend also offers the attachment button regardless of the selected model.

## Goal

Add a structured `modalities` capability object to each `ModelProvider` so the backend can validate inputs and the frontend can conditionally show/hide the attachment UI.

## Design

### ModalitySupport schema (`app/schemas/models.py`)

```python
class ModalitySupport(BaseModel):
    images: bool = False
    audio: bool = False
    video: bool = False
```

Lives alongside `ModelInfo`. All fields default to `False` — the safe assumption for unknown providers.

### ModelProvider base (`app/agents/providers/base.py`)

Add a `modalities` property returning `ModalitySupport()` (all False by default):

```python
@property
def modalities(self) -> ModalitySupport:
    return ModalitySupport()
```

### Provider overrides

| Provider | images | audio | video |
|----------|--------|-------|-------|
| `GeminiModelProvider` | ✅ | ✅ | ✅ |
| `VertexModelProvider` | ❌ | ❌ | ❌ |

`GeminiModelProvider` overrides `modalities` to return `ModalitySupport(images=True, audio=True, video=True)`. `VertexModelProvider` inherits the all-False default.

### ModelInfo schema

```python
class ModelInfo(BaseModel):
    id: str
    label: str
    provider: str
    supports_thinking: bool = False
    modalities: ModalitySupport = ModalitySupport()
```

### Registry (`get_model_list`)

Include `modalities` in each returned dict:

```python
"modalities": provider.modalities.model_dump()
```

### API response shape

```json
[
  {
    "id": "gemini-2.5-flash",
    "label": "Gemini 2.5 Flash",
    "provider": "Google Gemini",
    "supports_thinking": true,
    "modalities": { "images": true, "audio": true, "video": true }
  },
  {
    "id": "glm-5",
    "label": "GLM-5 (Vertex AI)",
    "provider": "Google Vertex AI",
    "supports_thinking": false,
    "modalities": { "images": false, "audio": false, "video": false }
  }
]
```

### Backend validation (`app/api/routes/v1/agent.py`)

After resolving the provider, before `build_multimodal_input`:

```python
if attachments and not provider.modalities.images:
    await manager.send_event(
        websocket,
        "error",
        {"message": f"Model '{provider.display_name}' does not support image attachments."},
    )
    continue
```

Early exit — no S3 downloads, no agent calls.

### Frontend hook (`frontend/src/hooks/use-model-capabilities.ts`)

Fetches `/api/models` once per session, looks up `user.default_model` from the auth store, returns the matching `modalities` object. Defaults to all-true if the model is not found (safe fallback — unknown models should not silently break the UI).

```typescript
type Modalities = { images: boolean; audio: boolean; video: boolean };

export function useModelCapabilities(): Modalities {
  // fetch /api/models, find user.default_model entry, return .modalities
  // default: { images: true, audio: true, video: true }
}
```

### Chat input (`frontend/src/components/chat/`)

Attachment button renders only when `modalities.images` is true:

```tsx
const modalities = useModelCapabilities();
// ...
{modalities.images && <AttachmentButton ... />}
```

## Testing

| Test file | What to add |
|-----------|-------------|
| `tests/test_providers.py` | `test_gemini25_modalities_all_true`, `test_gemini3_modalities_all_true`, `test_vertex_modalities_all_false` |
| `tests/api/test_models.py` | `test_models_response_has_modalities`, `test_glm5_modalities_all_false`, `test_gemini_modalities_all_true` |
| `tests/test_agents.py` | `test_attachments_rejected_for_non_multimodal_model` |

## Files Changed

| File | Change |
|------|--------|
| `backend/app/schemas/models.py` | Add `ModalitySupport` model; add `modalities` field to `ModelInfo` |
| `backend/app/schemas/__init__.py` | Export `ModalitySupport` |
| `backend/app/agents/providers/base.py` | Import `ModalitySupport`; add `modalities` property |
| `backend/app/agents/providers/gemini.py` | Override `modalities` → all True |
| `backend/app/agents/providers/registry.py` | Include `modalities` in `get_model_list()` |
| `backend/app/api/routes/v1/agent.py` | Guard against attachments on non-multimodal models |
| `backend/tests/test_providers.py` | Add modalities tests |
| `backend/tests/api/test_models.py` | Add modalities field tests |
| `backend/tests/test_agents.py` | Add rejection test |
| `frontend/src/hooks/use-model-capabilities.ts` | New hook |
| `frontend/src/components/chat/` | Conditionally render attachment button |

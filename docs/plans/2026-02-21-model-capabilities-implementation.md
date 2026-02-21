# Model Capability Flags Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `ModalitySupport` capability object to each `ModelProvider` so the backend rejects image attachments for non-multimodal models and the frontend hides the attachment button for those models.

**Architecture:** `ModalitySupport(images, audio, video)` is a Pydantic model defined in `schemas/models.py`. `ModelProvider` base exposes a `modalities` property defaulting to all-False. `GeminiModelProvider` overrides to all-True. The `/api/v1/models` endpoint already exists and just needs `modalities` added to `ModelInfo` and `get_model_list()`. The WS handler gets an early-exit guard before `build_multimodal_input`. The frontend has a new `useModelCapabilities` hook that fetches the models list and derives the active model's modalities from the auth store user; `ChatInput` receives a `supportsImages` prop and conditionally renders `<ImageAttachmentInput>`.

**Tech Stack:** Python/Pydantic v2, FastAPI, pytest/anyio, TypeScript/React, Next.js

---

## Task 1: Add `ModalitySupport` to schemas and providers

**Files:**
- Modify: `backend/app/schemas/models.py`
- Modify: `backend/app/schemas/__init__.py`
- Modify: `backend/app/agents/providers/base.py`
- Modify: `backend/app/agents/providers/gemini.py`
- Test: `backend/tests/test_providers.py`

**Background:** `ModalitySupport` must be defined in `schemas/models.py` (next to `ModelInfo`) to avoid circular imports — schemas don't import from agents, but agents already import from schemas. The provider base imports `ModalitySupport` from schemas to type its `modalities` property. `GeminiModelProvider` (the abstract base for all Gemini providers — Gemini25 and Gemini3 both inherit from it) overrides `modalities` to return all-True. `VertexModelProvider` inherits the all-False default from `ModelProvider`.

**Step 1: Write the failing tests**

Add to `backend/tests/test_providers.py` inside the existing `TestModelProviderBase` class:

```python
    def test_base_modalities_all_false(self):
        p = StubProvider("m", "m", "M", "P")
        assert p.modalities.images is False
        assert p.modalities.audio is False
        assert p.modalities.video is False
```

Add to `TestGeminiModelProvider` class:

```python
    def test_gemini25_modalities_all_true(self):
        from app.agents.providers.gemini import Gemini25ModelProvider
        p = Gemini25ModelProvider("gemini-2.5-flash", "gemini-2.5-flash", "Gemini 2.5 Flash")
        assert p.modalities.images is True
        assert p.modalities.audio is True
        assert p.modalities.video is True

    def test_gemini3_modalities_all_true(self):
        from app.agents.providers.gemini import Gemini3ModelProvider
        p = Gemini3ModelProvider("gemini-3-flash-preview", "gemini-3-flash-preview", "Gemini 3 Flash")
        assert p.modalities.images is True
        assert p.modalities.audio is True
        assert p.modalities.video is True
```

Add to `TestVertexModelProvider` class:

```python
    def test_vertex_modalities_all_false(self):
        from app.agents.providers.vertex import VertexModelProvider
        p = VertexModelProvider("glm-5", "publishers/zai-org/models/glm-5-maas", "GLM-5")
        assert p.modalities.images is False
        assert p.modalities.audio is False
        assert p.modalities.video is False
```

**Step 2: Run to verify failure**

```bash
cd backend && source .venv/bin/activate && pytest tests/test_providers.py::TestModelProviderBase::test_base_modalities_all_false tests/test_providers.py::TestGeminiModelProvider::test_gemini25_modalities_all_true tests/test_providers.py::TestVertexModelProvider::test_vertex_modalities_all_false -v
```

Expected: `FAILED` — `AttributeError: 'StubProvider' object has no attribute 'modalities'`

**Step 3: Add `ModalitySupport` to `backend/app/schemas/models.py`**

Insert before the `ModelInfo` class (which comes after `ModalitySupport`). Add at the top of the file, after the `from pydantic import BaseModel` import:

```python
class ModalitySupport(BaseModel):
    """Supported input modalities for an LLM model."""

    images: bool = False
    audio: bool = False
    video: bool = False
```

The full updated file should look like:

```python
"""Shared schema primitives for model configuration."""

from pydantic import BaseModel


class ModalitySupport(BaseModel):
    """Supported input modalities for an LLM model."""

    images: bool = False
    audio: bool = False
    video: bool = False


class ModelInfo(BaseModel):
    """Available model information returned by the /models endpoint."""

    id: str
    label: str
    provider: str
    supports_thinking: bool = False
    modalities: ModalitySupport = ModalitySupport()


# Backward-compatible alias. New code should import DEFAULT_MODEL_ID from
# app.agents.providers.registry. This string alias avoids circular imports
# while being importable from schemas.
DEFAULT_GEMINI_MODEL: str = "gemini-2.5-flash"
DEFAULT_MODEL_ID: str = DEFAULT_GEMINI_MODEL  # Canonical alias; same as registry.DEFAULT_MODEL_ID
```

**Step 4: Export `ModalitySupport` from `backend/app/schemas/__init__.py`**

Change line 30 from:
```python
from app.schemas.models import ModelInfo, DEFAULT_GEMINI_MODEL
```
to:
```python
from app.schemas.models import ModelInfo, ModalitySupport, DEFAULT_GEMINI_MODEL
```

In `__all__`, add `"ModalitySupport"` after `"ModelInfo"`:
```python
    "ModelInfo",
    "ModalitySupport",
    "DEFAULT_GEMINI_MODEL",
```

**Step 5: Add `modalities` property to `backend/app/agents/providers/base.py`**

Add the import at the top of `base.py`, after the existing imports:
```python
from app.schemas.models import ModalitySupport
```

Add the property after the `supports_thinking` property:
```python
    @property
    def modalities(self) -> ModalitySupport:
        """Supported input modalities. Override in providers that support multimodal input."""
        return ModalitySupport()
```

**Step 6: Override `modalities` in `backend/app/agents/providers/gemini.py`**

In `GeminiModelProvider` class, add after the `supports_thinking` property (around line 105):
```python
    @property
    def modalities(self) -> ModalitySupport:
        return ModalitySupport(images=True, audio=True, video=True)
```

Also add the import at the top of `gemini.py`:
```python
from app.schemas.models import ModalitySupport
```

**Step 7: Run the tests**

```bash
cd backend && source .venv/bin/activate && pytest tests/test_providers.py -v
```

Expected: all provider tests pass including the new modalities tests.

**Step 8: Commit**

```bash
git add backend/app/schemas/models.py backend/app/schemas/__init__.py \
        backend/app/agents/providers/base.py backend/app/agents/providers/gemini.py \
        backend/tests/test_providers.py
git commit -m "feat: add ModalitySupport to providers (images/audio/video capability flags)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Expose `modalities` in `ModelInfo` and `/api/v1/models`

**Files:**
- Modify: `backend/app/agents/providers/registry.py`
- Modify: `backend/tests/api/test_models.py`

**Background:** `ModelInfo` already has `modalities: ModalitySupport = ModalitySupport()` from Task 1. Now `get_model_list()` needs to include it. The test file already exists at `backend/tests/api/test_models.py` with 4 tests — we're adding 3 more.

**Step 1: Write the failing tests**

Add to `backend/tests/api/test_models.py`:

```python
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
```

**Step 2: Run to verify failure**

```bash
cd backend && source .venv/bin/activate && pytest tests/api/test_models.py::test_models_response_has_modalities -v
```

Expected: `FAILED` — `AssertionError: assert 'modalities' in {...}` (field not yet in response)

**Step 3: Update `get_model_list()` in `backend/app/agents/providers/registry.py`**

Change the `get_model_list()` function to include `modalities`:

```python
def get_model_list() -> list[dict[str, object]]:
    """Return a list of all available models for the /models API endpoint.

    Each entry has: id, label, provider, supports_thinking, modalities.
    """
    return [
        {
            "id": provider.model_id,
            "label": provider.display_name,
            "provider": provider.provider_label,
            "supports_thinking": provider.supports_thinking,
            "modalities": provider.modalities.model_dump(),
        }
        for provider in MODEL_REGISTRY.values()
    ]
```

**Step 4: Run the tests**

```bash
cd backend && source .venv/bin/activate && pytest tests/api/test_models.py -v
```

Expected: all 7 tests pass.

**Step 5: Commit**

```bash
git add backend/app/agents/providers/registry.py backend/tests/api/test_models.py
git commit -m "feat: include modalities in /api/v1/models response

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Backend validation — reject attachments for non-multimodal models

**Files:**
- Modify: `backend/app/api/routes/v1/agent.py`
- Modify: `backend/tests/test_agents.py`

**Background:** The WS handler in `agent.py` builds multimodal input at line ~536. We extract the capability check into a small module-level helper function `_check_attachment_support()` so it can be unit-tested without spinning up a WebSocket. The helper returns `None` if the request is valid, or an error string if not.

**Step 1: Write the failing tests**

Add to `backend/tests/test_agents.py` (find a suitable class or add at the bottom of the file):

```python
class TestAttachmentCapabilityCheck:
    """Tests for the _check_attachment_support helper in agent.py."""

    def test_rejects_images_for_non_multimodal_model(self):
        """Non-multimodal provider with attachments returns an error string."""
        from app.api.routes.v1.agent import _check_attachment_support
        from app.agents.providers.vertex import VertexModelProvider
        from app.schemas.attachment import AttachmentInMessage

        provider = VertexModelProvider("glm-5", "publishers/zai-org/models/glm-5-maas", "GLM-5")
        attachments = [
            AttachmentInMessage(s3_key="test.png", mime_type="image/png", size_bytes=100)
        ]
        result = _check_attachment_support(provider, attachments)
        assert result is not None
        assert "does not support" in result
        assert "GLM-5" in result

    def test_allows_images_for_multimodal_model(self):
        """Multimodal provider with attachments returns None (no error)."""
        from app.api.routes.v1.agent import _check_attachment_support
        from app.agents.providers.gemini import Gemini25ModelProvider
        from app.schemas.attachment import AttachmentInMessage

        from unittest.mock import patch
        with patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"}):
            provider = Gemini25ModelProvider("gemini-2.5-flash", "gemini-2.5-flash", "Gemini 2.5 Flash")
        attachments = [
            AttachmentInMessage(s3_key="test.png", mime_type="image/png", size_bytes=100)
        ]
        result = _check_attachment_support(provider, attachments)
        assert result is None

    def test_no_attachments_always_passes(self):
        """No attachments returns None even for non-multimodal models."""
        from app.api.routes.v1.agent import _check_attachment_support
        from app.agents.providers.vertex import VertexModelProvider

        provider = VertexModelProvider("glm-5", "publishers/zai-org/models/glm-5-maas", "GLM-5")
        result = _check_attachment_support(provider, [])
        assert result is None
```

**Step 2: Run to verify failure**

```bash
cd backend && source .venv/bin/activate && pytest tests/test_agents.py::TestAttachmentCapabilityCheck -v
```

Expected: `FAILED` — `ImportError: cannot import name '_check_attachment_support' from 'app.api.routes.v1.agent'`

**Step 3: Add `_check_attachment_support` helper to `backend/app/api/routes/v1/agent.py`**

Find `async def build_multimodal_input(` (around line 251) and insert the helper function just before it:

```python
def _check_attachment_support(
    provider: "ModelProvider",
    attachments: "list[AttachmentInMessage]",
) -> str | None:
    """Return an error message if the provider cannot handle these attachments.

    Args:
        provider: The resolved ModelProvider for the current request.
        attachments: Validated attachments from the WebSocket message.

    Returns:
        An error string if the model does not support image input and
        attachments are present, otherwise None.
    """
    if attachments and not provider.modalities.images:
        return f"Model '{provider.display_name}' does not support image attachments."
    return None
```

Note: `ModelProvider` and `AttachmentInMessage` are already imported at the top of `agent.py`. The string quotes in the type hints are defensive; check if the imports are already at module scope (`from app.agents.providers.base import ModelProvider` and `from app.schemas.attachment import AttachmentInMessage`). If they are, remove the quotes.

**Step 4: Wire the guard into the WebSocket handler**

Find this block in the `ws_chat` handler (around line 534):

```python
                # Build multimodal input if attachments are present
                try:
                    agent_input = await build_multimodal_input(
                        user_message, attachments, str(user.id)
                    )
```

Insert the capability check immediately before it:

```python
                # Reject attachments if the model does not support multimodal input
                attachment_error = _check_attachment_support(provider, attachments)
                if attachment_error:
                    await manager.send_event(websocket, "error", {"message": attachment_error})
                    continue

                # Build multimodal input if attachments are present
                try:
                    agent_input = await build_multimodal_input(
                        user_message, attachments, str(user.id)
                    )
```

**Step 5: Run the tests**

```bash
cd backend && source .venv/bin/activate && pytest tests/test_agents.py::TestAttachmentCapabilityCheck -v
```

Expected: all 3 tests pass.

```bash
cd backend && source .venv/bin/activate && pytest tests/ -x -k "not test_sanitize_preserves_required_fields" 2>&1 | tail -20
```

Expected: all tests pass (pre-existing `test_sanitize_preserves_required_fields` failure is unrelated).

**Step 6: Commit**

```bash
git add backend/app/api/routes/v1/agent.py backend/tests/test_agents.py
git commit -m "feat: reject image attachments for non-multimodal models in WS handler

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Frontend — hook + conditional attachment button

**Files:**
- Create: `frontend/src/hooks/use-model-capabilities.ts`
- Modify: `frontend/src/components/chat/chat-input.tsx`
- Modify: `frontend/src/components/chat/chat-container.tsx`

**Background:** `ChatInput` gets a new optional `supportsImages?: boolean` prop (default `true` — safe fallback so unknown models don't silently break the UI). `ChatContainer` calls the new `useModelCapabilities` hook and passes `supportsImages={modalities.images}`. The hook fetches `/api/models` once per session (on mount), looks up the user's `default_model` from the Zustand `useAuthStore`, and returns the matching modalities. The user type is already at `@/types` and the auth store at `@/stores/auth-store`.

**Step 1: Check the user type for `default_model`**

Verify the `User` type has `default_model` by reading `frontend/src/types/auth.ts` (or wherever the `User` type lives). It should have `default_model?: string | null`. If not, add it.

```bash
grep -n "default_model" frontend/src/types/*.ts frontend/src/types/*.d.ts 2>/dev/null
```

**Step 2: Create `frontend/src/hooks/use-model-capabilities.ts`**

```typescript
"use client";

import { useState, useEffect } from "react";
import { useAuthStore } from "@/stores";

type Modalities = {
  images: boolean;
  audio: boolean;
  video: boolean;
};

type ModelEntry = {
  id: string;
  modalities: Modalities;
};

// Default: all true — safe fallback when models list hasn't loaded yet
// or when the active model is unknown. Avoids hiding the UI unexpectedly.
const DEFAULT_MODALITIES: Modalities = { images: true, audio: true, video: true };

/**
 * Returns the modality capabilities of the current user's active model.
 *
 * Fetches the models list from /api/models once per session and cross-references
 * the user's default_model from the auth store.
 *
 * Falls back to all-true (permissive) if the fetch fails or the model is unknown.
 */
export function useModelCapabilities(): Modalities {
  const user = useAuthStore((state) => state.user);
  const [models, setModels] = useState<ModelEntry[]>([]);

  useEffect(() => {
    fetch("/api/models")
      .then((r) => r.json())
      .then((data: ModelEntry[]) => setModels(data))
      .catch(() => setModels([]));
  }, []);

  if (!user?.default_model || models.length === 0) {
    return DEFAULT_MODALITIES;
  }

  const active = models.find((m) => m.id === user.default_model);
  return active?.modalities ?? DEFAULT_MODALITIES;
}
```

**Step 3: Add `supportsImages` prop to `frontend/src/components/chat/chat-input.tsx`**

Update the `ChatInputProps` interface:

```typescript
interface ChatInputProps {
  onSend: (message: string, attachments?: ChatAttachment[]) => void;
  disabled?: boolean;
  isProcessing?: boolean;
  supportsImages?: boolean;
}
```

Update the function signature to destructure the new prop (default `true`):

```typescript
export function ChatInput({ onSend, disabled, isProcessing, supportsImages = true }: ChatInputProps) {
```

In the JSX, wrap `<ImageAttachmentInput>` conditionally:

```tsx
      <div className="flex items-end gap-2">
        {supportsImages && (
          <ImageAttachmentInput
            attachments={attachments}
            onAttachmentsChange={setAttachments}
            disabled={disabled}
          />
        )}
```

**Step 4: Update `frontend/src/components/chat/chat-container.tsx`**

Add the import at the top of the file (with other hook imports):

```typescript
import { useModelCapabilities } from "@/hooks/use-model-capabilities";
```

Inside `ChatContainer`, add the hook call near the other hook calls:

```typescript
  const modalities = useModelCapabilities();
```

Pass `supportsImages` to `<ChatInput>`:

```tsx
              <ChatInput
                onSend={sendMessage}
                disabled={!isConnected || isProcessing}
                supportsImages={modalities.images}
              />
```

**Step 5: Export the hook from the hooks index (if one exists)**

Check if there's a `frontend/src/hooks/index.ts`:

```bash
ls frontend/src/hooks/index.ts 2>/dev/null && cat frontend/src/hooks/index.ts
```

If it exists, add: `export { useModelCapabilities } from "./use-model-capabilities";`

**Step 6: TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -v "node_modules" | head -20
```

Expected: only pre-existing errors (missing `date-fns`, `@radix-ui/react-scroll-area`). No new errors.

**Step 7: Commit**

```bash
git add frontend/src/hooks/use-model-capabilities.ts \
        frontend/src/components/chat/chat-input.tsx \
        frontend/src/components/chat/chat-container.tsx
# Also add index.ts if changed:
# git add frontend/src/hooks/index.ts
git commit -m "feat: hide attachment button for non-multimodal models

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Final verification

```bash
cd backend && source .venv/bin/activate && pytest tests/ -v -k "not test_sanitize_preserves_required_fields" 2>&1 | tail -20
cd backend && source .venv/bin/activate && ruff check app/ && ruff format app/ --check
cd frontend && npx tsc --noEmit 2>&1 | grep -v "node_modules" | grep -c "error" || echo "0 new errors"
```

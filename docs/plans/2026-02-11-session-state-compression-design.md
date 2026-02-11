# Session State Compression: Semantic Context Preservation

**Date:** 2026-02-11
**Branch:** `feat/llm-on-celery`
**Status:** Design

---

## Problem

When conversations grow long, the context optimizer (`context_optimizer.py`) performs FIFO truncation - it drops the oldest messages entirely when the token budget is exceeded. This causes the "lobotomy effect": the assistant loses all awareness of earlier conversation context including tone, decisions made, running jokes, and shared understanding.

The current system has ~850K-1.7M token budgets (Gemini models at 85%), so this rarely triggers in normal use. But it does happen in extended sessions, and will become critical for the planned autonomous research agent feature.

## Solution: Structured State Compression

Replace blind FIFO truncation with LLM-powered compression that extracts conversation state into a structured `SessionState` object. Older messages are replaced with a compact state snapshot that preserves factual context, emotional tone, and shared intellectual frameworks.

### Inspiration

Based on the "Semantic State Compression" protocol - treating conversation state not as text to summarize, but as **state variables** to extract. Maps the rhetorical triangle (Logos, Pathos, Ethos) into structured fields.

## Architecture

### SessionState Schema

```python
from pydantic import BaseModel

class SessionState(BaseModel):
    """Compressed conversation state."""
    logos: list[str] = []     # Hard facts, decisions, technical context (zero loss)
    pathos: list[str] = []    # Tone, metaphors, communication style
    abstract: list[str] = []  # Shared frameworks, known concepts (condescension filter)
    conversation_summary: str = ""  # 2-3 sentence narrative bridge
```

Fields use `list[str]` for flexibility - the LLM decides what's important to capture within each category. This works with Gemini's `response_schema` (constrained decoding ensures the four fields are always present and correctly typed).

**Example output:**

```json
{
  "logos": [
    "User is building an AI chat app called Arachne",
    "Stack: FastAPI + Next.js + PydanticAI + Gemini",
    "Docker sandbox supports concurrent container execution",
    "Decided on Redis pub/sub + DB checkpointing for agent durability"
  ],
  "pathos": [
    "Engaged and technically confident",
    "Prefers pragmatic solutions - asks 'is this necessary?' before building",
    "Values being consulted on architectural decisions"
  ],
  "abstract": [
    "Understands async/await vs threading deeply",
    "Familiar with pub/sub and event-driven architecture",
    "Shared metaphor: 'lobotomy effect' for context loss"
  ],
  "conversation_summary": "Discussed moving LLM calls to Celery. Concluded the async stack handles concurrency fine but Celery is needed for durability of long-running autonomous research agents. Currently designing a SessionState compression system to preserve conversation context."
}
```

### Compression Flow

```
User sends message
       │
optimize_context_window()
       │
       ├─ Load conversation.compressed_state from DB (if exists)
       ├─ Load messages AFTER compressed_at_message_id
       ├─ Calculate token budget
       │
       ├─ If total context > 70% of budget:
       │    │
       │    ├─ Select oldest N messages from recent set (enough to get under 60%)
       │    ├─ Call compress_session_state() → Gemini 3 Flash
       │    │    ├─ Input: oldest messages + existing SessionState (if any)
       │    │    ├─ Uses response_schema for structured output
       │    │    └─ Returns: merged SessionState
       │    ├─ Persist new compressed_state + compressed_at_message_id to DB
       │    └─ Remove compressed messages from working set
       │
       └─ Assemble final context:
            [SessionState synthetic message pair]  ← if state exists
            [remaining recent messages]
            [current user message]
```

### Token Budget Thresholds

| Threshold | Action |
|-----------|--------|
| < 70% | No compression, all messages included |
| 70-85% | Compression triggers, oldest messages compressed into SessionState |
| > 85% | Hard FIFO fallback (existing behavior, safety net) |

The 70% trigger leaves a 15% buffer for the compression to run before the hard cutoff. Even if a single large message jumps from below 70% to above 85%, the compression runs **synchronously before the LLM call**, so no messages are lost to blind truncation.

### Compression LLM Call

Uses **Gemini 3 Flash** with structured output (`response_schema=SessionState`).

**Compression prompt (for initial compression):**

```
You are a conversation state compiler. Analyze the following conversation
and produce a SessionState object.

Extract:
- "logos": Hard facts established - user details, decisions made, technical
  constraints, code discussed, specific values/names. Zero loss tolerance.
  When in doubt, include it.
- "pathos": Current emotional tone and direction (improving/stable/worsening),
  active metaphors or running jokes, communication style preferences,
  implicit needs.
- "abstract": Shared intellectual frameworks, concepts the user clearly
  understands (these should not be re-explained), agreed-upon premises.
- "conversation_summary": 2-3 sentence narrative of what happened and where
  things left off.
```

**Merge prompt (when previous SessionState exists):**

```
You are a conversation state compiler. You have an existing session state
from earlier compression and new messages to incorporate.

<previous_state>
{existing SessionState JSON}
</previous_state>

<new_messages>
{messages to compress}
</new_messages>

Produce a MERGED SessionState that combines the previous state with new
information. Update fields that have changed, keep fields still relevant,
drop anything contradicted or no longer applicable. Do not duplicate entries.
```

## Database Changes

### Migration: Add columns to `conversations` table

```python
# New columns on Conversation model
compressed_state: dict | None = Field(
    default=None,
    sa_column=Column(JSONB, nullable=True),
)
compressed_at_message_id: uuid.UUID | None = Field(
    default=None,
    sa_column=Column(PG_UUID(as_uuid=True), nullable=True),
)
```

- `compressed_state`: The serialized SessionState JSON
- `compressed_at_message_id`: The last message ID covered by the compression (boundary marker between compressed and full-fidelity history)

**No new tables.** Original messages remain untouched in the DB - the compressed state is a read optimization for context assembly, not a replacement. Users can still scroll through full conversation history in the UI.

## System Prompt Changes

### SessionState Awareness Block

Appended to the system prompt **always** (not conditionally). At ~50 tokens it's negligible, and keeping it permanent avoids invalidating the Gemini content cache when compression first triggers.

```
### Compressed Memory
When you see a <session_state> block at the start of conversation history,
it contains compressed context from earlier in this conversation. Use it as
follows:
- `logos`: Hard facts (user details, decisions, constraints). Treat as ground truth.
- `pathos`: Emotional tone and active metaphors. Match your tone to this state.
- `abstract`: Shared intellectual context. Do not re-explain concepts listed here.

Continue the conversation naturally as if you remember everything. Never
reference the compression or acknowledge that context was compressed.
```

### Context Window Layout

```
┌─────────────────────────────────────────────────┐
│ Gemini CachedContent (stable, long-lived)       │
│  ├─ System prompt + awareness block             │
│  ├─ Tool definitions                            │
│  └─ Pinned content (files/media)                │
├─────────────────────────────────────────────────┤
│ Message History (dynamic, per-request)          │
│  ├─ User: <session_state>{...}</session_state>  │  ← synthetic pair
│  ├─ Assistant: Understood.                      │  ← (only if state exists)
│  ├─ Recent message 1                            │
│  ├─ Recent message 2                            │
│  ├─ ...                                         │
│  └─ Current user message                        │
└─────────────────────────────────────────────────┘
```

The SessionState is injected as a user-assistant message pair to maintain PydanticAI's expected alternating message pattern.

## Gemini Content Cache Interaction

The SessionState lives in the **message history**, not the system prompt or cached content. This means:

- The Gemini content cache (system prompt + tools + pinned content) is **not affected** by compression
- No cache invalidation when compression triggers
- The awareness block is part of the system prompt and gets cached with it (effectively free)

### Design Decision: Why Message History, Not System Prompt

An alternative design would place the SessionState data in the system prompt (alongside the awareness block). Here's why message history was chosen:

**System prompt placement:**

| | |
|---|---|
| Pro | Higher attention weight - LLMs prioritize system prompt content |
| Pro | Semantically cleaner - it is context/instructions, not a message |
| Pro | No synthetic user/assistant message pair needed |
| Con | Every compression cycle changes the system prompt hash |
| Con | Changed hash **invalidates the Gemini content cache** |
| Con | Cache rebuild re-caches system prompt + tools + pinned content at full price |

**Message history placement (chosen):**

| | |
|---|---|
| Pro | System prompt cache stays stable across all compression cycles |
| Pro | 75% cost savings on system prompt + tools preserved indefinitely |
| Con | SessionState tokens (~200-800) paid at full price every request |
| Con | Requires synthetic user/assistant message pair for PydanticAI compatibility |

**The math:** System prompt + tool definitions are typically 3,000-8,000+ tokens. The SessionState is ~200-800 tokens. Caching the SessionState in the system prompt saves 75% on 200-800 tokens, but **invalidates the cache on the much larger 3,000-8,000 token payload** every time compression runs. In a long conversation where compression triggers multiple times, the system prompt approach costs significantly more due to repeated cache rebuilds. The synthetic message pair is a small aesthetic compromise for a meaningful cost advantage.

## Files to Modify

| File | Change |
|------|--------|
| `db/models/conversation.py` | Add `compressed_state` and `compressed_at_message_id` columns |
| `schemas/conversation.py` | Add `SessionState` Pydantic model, update response schemas |
| `alembic/versions/` | New migration for the two columns |
| `agents/context_optimizer.py` | Compression trigger logic, `compress_session_state()` function, modified `optimize_context_window()` |
| `agents/prompts.py` | Add `SESSION_STATE_AWARENESS_BLOCK` and compression prompts |
| `services/conversation.py` | Persist compressed state after compression |

## Edge Cases

| Case | Handling |
|------|----------|
| Single message exceeds entire budget | Input validation rejects/truncates oversized messages (separate concern) |
| Jump from <70% to >85% in one message | Compression runs synchronously before LLM call - no message loss |
| Compression LLM call fails | Graceful fallback to existing FIFO truncation with warning log |
| Very first message in conversation | No compression needed, `compressed_state` stays null |
| User changes system prompt mid-conversation | Compression is independent of system prompt, no interaction |

## Cost Analysis

- **Compression call**: Gemini 3 Flash, input = oldest messages + previous state, output = structured JSON (~200-500 tokens). Triggers only when 70% budget is exceeded.
- **Awareness block**: ~50 tokens, cached with system prompt (75% cost reduction).
- **SessionState in history**: ~200-800 tokens depending on conversation complexity. Much smaller than the messages it replaces.
- **Net effect**: Significant cost reduction on long conversations since compressed state is far smaller than raw message history.

## Future Considerations

- **Research agent compression**: Will need a different schema focused on research state (findings, hypotheses, next actions) rather than conversational rapport. Separate design.
- **Multi-session memory**: SessionState could potentially persist across conversations for user-level memory (long-term pathos/abstract). Out of scope for now.
- **Compression quality metrics**: Could track "continuity score" by comparing pre/post compression responses. Nice-to-have for iteration.

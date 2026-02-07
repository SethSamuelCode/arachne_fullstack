# Chat Initialization & Naming Redesign

## Problem

Two issues with how chats start today:

1. **Unreliable startup.** Clicking "New Chat" eagerly creates a conversation via `POST /conversations`, then the first message is sent via WebSocket with that ID. This two-step process creates a race condition — the backend's "create conversation from first message" code path (which sets the title) is skipped because the conversation already exists.

2. **Titles are often just the date.** Because the conversation is created before any message is sent, the title is `null`. The sidebar falls back to displaying the creation date.

**Root cause:** `startNewChat()` calls `createConversation()` immediately on button click, before the user has typed anything.

## Solution: Hybrid Lazy Creation + LLM Titles

### Principle

Don't create a conversation until the user takes a meaningful action (pinning content or sending a message). Then generate a descriptive title using a lightweight LLM call after the first text response.

### New Chat Flow

Clicking "New Chat" resets local state only. No API call, no database record.

```
startNewChat():
  1. clearMessages()
  2. setCurrentMessages([])
  3. setCurrentConversationId(null)
```

No entry appears in the conversation sidebar yet.

### `ensureConversation()` — Shared Lazy Creator

A new frontend utility that both the pin flow and the message flow call. Returns the existing conversation ID or creates one.

```
ensureConversation():
  1. if currentConversationId exists -> return it
  2. else -> POST /conversations (no title) -> store new ID -> return it
```

Called by:
- **Pinning flow** (`usePinFiles`): Before making the pin API call.
- **Message flow** (`useChat.sendChatMessage`): Before sending the WebSocket message. The frontend always creates the conversation — the backend WebSocket handler always receives a `conversation_id`.

When `ensureConversation()` completes, the conversation appears in the sidebar with a placeholder label (e.g., "New conversation").

### LLM Title Generation

After the first message exchange completes (user message sent, AI first text response fully streamed), the backend generates a title.

**Trigger conditions:**
- Agent has finished streaming its first text response (not just tool calls — wait for actual text output)
- `conversation.title` is `null`

**Backend flow (in `agent.py` WebSocket handler):**
1. Agent finishes first text response
2. Check: `conversation.title is None`?
3. If yes: lightweight LLM call (cheap/fast model like Gemini Flash):
   - Input: first user message + truncated first assistant response
   - Prompt: "Generate a short title (5-8 words max) for this conversation."
4. Update conversation title in DB
5. Send WebSocket event: `{ type: "conversation_updated", data: { conversation_id, title } }`

**Frontend handling:**
- New `conversation_updated` case in `use-chat.ts` WebSocket handler
- Calls `updateConversation(id, { title })` on the conversation store
- Sidebar reactively updates from placeholder to real title

**Edge cases:**
- If LLM title generation fails, fall back to first 50 chars of user message
- If user manually renamed the conversation before the LLM title arrives, don't overwrite (check title is still null before updating)

## Full Scenarios

### A: User sends a message immediately (most common)

1. Click "New Chat" -> state cleared, no conversation in DB
2. Type message, hit send
3. `ensureConversation()` -> `POST /conversations` -> get ID
4. Send WebSocket message with new `conversation_id`
5. Backend processes, streams response (possibly with tool calls first)
6. First text response finishes streaming
7. Backend: title is null -> LLM generates title -> updates DB
8. Backend sends `{ type: "conversation_updated", data: { title } }`
9. Sidebar updates from "New conversation" to real title

### B: User pins files first, then messages

1. Click "New Chat" -> state cleared, no conversation in DB
2. User selects files to pin
3. `ensureConversation()` -> `POST /conversations` -> get ID
4. Pin proceeds normally (SSE stream, 8 phases)
5. Conversation appears in sidebar as "New conversation"
6. User sends first message (conversation already exists)
7. WebSocket message sent with existing `conversation_id`
8. First text response finishes -> LLM title -> sidebar updates

### C: User pins files and never messages

1-5. Same as Scenario B
6. User closes tab or navigates away
7. Conversation exists with pinned content but no messages (acceptable — user took a real action)

## Files to Modify

### Frontend
- `hooks/use-conversations.ts` — Remove `createConversation()` from `startNewChat()`, add `ensureConversation()`
- `hooks/use-chat.ts` — Call `ensureConversation()` before WebSocket send, handle `conversation_updated` event
- `hooks/use-pin-files.ts` — Call `ensureConversation()` before pin API call (handle "no conversation yet" case)
- `stores/conversation-store.ts` — May need minor adjustments for placeholder display
- `components/chat/conversation-sidebar.tsx` — Display "New conversation" for null-title conversations

### Backend
- `api/routes/v1/agent.py` — Add LLM title generation after first text response, send `conversation_updated` event. Optionally simplify/remove the "create conversation in WebSocket" fallback.
- `services/conversation.py` — Add `generate_title()` or similar method

# System Prompt Injection Issue - Analysis & Solution

## Problem Statement

The AI assistant "Arachne" was not responding to questions about its name/identity. When asked "What is your name?", the LLM would not identify as "Arachne" despite a system prompt being defined that should instruct it to do so.

## Root Cause Analysis

### Investigation

Traced the system prompt flow through the codebase:

1. **DEFAULT_SYSTEM_PROMPT** is defined in `backend/app/agents/prompts.py`:
   ```python
   DEFAULT_SYSTEM_PROMPT = "You are Arachne, an advanced AI assistant..."
   ```

2. **WebSocket route** (`backend/app/api/routes/v1/agent.py`) handles chat messages and creates conversations.

3. **The bug**: When creating new conversations via WebSocket, the system prompt was only set if explicitly provided by the frontend:
   ```python
   # BEFORE (broken)
   conv_data = ConversationCreate(
       user_id=user.id,
       title=user_message[:50],
       system_prompt=data.get("system_prompt"),  # Returns None if not sent!
   )
   ```

4. **Second bug**: When retrieving the system prompt for agent execution:
   ```python
   # BEFORE (broken)
   system_prompt = None
   if current_conversation_id:
       current_conv = await conv_service.get_conversation(...)
       if current_conv:
           system_prompt = current_conv.system_prompt  # Could be None!
   ```

5. The `AssistantAgent` class has a fallback to `DEFAULT_SYSTEM_PROMPT`, but the `optimize_context_window()` function was passing `system_prompt=None` to it, and the `OptimizedContext` TypedDict preserved that `None` value, bypassing the fallback logic.

### Why It Happened

The system prompt fallback chain was broken at multiple points:
- New conversations stored `None` as their system_prompt
- The route passed `None` to the agent when the conversation had no system_prompt
- The context optimizer preserved the `None` value
- The agent's fallback logic wasn't reached because `None` was explicitly passed

## Solution Implemented

### 1. Added import for DEFAULT_SYSTEM_PROMPT in agent route

```python
from app.agents.prompts import DEFAULT_SYSTEM_PROMPT
```

### 2. Fixed conversation creation with proper fallback chain

```python
# AFTER (fixed)
elif not current_conversation_id:
    # Create new conversation
    # Priority: client-provided > user default > global default
    conv_system_prompt = (
        data.get("system_prompt")
        or user.default_system_prompt
        or DEFAULT_SYSTEM_PROMPT
    )
    conv_data = ConversationCreate(
        user_id=user.id,
        title=user_message[:50] if len(user_message) > 50 else user_message,
        system_prompt=conv_system_prompt,
    )
```

### 3. Fixed system prompt retrieval with proper fallback chain

```python
# AFTER (fixed)
# Priority: conversation-specific > user default > global default
system_prompt: str = DEFAULT_SYSTEM_PROMPT
if current_conversation_id:
    async with get_db_context() as db:
        conv_service = get_conversation_service(db)
        current_conv = await conv_service.get_conversation(
            UUID(current_conversation_id)
        )
        if current_conv and current_conv.system_prompt:
            system_prompt = current_conv.system_prompt
        elif user.default_system_prompt:
            system_prompt = user.default_system_prompt
```

### System Prompt Priority Chain

| Priority | Source | When Used |
|----------|--------|-----------|
| 1 | Client-provided `system_prompt` | Frontend sends explicit prompt in WebSocket message |
| 2 | `user.default_system_prompt` | User has configured a default in their profile |
| 3 | `DEFAULT_SYSTEM_PROMPT` | Global fallback ("You are Arachne...") |

## Additional Issue Discovered: Caching Incompatibility

During the investigation, we also found that the system prompt caching feature (using Gemini's CachedContent API for 75% cost reduction) is **incompatible with tool usage**.

### Error

```
CachedContent can not be used with GenerateContent request setting 
system_instruction, tools or tool_config.

Proposed fix: move those values to CachedContent from GenerateContent request.
```

### Cause

Gemini's CachedContent API requires that if you use a cached content reference, **all of the following must be in the cache**:
- System instruction
- Tools
- Tool config

You cannot mix cached system prompts with dynamically registered tools.

### Resolution

Disabled system prompt caching by default in `config.py`:

```python
# NOTE: Currently disabled because Gemini's CachedContent cannot be used
# with tools in the same request. To enable, tools must also be cached.
ENABLE_SYSTEM_PROMPT_CACHING: bool = False
```

### Future Enhancement (if caching is needed)

To enable caching with tools, you would need to:
1. Cache the system prompt AND tool definitions together
2. Serialize all tool schemas into the cached content at cache creation time
3. Skip `register_tools(agent)` in `_create_agent()` when using a cache
4. Ensure the cached tool definitions match the current tool implementations

## Files Modified

1. `backend/app/api/routes/v1/agent.py` - Fixed system prompt fallback chain
2. `backend/app/core/config.py` - Disabled caching by default

## Testing

All 75 agent tests pass after the fix. The system prompt is now correctly injected for all conversations, and the LLM properly identifies as "Arachne" when asked.

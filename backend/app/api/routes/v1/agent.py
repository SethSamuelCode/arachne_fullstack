"""AI Agent WebSocket routes with streaming support (PydanticAI)."""

import base64
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from pydantic_ai import (
    Agent,
    BinaryContent,
    FinalResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
    ThinkingPartDelta,
    ToolCallPartDelta,
)
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from app.agents.assistant import Deps, get_agent
from app.agents.context_optimizer import OptimizedContext, optimize_context_window
from app.agents.prompts import DEFAULT_SYSTEM_PROMPT
from app.agents.providers.base import ModelProvider
from app.agents.providers.registry import DEFAULT_MODEL_ID, get_provider
from app.agents.tools import get_tool_definitions
from app.api.deps import get_conversation_service, get_current_user_ws
from app.clients.redis import RedisClient
from app.core.config import settings
from app.core.utils import serialize_tool_result_for_db
from app.db.models.user import User
from app.db.session import get_db_context
from app.schemas.attachment import AttachmentInMessage, validate_attachments_total_size
from app.schemas.conversation import (
    ConversationCreate,
    MessageCreate,
    ToolCallComplete,
    ToolCallCreate,
)
from app.services.pinned_content import PinnedContentService
from app.services.s3 import get_s3_service

logger = logging.getLogger(__name__)

router = APIRouter()


def serialize_content(content: Any) -> Any:
    """Serialize content that may contain BinaryContent for JSON transport.

    Handles strings, lists with BinaryContent/strings, and nested structures.
    Used for both tool results and user prompts with images.

    Args:
        content: Content that may contain BinaryContent objects

    Returns:
        JSON-serializable version of the content
    """
    if content is None:
        return None

    if isinstance(content, BinaryContent):
        # Single BinaryContent object
        return {
            "type": "image",
            "media_type": content.media_type,
            "data": base64.b64encode(content.data).decode("utf-8"),
        }

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        return [serialize_content(item) for item in content]

    if isinstance(content, dict):
        return {k: serialize_content(v) for k, v in content.items()}

    # For other types, convert to string
    return str(content)


def serialize_tool_content(content: Any) -> list[dict[str, Any]]:
    """Serialize tool result content, handling BinaryContent for images.

    Args:
        content: The content from ToolReturn, can be list with strings and BinaryContent

    Returns:
        List of serialized content parts with type indicators
    """
    if content is None:
        return []

    if not isinstance(content, list):
        return [{"type": "text", "text": str(content)}]

    parts: list[dict[str, Any]] = []
    for item in content:
        if isinstance(item, BinaryContent):
            # Encode binary data as base64 for JSON transport
            parts.append(
                {
                    "type": "image",
                    "media_type": item.media_type,
                    "data": base64.b64encode(item.data).decode("utf-8"),
                }
            )
        elif isinstance(item, str):
            parts.append({"type": "text", "text": item})
        else:
            parts.append({"type": "text", "text": str(item)})

    return parts


class AgentConnectionManager:
    """WebSocket connection manager for AI agent."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and store a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Agent WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(
            f"Agent WebSocket disconnected. Total connections: {len(self.active_connections)}"
        )

    async def send_event(self, websocket: WebSocket, event_type: str, data: Any) -> bool:
        """Send a JSON event to a specific WebSocket client.

        Returns True if sent successfully, False if connection is closed.
        """
        try:
            await websocket.send_json({"type": event_type, "data": data})
            return True
        except (WebSocketDisconnect, RuntimeError):
            # Connection already closed
            return False


manager = AgentConnectionManager()


async def enrich_history_with_tool_calls(
    history: list[dict[str, str]],
    conversation_id: UUID,
) -> list[dict[str, Any]]:
    """Enrich conversation history with tool call context for LLM learning.

    Inserts tool execution records (name, args, result, status) after each
    assistant message so the LLM can learn from past tool usage and errors.

    Args:
        history: Base conversation history with user/assistant messages
        conversation_id: UUID of the conversation

    Returns:
        Enriched history with tool call entries inserted
    """
    enriched_history: list[dict[str, Any]] = []

    try:
        async with get_db_context() as db:
            conv_service = get_conversation_service(db)

            # Get all messages with their IDs and tool calls
            messages, _ = await conv_service.list_messages(
                conversation_id, limit=10000, include_tool_calls=True
            )
            message_id_map = {msg.content: msg.id for msg in messages if msg.content}

            for msg in history:
                # Add the original message
                enriched_history.append(msg)

                # If this is an assistant message, check for tool calls
                if msg["role"] == "assistant":
                    # Try to find message ID by matching content
                    message_id = message_id_map.get(msg["content"])

                    if message_id:
                        # Get tool calls for this message
                        tool_calls = await conv_service.list_tool_calls(message_id)

                        # Add tool call records to history with content field for optimizer
                        for tc in tool_calls:
                            tool_content = (
                                f"Tool: {tc.tool_name}\n"
                                f"Status: {tc.status}\n"
                                f"Args: {tc.args}\n"
                                f"Result: {tc.result or ''}"
                            )
                            enriched_history.append(
                                {
                                    "role": "tool",
                                    "content": tool_content,
                                    "tool_name": tc.tool_name,
                                    "args": tc.args,
                                    "result": tc.result or "",
                                    "status": tc.status,
                                    "duration_ms": tc.duration_ms,
                                }
                            )

    except Exception as e:
        logger.warning(f"Failed to enrich history with tool calls: {e}")
        # Return original history if enrichment fails
        return history

    return enriched_history


def build_message_history(history: list[dict[str, str]]) -> list[ModelRequest | ModelResponse]:
    """Convert conversation history to PydanticAI message format."""
    model_history: list[ModelRequest | ModelResponse] = []

    for msg in history:
        if msg["role"] == "user":
            model_history.append(ModelRequest(parts=[UserPromptPart(content=msg["content"])]))
        elif msg["role"] == "assistant":
            model_history.append(ModelResponse(parts=[TextPart(content=msg["content"])]))
        elif msg["role"] == "system":
            model_history.append(ModelRequest(parts=[SystemPromptPart(content=msg["content"])]))
        elif msg["role"] == "tool":
            # Include tool execution context for LLM learning (content already formatted)
            model_history.append(ModelResponse(parts=[TextPart(content=msg["content"])]))

    return model_history


def _check_attachment_support(
    provider: ModelProvider,
    attachments: list[AttachmentInMessage],
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


async def build_multimodal_input(
    user_message: str,
    attachments: list[AttachmentInMessage],
    user_id: str | None,
) -> str | list[str | BinaryContent]:
    """Build multimodal input from user message and attachments.

    Downloads images from S3 and creates BinaryContent objects.

    Args:
        user_message: The text message from the user.
        attachments: List of validated attachments with S3 keys.
        user_id: User ID for S3 path prefix.

    Returns:
        Either a plain string (no attachments) or a list of text + BinaryContent.
    """
    if not attachments:
        return user_message

    s3 = get_s3_service()
    user_prefix = f"users/{user_id}/" if user_id else ""

    # Start with the text message
    content: list[str | BinaryContent] = [user_message]

    # Download and add each image
    for attachment in attachments:
        full_key = f"{user_prefix}{attachment.s3_key}"
        try:
            image_data = s3.download_obj(full_key)
            content.append(BinaryContent(data=image_data, media_type=attachment.mime_type))
            logger.debug(f"Added image attachment: {attachment.s3_key} ({len(image_data)} bytes)")
        except Exception as e:
            logger.error(f"Failed to download attachment {attachment.s3_key}: {e}")
            raise ValueError(f"Failed to load image '{attachment.s3_key}': {e}") from e

    return content


async def _persist_assistant_result(
    *,
    conversation_id: str | None,
    output: str,
    assistant_message_id: UUID | None,
    thinking_content_buffer: list[str],
    model_name: str | None,
    user_message: str,
    websocket: WebSocket,
) -> None:
    """Persist the assistant response, tool-call message, title generation, etc.

    Shared by both the streaming and non-streaming paths so DB logic is not
    duplicated.
    """
    if not conversation_id:
        return

    final_thinking_content = "".join(thinking_content_buffer) if thinking_content_buffer else None

    try:
        async with get_db_context() as db:
            conv_service = get_conversation_service(db)

            if assistant_message_id is not None:
                # Update existing message (created during tool calls)
                from app.repositories.conversation import update_message_content

                await update_message_content(
                    db,
                    assistant_message_id,
                    output,
                    thinking_content=final_thinking_content,
                )
            else:
                # No tools were used, create new message
                await conv_service.add_message(
                    UUID(conversation_id),
                    MessageCreate(
                        role="assistant",
                        content=output,
                        thinking_content=final_thinking_content,
                        model_name=model_name,
                    ),
                )
    except Exception as e:
        logger.warning(f"Failed to persist assistant response: {e}")

    # Generate title for new conversations (non-blocking)
    try:
        async with get_db_context() as db:
            conv_service = get_conversation_service(db)
            title = await conv_service.generate_and_set_title(
                UUID(conversation_id),
                user_message,
                output,
            )
            if title:
                await manager.send_event(
                    websocket,
                    "conversation_updated",
                    {
                        "conversation_id": conversation_id,
                        "title": title,
                    },
                )
    except Exception as e:
        logger.warning(f"Failed to generate conversation title: {e}")


async def _run_agent_non_streaming(
    *,
    assistant: Any,
    agent_input: Any,
    deps: Deps,
    model_history: list[ModelRequest | ModelResponse],
    websocket: WebSocket,
    conversation_id: str | None,
    user_message: str,
    conversation_history: list[dict[str, Any]],
) -> None:
    """Execute the agent without streaming and emit WebSocket events after completion.

    Used for providers that do not support streaming (e.g. Vertex AI Model
    Garden models) to avoid 429 RESOURCE_EXHAUSTED errors from the streaming
    endpoint.

    The full result is obtained via ``agent.run()``, then tool calls, thinking,
    and text are sent to the client as discrete WebSocket events — the same
    event types the frontend already handles.
    """
    from pydantic_ai import UsageLimits

    assistant_message_id: UUID | None = None
    tool_call_mapping: dict[str, UUID] = {}
    thinking_content_buffer: list[str] = []

    async with get_db_context() as agent_db:
        deps.db = agent_db

        result = await assistant.agent.run(
            agent_input,
            deps=deps,
            message_history=model_history,
            usage_limits=UsageLimits(
                request_limit=settings.AGENT_MAX_REQUESTS,
                tool_calls_limit=settings.AGENT_MAX_TOOL_CALLS,
            ),
        )

    # Walk result messages and emit events the frontend understands
    await manager.send_event(websocket, "model_request_start", {})

    for message in result.all_messages():
        if isinstance(message, ModelResponse):
            for part in message.parts:
                if isinstance(part, ThinkingPart) and part.content:
                    thinking_content_buffer.append(part.content)
                    if settings.AGENT_STREAM_THINKING:
                        await manager.send_event(
                            websocket,
                            "thinking_delta",
                            {"index": 0, "content": part.content},
                        )
                elif isinstance(part, ToolCallPart):
                    args = part.args if isinstance(part.args, dict) else {}
                    await manager.send_event(
                        websocket,
                        "tool_call",
                        {
                            "tool_name": part.tool_name,
                            "args": args,
                            "tool_call_id": part.tool_call_id,
                        },
                    )
                    # Persist tool call start
                    if conversation_id:
                        try:
                            if assistant_message_id is None:
                                async with get_db_context() as db:
                                    conv_service = get_conversation_service(db)
                                    assistant_msg = await conv_service.add_message(
                                        UUID(conversation_id),
                                        MessageCreate(
                                            role="assistant",
                                            content="",
                                            model_name=assistant.model_name
                                            if hasattr(assistant, "model_name")
                                            else None,
                                        ),
                                    )
                                    assistant_message_id = assistant_msg.id

                            async with get_db_context() as db:
                                conv_service = get_conversation_service(db)
                                tool_call = await conv_service.start_tool_call(
                                    assistant_message_id,
                                    ToolCallCreate(
                                        tool_call_id=part.tool_call_id,
                                        tool_name=part.tool_name,
                                        args=args,
                                        started_at=datetime.now(UTC),
                                    ),
                                )
                                tool_call_mapping[part.tool_call_id] = tool_call.id
                        except Exception as e:
                            logger.warning(f"Failed to persist tool call start: {e}")

        elif isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, ToolReturnPart):
                    content_parts = serialize_tool_content(part.content)
                    await manager.send_event(
                        websocket,
                        "tool_result",
                        {
                            "tool_call_id": part.tool_call_id,
                            "content": content_parts,
                        },
                    )
                    # Persist tool result
                    if conversation_id and part.tool_call_id in tool_call_mapping:
                        try:
                            db_tool_call_id = tool_call_mapping[part.tool_call_id]
                            result_text = serialize_tool_result_for_db(part.content)
                            is_error = (
                                isinstance(part.content, dict) and part.content.get("error") is True
                            )
                            async with get_db_context() as db:
                                conv_service = get_conversation_service(db)
                                await conv_service.complete_tool_call(
                                    db_tool_call_id,
                                    ToolCallComplete(
                                        result=result_text,
                                        completed_at=datetime.now(UTC),
                                        success=not is_error,
                                    ),
                                )
                        except Exception as e:
                            logger.warning(f"Failed to persist tool result: {e}")

    # Send the full output text as a single delta
    await manager.send_event(
        websocket,
        "text_delta",
        {"index": 0, "content": result.output},
    )

    # Signal final result
    await manager.send_event(
        websocket,
        "final_result",
        {"output": result.output},
    )

    # Update conversation history
    conversation_history.append({"role": "user", "content": user_message})
    conversation_history.append({"role": "assistant", "content": result.output})

    # Persist assistant response and generate title
    await _persist_assistant_result(
        conversation_id=conversation_id,
        output=result.output,
        assistant_message_id=assistant_message_id,
        thinking_content_buffer=thinking_content_buffer,
        model_name=assistant.model_name if hasattr(assistant, "model_name") else None,
        user_message=user_message,
        websocket=websocket,
    )

    # Handle interrupted tool calls (agent didn't complete but we created a message)
    if not result.output and assistant_message_id is not None:
        try:
            async with get_db_context() as db:
                from app.repositories.conversation import update_message_content

                await update_message_content(
                    db,
                    assistant_message_id,
                    "(Tool execution interrupted)",
                )
        except Exception as e:
            logger.warning(f"Failed to update interrupted message: {e}")

    await manager.send_event(
        websocket,
        "complete",
        {"conversation_id": conversation_id},
    )


@router.websocket("/ws/agent")
async def agent_websocket(
    websocket: WebSocket,
    user: User = Depends(get_current_user_ws),
) -> None:
    """WebSocket endpoint for AI agent with full event streaming.

    Uses PydanticAI iter() to stream all agent events including:
    - user_prompt: When user input is received
    - model_request_start: When model request begins
    - text_delta: Streaming text from the model
    - tool_call_delta: Streaming tool call arguments
    - tool_call: When a tool is called (with full args)
    - tool_result: When a tool returns a result
    - final_result: When the final result is ready
    - complete: When processing is complete
    - error: When an error occurs

    Expected input message format:
    {
        "message": "user message here",
        "history": [{"role": "user|assistant|system", "content": "..."}],
        "conversation_id": "optional-uuid-to-continue-existing-conversation",
        "attachments": [
            {
                "s3_key": "path/to/image.png",
                "mime_type": "image/png",
                "size_bytes": 12345,
                "filename": "optional-original-filename.png"
            }
        ]
    }

    Supported image formats: PNG, JPEG, WebP, HEIC, HEIF
    Maximum total attachment size: 20MB

    Authentication: Requires a valid JWT token passed as a query parameter or header.

    Persistence: Set 'conversation_id' to continue an existing conversation.
    If provided, the last 50 messages are automatically retrieved from the
    database to restore context.
    If not provided, a new conversation is created. The conversation_id is
    returned in the 'conversation_created' event.
    """

    await manager.connect(websocket)

    # Conversation state per connection
    conversation_history: list[dict[str, str]] = []
    deps = Deps(user_id=str(user.id), user_name=user.email)
    current_conversation_id: str | None = None

    try:
        while True:
            # Receive user message
            data = await websocket.receive_json()
            user_message = data.get("message", "")
            # Optionally accept history from client (or use server-side tracking)
            if "history" in data:
                conversation_history = data["history"]

            if not user_message:
                await manager.send_event(websocket, "error", {"message": "Empty message"})
                continue

            # Parse and validate attachments
            attachments: list[AttachmentInMessage] = []
            raw_attachments = data.get("attachments", [])
            if raw_attachments:
                try:
                    attachments = [AttachmentInMessage(**a) for a in raw_attachments]
                    validate_attachments_total_size(attachments)
                    logger.info(
                        f"Message includes {len(attachments)} attachment(s), "
                        f"total size: {sum(a.size_bytes for a in attachments)} bytes"
                    )
                except ValidationError as e:
                    await manager.send_event(
                        websocket,
                        "error",
                        {"message": f"Invalid attachment: {e.errors()[0]['msg']}"},
                    )
                    continue
                except ValueError as e:
                    await manager.send_event(websocket, "error", {"message": str(e)})
                    continue

            # Handle conversation persistence
            try:
                async with get_db_context() as db:
                    conv_service = get_conversation_service(db)

                    # Get or create conversation
                    requested_conv_id = data.get("conversation_id")
                    if requested_conv_id:
                        # Check if switching to a different conversation
                        is_conversation_switch = (
                            current_conversation_id is not None
                            and current_conversation_id != requested_conv_id
                        )

                        current_conversation_id = requested_conv_id
                        # Verify conversation exists
                        await conv_service.get_conversation(UUID(requested_conv_id))

                        # Populate history from DB if missing OR if switching conversations
                        if not conversation_history or is_conversation_switch:
                            # Clear any existing history from previous conversation
                            conversation_history.clear()

                            # Restoring context on reconnection:
                            # 1. Get total message count to determine offset
                            _, total_count = await conv_service.list_messages(
                                UUID(requested_conv_id), limit=1
                            )

                            # 2. Fetch only the last 50 messages (context window)
                            # Expanding context window/semantic memory
                            fetch_limit = 1000
                            skip = max(0, total_count - fetch_limit)
                            restored_msgs, _ = await conv_service.list_messages(
                                UUID(requested_conv_id),
                                skip=skip,
                                limit=fetch_limit,
                                include_tool_calls=True,
                            )

                            # 3. Populate history
                            for msg in restored_msgs:
                                conversation_history.append(
                                    {"role": msg.role, "content": msg.content or ""}
                                )

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
                            title=None,
                            system_prompt=conv_system_prompt,
                        )
                        conversation = await conv_service.create_conversation(conv_data)
                        current_conversation_id = str(conversation.id)
                        await manager.send_event(
                            websocket,
                            "conversation_created",
                            {"conversation_id": current_conversation_id},
                        )

                    # Save user message
                    await conv_service.add_message(
                        UUID(current_conversation_id),
                        MessageCreate(role="user", content=user_message),
                    )
            except Exception as e:
                logger.warning(f"Failed to persist conversation: {e}")
                # Continue without persistence

            await manager.send_event(websocket, "user_prompt", {"content": user_message})

            # Retrieve the system prompt for this conversation
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
            logger.info(
                f"Using system prompt for conversation {current_conversation_id}: "
                f"{system_prompt[:50]}..."
            )

            try:
                # Resolve provider once — used by both optimize_context_window and get_agent
                provider = get_provider(user.default_model or DEFAULT_MODEL_ID)

                # Reject attachments if the model does not support multimodal input
                attachment_error = _check_attachment_support(provider, attachments)
                if attachment_error:
                    await manager.send_event(websocket, "error", {"message": attachment_error})
                    continue

                # Enrich history with tool call context for LLM learning
                if current_conversation_id:
                    conversation_history = await enrich_history_with_tool_calls(
                        conversation_history,
                        UUID(current_conversation_id),
                    )

                # Get Redis client for system prompt caching
                redis_client: RedisClient | None = getattr(websocket.state, "redis", None)

                # Get tool definitions for caching (system prompt + tools cached together)
                tool_definitions = get_tool_definitions()

                # Check for pinned content in this conversation
                pinned_content_hash: str | None = None
                pinned_content_tokens: int = 0
                if current_conversation_id and redis_client:
                    async with get_db_context() as db:
                        pinned_service = PinnedContentService(db, redis_client)
                        pinned_content_hash = await pinned_service.get_pinned_content_hash(
                            UUID(current_conversation_id)
                        )
                        pinned_content_tokens = await pinned_service.get_pinned_tokens(
                            UUID(current_conversation_id)
                        )
                        if pinned_content_hash:
                            logger.info(
                                f"Found pinned content for conversation {current_conversation_id}: "
                                f"hash={pinned_content_hash}, tokens={pinned_content_tokens}"
                            )

                # Optimize context window with tiered memory management
                # Uses 85% of model's context limit for better responsiveness
                optimized: OptimizedContext = await optimize_context_window(
                    history=conversation_history,
                    provider=provider,
                    system_prompt=system_prompt,
                    tool_definitions=tool_definitions,
                    redis_client=redis_client,
                    pinned_content_hash=pinned_content_hash,
                    pinned_content_tokens=pinned_content_tokens,
                )
                model_history = optimized["history"]
                logger.debug(
                    f"Context optimized: {len(conversation_history)} -> {len(model_history)} messages"
                )

                # Create agent with system prompt or cached prompt
                # skip_tool_registration=True when tools are already in the cached content
                assistant = get_agent(
                    system_prompt=optimized["system_prompt"],
                    provider=provider,
                    cached_prompt_name=optimized["cached_prompt_name"],
                    skip_tool_registration=optimized["skip_tool_registration"],
                )

                # Build multimodal input if attachments are present
                try:
                    agent_input = await build_multimodal_input(
                        user_message, attachments, str(user.id)
                    )
                except ValueError as e:
                    await manager.send_event(websocket, "error", {"message": str(e)})
                    continue

                # Branch: non-streaming path for providers that don't support it
                if not provider.supports_streaming:
                    await _run_agent_non_streaming(
                        assistant=assistant,
                        agent_input=agent_input,
                        deps=deps,
                        model_history=model_history,
                        websocket=websocket,
                        conversation_id=current_conversation_id,
                        user_message=user_message,
                        conversation_history=conversation_history,
                    )
                    continue

                # Track assistant message and tool call mapping for persistence
                assistant_message_id: UUID | None = None
                tool_call_mapping: dict[str, UUID] = {}  # Maps PydanticAI tool_call_id to DB UUID
                thinking_content_buffer: list[str] = []  # Accumulate thinking content

                # Use iter() on the underlying PydanticAI agent to stream all events
                # Wrap in db context so plan tools can access the database
                async with get_db_context() as agent_db:
                    # Update deps with the db session for this agent run
                    deps.db = agent_db

                    # Import UsageLimits for controlling tool call chains
                    from pydantic_ai import UsageLimits

                    async with assistant.agent.iter(
                        agent_input,
                        deps=deps,
                        message_history=model_history,
                        usage_limits=UsageLimits(
                            request_limit=settings.AGENT_MAX_REQUESTS,
                            tool_calls_limit=settings.AGENT_MAX_TOOL_CALLS,
                        ),
                    ) as agent_run:
                        async for node in agent_run:
                            if Agent.is_user_prompt_node(node):
                                # Serialize user_prompt which may contain BinaryContent from images
                                await manager.send_event(
                                    websocket,
                                    "user_prompt_processed",
                                    {"prompt": serialize_content(node.user_prompt)},
                                )

                            elif Agent.is_model_request_node(node):
                                await manager.send_event(websocket, "model_request_start", {})

                                async with node.stream(agent_run.ctx) as request_stream:
                                    async for event in request_stream:
                                        if isinstance(event, PartStartEvent):
                                            await manager.send_event(
                                                websocket,
                                                "part_start",
                                                {
                                                    "index": event.index,
                                                    "part_type": type(event.part).__name__,
                                                },
                                            )
                                            # Send initial content from TextPart if present
                                            if (
                                                isinstance(event.part, TextPart)
                                                and event.part.content
                                            ):
                                                await manager.send_event(
                                                    websocket,
                                                    "text_delta",
                                                    {
                                                        "index": event.index,
                                                        "content": event.part.content,
                                                    },
                                                )
                                            # Handle ThinkingPart - stream to client and accumulate
                                            elif (
                                                isinstance(event.part, ThinkingPart)
                                                and event.part.content
                                            ):
                                                thinking_content_buffer.append(event.part.content)
                                                if settings.AGENT_STREAM_THINKING:
                                                    await manager.send_event(
                                                        websocket,
                                                        "thinking_delta",
                                                        {
                                                            "index": event.index,
                                                            "content": event.part.content,
                                                        },
                                                    )

                                        elif isinstance(event, PartDeltaEvent):
                                            if isinstance(event.delta, TextPartDelta):
                                                await manager.send_event(
                                                    websocket,
                                                    "text_delta",
                                                    {
                                                        "index": event.index,
                                                        "content": event.delta.content_delta,
                                                    },
                                                )
                                            # Handle ThinkingPartDelta - stream to client and accumulate
                                            elif (
                                                isinstance(event.delta, ThinkingPartDelta)
                                                and event.delta.content_delta
                                            ):
                                                thinking_content_buffer.append(
                                                    event.delta.content_delta
                                                )
                                                if settings.AGENT_STREAM_THINKING:
                                                    await manager.send_event(
                                                        websocket,
                                                        "thinking_delta",
                                                        {
                                                            "index": event.index,
                                                            "content": event.delta.content_delta,
                                                        },
                                                    )
                                            elif isinstance(event.delta, ToolCallPartDelta):
                                                await manager.send_event(
                                                    websocket,
                                                    "tool_call_delta",
                                                    {
                                                        "index": event.index,
                                                        "args_delta": event.delta.args_delta,
                                                    },
                                                )

                                        elif isinstance(event, FinalResultEvent):
                                            await manager.send_event(
                                                websocket,
                                                "final_result_start",
                                                {"tool_name": event.tool_name},
                                            )

                            elif Agent.is_call_tools_node(node):
                                await manager.send_event(websocket, "call_tools_start", {})

                                async with node.stream(agent_run.ctx) as handle_stream:
                                    async for event in handle_stream:
                                        if isinstance(event, FunctionToolCallEvent):
                                            await manager.send_event(
                                                websocket,
                                                "tool_call",
                                                {
                                                    "tool_name": event.part.tool_name,
                                                    "args": event.part.args,
                                                    "tool_call_id": event.part.tool_call_id,
                                                },
                                            )

                                            # Persist tool call to database
                                            if current_conversation_id:
                                                try:
                                                    # Create assistant message if not exists
                                                    if assistant_message_id is None:
                                                        async with get_db_context() as db:
                                                            conv_service = get_conversation_service(
                                                                db
                                                            )
                                                            assistant_msg = await conv_service.add_message(
                                                                UUID(current_conversation_id),
                                                                MessageCreate(
                                                                    role="assistant",
                                                                    content="",  # Will be updated after agent completes
                                                                    model_name=assistant.model_name
                                                                    if hasattr(
                                                                        assistant, "model_name"
                                                                    )
                                                                    else None,
                                                                ),
                                                            )
                                                            assistant_message_id = assistant_msg.id

                                                    # Start tool call
                                                    async with get_db_context() as db:
                                                        conv_service = get_conversation_service(db)
                                                        tool_call = await conv_service.start_tool_call(
                                                            assistant_message_id,
                                                            ToolCallCreate(
                                                                tool_call_id=event.part.tool_call_id,
                                                                tool_name=event.part.tool_name,
                                                                args=event.part.args
                                                                if isinstance(event.part.args, dict)
                                                                else {},
                                                                started_at=datetime.now(UTC),
                                                            ),
                                                        )
                                                        # Map PydanticAI ID to DB UUID
                                                        tool_call_mapping[
                                                            event.part.tool_call_id
                                                        ] = tool_call.id
                                                except Exception as e:
                                                    logger.warning(
                                                        f"Failed to persist tool call start: {e}"
                                                    )

                                        elif isinstance(event, FunctionToolResultEvent):
                                            # Serialize content, handling BinaryContent for images
                                            content_parts = serialize_tool_content(
                                                event.result.content
                                            )
                                            await manager.send_event(
                                                websocket,
                                                "tool_result",
                                                {
                                                    "tool_call_id": event.tool_call_id,
                                                    "content": content_parts,
                                                },
                                            )

                                            # Persist tool result to database
                                            if (
                                                current_conversation_id
                                                and event.tool_call_id in tool_call_mapping
                                            ):
                                                try:
                                                    # Get DB UUID for this tool call
                                                    db_tool_call_id = tool_call_mapping[
                                                        event.tool_call_id
                                                    ]

                                                    # Serialize result for database (text only, truncated)
                                                    result_text = serialize_tool_result_for_db(
                                                        event.result.content
                                                    )

                                                    # Detect if this is an error result
                                                    is_error = (
                                                        isinstance(event.result.content, dict)
                                                        and event.result.content.get("error")
                                                        is True
                                                    )

                                                    # Complete tool call
                                                    async with get_db_context() as db:
                                                        conv_service = get_conversation_service(db)
                                                        await conv_service.complete_tool_call(
                                                            db_tool_call_id,
                                                            ToolCallComplete(
                                                                result=result_text,
                                                                completed_at=datetime.now(UTC),
                                                                success=not is_error,
                                                            ),
                                                        )
                                                except Exception as e:
                                                    logger.warning(
                                                        f"Failed to persist tool result: {e}"
                                                    )

                            elif Agent.is_end_node(node) and agent_run.result is not None:
                                await manager.send_event(
                                    websocket,
                                    "final_result",
                                    {"output": agent_run.result.output},
                                )

                # Update conversation history
                conversation_history.append({"role": "user", "content": user_message})
                if agent_run.result:
                    conversation_history.append(
                        {"role": "assistant", "content": agent_run.result.output}
                    )

                # Save or update assistant response to database
                if current_conversation_id and agent_run.result:
                    await _persist_assistant_result(
                        conversation_id=current_conversation_id,
                        output=agent_run.result.output,
                        assistant_message_id=assistant_message_id,
                        thinking_content_buffer=thinking_content_buffer,
                        model_name=assistant.model_name
                        if hasattr(assistant, "model_name")
                        else None,
                        user_message=user_message,
                        websocket=websocket,
                    )

                # Handle case where assistant message was created but agent didn't complete
                elif current_conversation_id and assistant_message_id is not None:
                    try:
                        async with get_db_context() as db:
                            from app.repositories.conversation import update_message_content

                            await update_message_content(
                                db,
                                assistant_message_id,
                                "(Tool execution interrupted)",
                            )
                    except Exception as e:
                        logger.warning(f"Failed to update interrupted message: {e}")

                await manager.send_event(
                    websocket,
                    "complete",
                    {
                        "conversation_id": current_conversation_id,
                    },
                )

            except WebSocketDisconnect:
                # Client disconnected during processing - this is normal
                logger.info("Client disconnected during agent processing")
                break
            except Exception as e:
                logger.exception(f"Error processing agent request: {e}")
                # Try to send error, but don't fail if connection is closed
                await manager.send_event(websocket, "error", {"message": str(e)})

    except WebSocketDisconnect:
        pass  # Normal disconnect
    finally:
        manager.disconnect(websocket)

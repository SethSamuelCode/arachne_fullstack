"""AI Agent WebSocket routes with streaming support (PydanticAI)."""

import base64
import logging
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
    ToolCallPartDelta,
)
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)

from app.agents.assistant import Deps, get_agent
from app.agents.context_optimizer import optimize_context_window
from app.api.deps import get_conversation_service, get_current_user_ws
from app.db.models.user import User
from app.db.session import get_db_context
from app.schemas.attachment import AttachmentInMessage, validate_attachments_total_size
from app.schemas.conversation import (
    ConversationCreate,
    MessageCreate,
)
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
            parts.append({
                "type": "image",
                "media_type": item.media_type,
                "data": base64.b64encode(item.data).decode("utf-8"),
            })
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

    return model_history


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
            content.append(
                BinaryContent(data=image_data, media_type=attachment.mime_type)
            )
            logger.debug(f"Added image attachment: {attachment.s3_key} ({len(image_data)} bytes)")
        except Exception as e:
            logger.error(f"Failed to download attachment {attachment.s3_key}: {e}")
            raise ValueError(f"Failed to load image '{attachment.s3_key}': {e}")

    return content


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
                                UUID(requested_conv_id), skip=skip, limit=fetch_limit
                            )

                            # 3. Populate history
                            for msg in restored_msgs:
                                conversation_history.append({
                                    "role": msg.role,
                                    "content": msg.content or ""
                                })

                    elif not current_conversation_id:
                        # Create new conversation
                        conv_data = ConversationCreate(
                            user_id=user.id,
                            title=user_message[:50] if len(user_message) > 50 else user_message,
                            system_prompt=data.get("system_prompt"),
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

            # Retrieve the specific system prompt for this conversation
            system_prompt = None
            if current_conversation_id:
                async with get_db_context() as db:
                    conv_service = get_conversation_service(db)
                    current_conv = await conv_service.get_conversation(UUID(current_conversation_id))
                    if current_conv:
                        system_prompt = current_conv.system_prompt
                        logger.info(f"Using system prompt for conversation {current_conversation_id}: {system_prompt}")

            try:
                # Use user's default model preference or backend default
                model_name = user.default_model
                assistant = get_agent(system_prompt=system_prompt, model_name=model_name)

                # Optimize context window with tiered memory management
                # Uses 85% of model's context limit for better responsiveness
                model_history = await optimize_context_window(
                    history=conversation_history,
                    model_name=model_name or "gemini-2.5-flash",
                    system_prompt=system_prompt,
                )
                logger.debug(
                    f"Context optimized: {len(conversation_history)} -> {len(model_history)} messages"
                )

                # Build multimodal input if attachments are present
                try:
                    agent_input = await build_multimodal_input(
                        user_message, attachments, str(user.id)
                    )
                except ValueError as e:
                    await manager.send_event(websocket, "error", {"message": str(e)})
                    continue

                # Use iter() on the underlying PydanticAI agent to stream all events
                async with assistant.agent.iter(
                    agent_input,
                    deps=deps,
                    message_history=model_history,
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
                                        if isinstance(event.part, TextPart) and event.part.content:
                                            await manager.send_event(
                                                websocket,
                                                "text_delta",
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

                # Save assistant response to database
                if current_conversation_id and agent_run.result:
                    try:
                        async with get_db_context() as db:
                            conv_service = get_conversation_service(db)
                            await conv_service.add_message(
                                UUID(current_conversation_id),
                                MessageCreate(
                                    role="assistant",
                                    content=agent_run.result.output,
                                    model_name=assistant.model_name
                                    if hasattr(assistant, "model_name")
                                    else None,
                                ),
                            )
                    except Exception as e:
                        logger.warning(f"Failed to persist assistant response: {e}")

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

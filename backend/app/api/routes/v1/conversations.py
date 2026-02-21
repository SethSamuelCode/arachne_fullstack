"""Conversation API routes for AI chat persistence.

Provides CRUD operations for conversations and messages, plus context pinning.

The endpoints are:
- GET /conversations - List user's conversations
- POST /conversations - Create a new conversation
- GET /conversations/{id} - Get a conversation with messages
- PATCH /conversations/{id} - Update conversation title/archived status
- DELETE /conversations/{id} - Delete a conversation
- POST /conversations/{id}/messages - Add a message to conversation
- GET /conversations/{id}/messages - List messages in conversation
- GET /conversations/{id}/pin - Pin content to conversation cache (SSE)
- POST /conversations/{id}/check-staleness - Check if pinned content is stale
- GET /conversations/{id}/repin - Repin content with updates (SSE)
- GET /conversations/{id}/pinned - Get pinned content info
"""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.agents.prompts import DEFAULT_SYSTEM_PROMPT
from app.agents.tools import get_tool_definitions
from app.api.deps import ConversationSvc, CurrentUser, DBSession, Redis
from app.schemas.conversation import (
    ConversationCreate,
    ConversationList,
    ConversationRead,
    ConversationReadWithMessages,
    ConversationUpdate,
    MessageCreate,
    MessageList,
    MessageRead,
)
from app.services.conversation import ConversationService
from app.services.pinned_content import PinnedContentService
from app.services.s3 import get_s3_service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("", response_model=ConversationList)
async def list_conversations(
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
    skip: int = Query(0, ge=0, description="Number of conversations to skip"),
    limit: int = Query(50, ge=1, le=100, description="Maximum conversations to return"),
    include_archived: bool = Query(False, description="Include archived conversations"),
):
    """List conversations for the current user.

    Returns conversations ordered by most recently updated.
    """
    items, total = await conversation_service.list_conversations(
        user_id=current_user.id,
        skip=skip,
        limit=limit,
        include_archived=include_archived,
    )
    return ConversationList(items=items, total=total)


@router.post("", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
    data: ConversationCreate | None = None,
):
    """Create a new conversation.

    The title is optional and can be set later.
    """
    if data is None:
        data = ConversationCreate()

    # Use user's default system prompt if none provided
    if data.system_prompt is None and current_user.default_system_prompt:
        data.system_prompt = current_user.default_system_prompt

    data.user_id = current_user.id
    return await conversation_service.create_conversation(data)


@router.get("/{conversation_id}", response_model=ConversationReadWithMessages)
async def get_conversation(
    conversation_id: UUID,
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
):
    """Get a conversation with all its messages.

    Raises 404 if the conversation does not exist.
    """
    return await conversation_service.get_conversation(conversation_id, include_messages=True)


@router.patch("/{conversation_id}", response_model=ConversationRead)
async def update_conversation(
    conversation_id: UUID,
    data: ConversationUpdate,
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
):
    """Update a conversation's title or archived status.

    Raises 404 if the conversation does not exist.
    """
    logger.info(f"Updating conversation {conversation_id} with data: {data}")
    return await conversation_service.update_conversation(conversation_id, data)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID,
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
):
    """Delete a conversation and all its messages.

    Raises 404 if the conversation does not exist.
    """
    await conversation_service.delete_conversation(conversation_id)


@router.post(
    "/{conversation_id}/archive",
    response_model=ConversationRead,
)
async def archive_conversation(
    conversation_id: UUID,
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
):
    """Archive a conversation.

    Archived conversations are hidden from the default list view.
    """
    return await conversation_service.archive_conversation(conversation_id)


@router.get("/{conversation_id}/messages", response_model=MessageList)
async def list_messages(
    conversation_id: UUID,
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    """List messages in a conversation.

    Returns messages ordered by creation time (oldest first).
    """
    items, total = await conversation_service.list_messages(
        conversation_id, skip=skip, limit=limit, include_tool_calls=True
    )
    return MessageList(items=items, total=total)


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_message(
    conversation_id: UUID,
    data: MessageCreate,
    conversation_service: ConversationSvc,
    current_user: CurrentUser,
):
    """Add a message to a conversation.

    Raises 404 if the conversation does not exist.
    """
    return await conversation_service.add_message(conversation_id, data)


# =============================================================================
# Pinned Content Schemas
# =============================================================================


class PinContentRequest(BaseModel):
    """Request to pin content to a conversation cache."""

    files: dict[str, str] | None = Field(
        default=None,
        description="Dict mapping file paths to text content (for direct content)",
    )
    s3_paths: list[str] | None = Field(
        default=None,
        description="List of S3 paths to fetch content from (user's storage)",
    )
    mime_types: dict[str, str] | None = Field(
        default=None,
        description="Optional dict mapping file paths to MIME types",
    )
    model_name: str = Field(
        default="gemini-2.5-flash",
        description="Gemini model name for budget calculation",
    )


class CheckStalenessRequest(BaseModel):
    """Request to check if pinned content is stale."""

    current_hashes: dict[str, str] = Field(
        ...,
        description="Dict mapping file paths to current SHA256 hashes",
    )


class StalenessResponse(BaseModel):
    """Response indicating staleness status."""

    is_stale: bool
    changed_files: list[str]
    added_files: list[str]
    removed_files: list[str]
    has_pinned_content: bool


class PinnedContentInfo(BaseModel):
    """Information about pinned content."""

    content_hash: str
    file_paths: list[str]
    file_hashes: dict[str, str]
    total_tokens: int
    pinned_at: str


# =============================================================================
# Pinned Content Endpoints
# =============================================================================


@router.get("/{conversation_id}/pin")
async def pin_content_sse(
    request: Request,
    conversation_id: UUID,
    db: DBSession,
    redis: Redis,
    current_user: CurrentUser,
    model_name: str = Query("gemini-2.5-flash", description="Model for budget calculation"),
) -> EventSourceResponse:
    """Pin content to conversation cache via SSE.

    Content is provided via query parameters. For large content, use POST body.
    Progress events are streamed as SSE with types: 'progress', 'warning', 'error', 'complete'.

    Note: For file content, use the POST /pin endpoint or provide s3_paths.
    """
    s3 = get_s3_service()
    user_id = str(current_user.id)

    # Get S3 paths from query params
    s3_paths_param = request.query_params.get("s3_paths", "")
    s3_paths = [p.strip() for p in s3_paths_param.split(",") if p.strip()]

    async def event_generator() -> AsyncGenerator[dict[str, Any], None]:
        try:
            if not s3_paths:
                yield {
                    "event": "error",
                    "data": json.dumps(
                        {
                            "code": "NO_FILES",
                            "message": "No files specified. Provide s3_paths query parameter.",
                        }
                    ),
                }
                return

            # Fetch files from S3
            files: dict[str, str | bytes] = {}
            mime_types: dict[str, str] = {}

            yield {
                "event": "progress",
                "data": json.dumps(
                    {
                        "phase": "fetching",
                        "current": 0,
                        "total": len(s3_paths),
                        "message": "Fetching files from storage...",
                    }
                ),
            }

            for i, path in enumerate(s3_paths):
                if await request.is_disconnected():
                    return

                try:
                    # Build full S3 key with user prefix
                    full_key = f"users/{user_id}/{path.lstrip('/')}"
                    content = s3.download_obj(full_key)

                    # Try to decode as text, otherwise keep as bytes
                    try:
                        files[path] = content.decode("utf-8")
                    except UnicodeDecodeError:
                        files[path] = content

                    yield {
                        "event": "progress",
                        "data": json.dumps(
                            {
                                "phase": "fetching",
                                "current": i + 1,
                                "total": len(s3_paths),
                                "current_file": path,
                            }
                        ),
                    }
                except Exception as e:
                    logger.warning(f"Failed to fetch {path}: {e}")
                    yield {
                        "event": "warning",
                        "data": json.dumps(
                            {
                                "type": "file_error",
                                "path": path,
                                "message": str(e),
                            }
                        ),
                    }

            if not files:
                yield {
                    "event": "error",
                    "data": json.dumps(
                        {
                            "code": "NO_FILES_LOADED",
                            "message": "Could not load any files from storage.",
                        }
                    ),
                }
                return

            # Get conversation's system prompt
            conv_service = ConversationService(db)
            conv = await conv_service.get_conversation(conversation_id)
            system_prompt = conv.system_prompt or DEFAULT_SYSTEM_PROMPT

            # Get tool definitions
            tool_definitions = get_tool_definitions()

            # Create service and pin content
            service = PinnedContentService(db, redis)
            async for event in service.pin_content_stream(
                conversation_id=conversation_id,
                files=files,
                mime_types=mime_types if mime_types else None,
                model_name=model_name,
                system_prompt=system_prompt,
                tool_definitions=tool_definitions,
            ):
                yield {
                    "event": event["event"],
                    "data": json.dumps(event["data"]),
                }

            # Commit the transaction
            await db.commit()

        except Exception as e:
            logger.exception(f"Error pinning content: {e}")
            yield {
                "event": "error",
                "data": json.dumps(
                    {
                        "code": "INTERNAL_ERROR",
                        "message": str(e),
                    }
                ),
            }

    return EventSourceResponse(event_generator())


@router.post("/{conversation_id}/pin")
async def pin_content_post(
    request: Request,
    conversation_id: UUID,
    data: PinContentRequest,
    db: DBSession,
    redis: Redis,
    current_user: CurrentUser,
) -> EventSourceResponse:
    """Pin content to conversation cache via SSE (POST body).

    Accepts direct file content or S3 paths. Returns SSE stream with progress.
    """
    s3 = get_s3_service()
    user_id = str(current_user.id)

    async def event_generator() -> AsyncGenerator[dict[str, Any], None]:
        try:
            files: dict[str, str | bytes] = {}
            mime_types: dict[str, str] = data.mime_types or {}

            # Add direct file content if provided
            if data.files:
                files.update(data.files)

            # Fetch from S3 if paths provided
            if data.s3_paths:
                yield {
                    "event": "progress",
                    "data": json.dumps(
                        {
                            "phase": "fetching",
                            "current": 0,
                            "total": len(data.s3_paths),
                            "message": "Fetching files from storage...",
                        }
                    ),
                }

                for i, path in enumerate(data.s3_paths):
                    if await request.is_disconnected():
                        return

                    try:
                        full_key = f"users/{user_id}/{path.lstrip('/')}"
                        content = s3.download_obj(full_key)

                        try:
                            files[path] = content.decode("utf-8")
                        except UnicodeDecodeError:
                            files[path] = content

                        yield {
                            "event": "progress",
                            "data": json.dumps(
                                {
                                    "phase": "fetching",
                                    "current": i + 1,
                                    "total": len(data.s3_paths),
                                    "current_file": path,
                                }
                            ),
                        }
                    except Exception as e:
                        logger.warning(f"Failed to fetch {path}: {e}")

            if not files:
                yield {
                    "event": "error",
                    "data": json.dumps(
                        {
                            "code": "NO_FILES",
                            "message": "No files provided or could be loaded.",
                        }
                    ),
                }
                return

            # Get conversation's system prompt
            conv_service = ConversationService(db)
            conv = await conv_service.get_conversation(conversation_id)
            system_prompt = conv.system_prompt or DEFAULT_SYSTEM_PROMPT

            # Get tool definitions
            tool_definitions = get_tool_definitions()

            # Pin content
            service = PinnedContentService(db, redis)
            async for event in service.pin_content_stream(
                conversation_id=conversation_id,
                files=files,
                mime_types=mime_types if mime_types else None,
                model_name=data.model_name,
                system_prompt=system_prompt,
                tool_definitions=tool_definitions,
            ):
                yield {
                    "event": event["event"],
                    "data": json.dumps(event["data"]),
                }

            await db.commit()

        except Exception as e:
            logger.exception(f"Error pinning content: {e}")
            yield {
                "event": "error",
                "data": json.dumps(
                    {
                        "code": "INTERNAL_ERROR",
                        "message": str(e),
                    }
                ),
            }

    return EventSourceResponse(event_generator())


@router.post("/{conversation_id}/check-staleness", response_model=StalenessResponse)
async def check_staleness(
    conversation_id: UUID,
    data: CheckStalenessRequest,
    db: DBSession,
    redis: Redis,
    current_user: CurrentUser,
):
    """Check if pinned content is stale.

    Compares provided file hashes against stored hashes to detect changes.
    """
    service = PinnedContentService(db, redis)
    result = await service.check_staleness(conversation_id, data.current_hashes)
    return StalenessResponse(**result)


@router.get("/{conversation_id}/repin")
async def repin_content_sse(
    request: Request,
    conversation_id: UUID,
    db: DBSession,
    redis: Redis,
    current_user: CurrentUser,
    model_name: str = Query("gemini-2.5-flash", description="Model for budget calculation"),
) -> EventSourceResponse:
    """Repin content to conversation cache via SSE.

    Same as pin but explicitly for replacing existing pinned content.
    """
    # Delegate to pin endpoint - same logic
    return await pin_content_sse(
        request=request,
        conversation_id=conversation_id,
        db=db,
        redis=redis,
        current_user=current_user,
        model_name=model_name,
    )


@router.get("/{conversation_id}/pinned", response_model=PinnedContentInfo | None)
async def get_pinned_content(
    conversation_id: UUID,
    db: DBSession,
    redis: Redis,
    current_user: CurrentUser,
):
    """Get information about pinned content for a conversation.

    Returns None if no content is pinned.
    """
    service = PinnedContentService(db, redis)
    result = await service.get_pinned_content_info(conversation_id)
    if result:
        return PinnedContentInfo(**result)
    return None

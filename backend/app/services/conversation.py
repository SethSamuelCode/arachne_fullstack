"""Conversation service (PostgreSQL async).

Contains business logic for conversation, message, and tool call operations.
"""

import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.db.models.conversation import Conversation, Message, ToolCall
from app.repositories import conversation_repo
from app.schemas.conversation import (
    ConversationCreate,
    ConversationUpdate,
    MessageCreate,
    ToolCallComplete,
    ToolCallCreate,
)


class ConversationService:
    """Service for conversation-related business logic."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # =========================================================================
    # Conversation Methods
    # =========================================================================

    async def get_conversation(
        self,
        conversation_id: UUID,
        *,
        include_messages: bool = False,
    ) -> Conversation:
        """Get conversation by ID.

        Raises:
            NotFoundError: If conversation does not exist.
        """
        conversation = await conversation_repo.get_conversation_by_id(
            self.db, conversation_id, include_messages=include_messages
        )
        if not conversation:
            raise NotFoundError(
                message="Conversation not found",
                details={"conversation_id": str(conversation_id)},
            )
        return conversation

    async def list_conversations(
        self,
        user_id: UUID | None = None,
        *,
        skip: int = 0,
        limit: int = 50,
        include_archived: bool = False,
    ) -> tuple[list[Conversation], int]:
        """List conversations with pagination.

        Returns:
            Tuple of (conversations, total_count).
        """
        items = await conversation_repo.get_conversations_by_user(
            self.db,
            user_id=user_id,
            skip=skip,
            limit=limit,
            include_archived=include_archived,
        )
        total = await conversation_repo.count_conversations(
            self.db,
            user_id=user_id,
            include_archived=include_archived,
        )
        return items, total

    async def create_conversation(
        self,
        data: ConversationCreate,
    ) -> Conversation:
        """Create a new conversation."""
        return await conversation_repo.create_conversation(
            self.db,
            user_id=data.user_id,
            title=data.title,
            system_prompt=data.system_prompt,
        )

    async def update_conversation(
        self,
        conversation_id: UUID,
        data: ConversationUpdate,
    ) -> Conversation:
        """Update a conversation.

        Raises:
            NotFoundError: If conversation does not exist.
        """
        conversation = await self.get_conversation(conversation_id)
        update_data = data.model_dump(exclude_unset=True)
        return await conversation_repo.update_conversation(
            self.db, db_conversation=conversation, update_data=update_data
        )

    async def archive_conversation(self, conversation_id: UUID) -> Conversation:
        """Archive a conversation.

        Raises:
            NotFoundError: If conversation does not exist.
        """
        conversation = await conversation_repo.archive_conversation(self.db, conversation_id)
        if not conversation:
            raise NotFoundError(
                message="Conversation not found",
                details={"conversation_id": str(conversation_id)},
            )
        return conversation

    async def delete_conversation(self, conversation_id: UUID) -> bool:
        """Delete a conversation.

        Raises:
            NotFoundError: If conversation does not exist.
        """
        deleted = await conversation_repo.delete_conversation(self.db, conversation_id)
        if not deleted:
            raise NotFoundError(
                message="Conversation not found",
                details={"conversation_id": str(conversation_id)},
            )
        return True

    # =========================================================================
    # Message Methods
    # =========================================================================

    async def get_message(self, message_id: UUID) -> Message:
        """Get message by ID.

        Raises:
            NotFoundError: If message does not exist.
        """
        message = await conversation_repo.get_message_by_id(self.db, message_id)
        if not message:
            raise NotFoundError(
                message="Message not found",
                details={"message_id": str(message_id)},
            )
        return message

    async def list_messages(
        self,
        conversation_id: UUID,
        *,
        skip: int = 0,
        limit: int = 100,
        include_tool_calls: bool = False,
    ) -> tuple[list[Message], int]:
        """List messages in a conversation.

        Returns:
            Tuple of (messages, total_count).
        """
        # Verify conversation exists
        await self.get_conversation(conversation_id)
        items = await conversation_repo.get_messages_by_conversation(
            self.db,
            conversation_id,
            skip=skip,
            limit=limit,
            include_tool_calls=include_tool_calls,
        )
        total = await conversation_repo.count_messages(self.db, conversation_id)
        return items, total

    async def add_message(
        self,
        conversation_id: UUID,
        data: MessageCreate,
    ) -> Message:
        """Add a message to a conversation.

        Raises:
            NotFoundError: If conversation does not exist.
        """
        # Verify conversation exists
        await self.get_conversation(conversation_id)
        return await conversation_repo.create_message(
            self.db,
            conversation_id=conversation_id,
            role=data.role,
            content=data.content,
            thinking_content=data.thinking_content,
            model_name=data.model_name,
            tokens_used=data.tokens_used,
        )

    async def delete_message(self, message_id: UUID) -> bool:
        """Delete a message.

        Raises:
            NotFoundError: If message does not exist.
        """
        deleted = await conversation_repo.delete_message(self.db, message_id)
        if not deleted:
            raise NotFoundError(
                message="Message not found",
                details={"message_id": str(message_id)},
            )
        return True

    # =========================================================================
    # Tool Call Methods
    # =========================================================================

    async def get_tool_call(self, tool_call_id: UUID) -> ToolCall:
        """Get tool call by ID.

        Raises:
            NotFoundError: If tool call does not exist.
        """
        tool_call = await conversation_repo.get_tool_call_by_id(self.db, tool_call_id)
        if not tool_call:
            raise NotFoundError(
                message="Tool call not found",
                details={"tool_call_id": str(tool_call_id)},
            )
        return tool_call

    async def list_tool_calls(self, message_id: UUID) -> list[ToolCall]:
        """List tool calls for a message."""
        # Verify message exists
        await self.get_message(message_id)
        return await conversation_repo.get_tool_calls_by_message(self.db, message_id)

    async def start_tool_call(
        self,
        message_id: UUID,
        data: ToolCallCreate,
    ) -> ToolCall:
        """Record the start of a tool call.

        Raises:
            NotFoundError: If message does not exist.
        """
        # Verify message exists
        await self.get_message(message_id)
        return await conversation_repo.create_tool_call(
            self.db,
            message_id=message_id,
            tool_call_id=data.tool_call_id,
            tool_name=data.tool_name,
            args=data.args,
            started_at=data.started_at or datetime.utcnow(),
        )

    async def complete_tool_call(
        self,
        tool_call_id: UUID,
        data: ToolCallComplete,
    ) -> ToolCall:
        """Mark a tool call as completed.

        Raises:
            NotFoundError: If tool call does not exist.
        """
        tool_call = await self.get_tool_call(tool_call_id)
        return await conversation_repo.complete_tool_call(
            self.db,
            db_tool_call=tool_call,
            result=data.result,
            completed_at=data.completed_at or datetime.utcnow(),
            success=data.success,
        )

    # =========================================================================
    # Title Generation
    # =========================================================================

    async def generate_and_set_title(
        self,
        conversation_id: UUID,
        user_message: str,
        assistant_response: str,
    ) -> str | None:
        """Generate an LLM title for a conversation and persist it.

        Skips if the conversation already has a non-null title (manual rename).
        Falls back to truncated user message on LLM failure.

        Returns:
            The new title, or None if title was already set.
        """
        conversation = await self.get_conversation(conversation_id)
        if conversation.title is not None:
            return None

        title = await _generate_title_via_llm(user_message, assistant_response)
        if not title:
            title = user_message[:50]

        await self.update_conversation(
            conversation_id,
            ConversationUpdate(title=title),
        )
        return title


logger = logging.getLogger(__name__)


async def _generate_title_via_llm(user_message: str, assistant_response: str) -> str | None:
    """Generate a short conversation title using a lightweight LLM.

    Returns:
        A 5-8 word title string, or None on failure.
    """
    try:
        from google import genai

        client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        prompt = (
            "Generate a concise title (5-8 words) for a conversation that starts with:\n\n"
            f"User: {user_message[:200]}\n\n"
            f"Assistant: {assistant_response[:200]}\n\n"
            "Reply with ONLY the title, no quotes, no punctuation at the end."
        )
        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash-lite",
            contents=prompt,
        )
        title = response.text.strip().strip('"').strip("'")
        if title:
            return title[:80]
        return None
    except Exception as e:
        logger.warning(f"LLM title generation failed: {e}")
        return None

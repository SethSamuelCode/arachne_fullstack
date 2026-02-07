"""Pinned content service for context caching.

Manages the lifecycle of pinned content for conversations:
- Pin content (serialize, validate budget, create cache)
- Check staleness (compare file hashes)
- Repin content (replace with updated files)
- Retrieve pinned content metadata

Uses SSE (Server-Sent Events) for progress reporting during
long-running operations like large file serialization.
"""

import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context_optimizer import get_cached_content
from app.agents.repo_serializer import (
    calculate_content_hash,
    calculate_file_hashes,
    serialize_content,
    validate_pinned_content_budget,
)
from app.clients.redis import RedisClient
from app.db.models.conversation import Conversation, ConversationPinnedContent
from app.schemas.attachment import MAX_PINNED_FILE_SIZE_BYTES

logger = logging.getLogger(__name__)


class PinnedContentError(Exception):
    """Base exception for pinned content operations."""

    def __init__(self, message: str, code: str = "PINNED_CONTENT_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class FileTooLargeError(PinnedContentError):
    """Raised when a file exceeds the size limit."""

    def __init__(self, path: str, size: int):
        max_mb = MAX_PINNED_FILE_SIZE_BYTES / (1024 * 1024)
        actual_mb = size / (1024 * 1024)
        super().__init__(
            f"File '{path}' ({actual_mb:.1f}MB) exceeds {max_mb}MB limit",
            code="FILE_TOO_LARGE",
        )


class BudgetExceededError(PinnedContentError):
    """Raised when pinned content exceeds token budget."""

    def __init__(self, budget_percent: float, max_percent: int):
        super().__init__(
            f"Pinned content ({budget_percent:.1f}%) exceeds {max_percent}% budget limit",
            code="BUDGET_EXCEEDED",
        )


class ConversationNotFoundError(PinnedContentError):
    """Raised when conversation doesn't exist."""

    def __init__(self, conversation_id: UUID):
        super().__init__(
            f"Conversation {conversation_id} not found",
            code="CONVERSATION_NOT_FOUND",
        )


class PinnedContentService:
    """Service for managing pinned content in conversations."""

    def __init__(self, db: AsyncSession, redis_client: RedisClient | None = None):
        """Initialize service.

        Args:
            db: Async database session.
            redis_client: Optional Redis client for cache operations.
        """
        self.db = db
        self.redis_client = redis_client

    async def _get_conversation(self, conversation_id: UUID) -> Conversation:
        """Get conversation by ID or raise error."""
        result = await self.db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conversation = result.scalar_one_or_none()
        if not conversation:
            raise ConversationNotFoundError(conversation_id)
        return conversation

    async def _get_pinned_content(
        self, conversation_id: UUID
    ) -> ConversationPinnedContent | None:
        """Get pinned content for a conversation."""
        result = await self.db.execute(
            select(ConversationPinnedContent).where(
                ConversationPinnedContent.conversation_id == conversation_id
            )
        )
        return result.scalar_one_or_none()

    async def pin_content_stream(
        self,
        conversation_id: UUID,
        files: dict[str, str | bytes],
        mime_types: dict[str, str] | None,
        model_name: str,
        system_prompt: str | None = None,
        tool_definitions: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Pin content to a conversation with progress streaming.

        Yields SSE-compatible events for each phase of the operation:
        - progress: Current phase and completion status
        - warning: Budget warnings (30-40%)
        - error: Failures
        - complete: Final result with cache info

        Args:
            conversation_id: Target conversation ID.
            files: Dict mapping file paths to content.
            mime_types: Optional dict mapping paths to MIME types.
            model_name: Gemini model name for budget calculation.
            system_prompt: Optional system prompt to include in cache.
            tool_definitions: Optional tool definitions to include in cache.

        Yields:
            SSE event dicts with 'event' and 'data' keys.
        """
        total_files = len(files)

        try:
            # Verify conversation exists
            await self._get_conversation(conversation_id)

            # Phase 1: Reading/validating files
            yield {
                "event": "progress",
                "data": {
                    "phase": "validating",
                    "current": 0,
                    "total": total_files,
                    "message": "Validating files...",
                },
            }

            # Validate file sizes
            for i, (path, content) in enumerate(files.items()):
                size = len(content) if isinstance(content, (str, bytes)) else 0
                if size > MAX_PINNED_FILE_SIZE_BYTES:
                    yield {
                        "event": "error",
                        "data": {
                            "code": "FILE_TOO_LARGE",
                            "message": f"File '{path}' exceeds 100MB limit",
                            "path": path,
                        },
                    }
                    return

                if (i + 1) % 10 == 0 or i == total_files - 1:
                    yield {
                        "event": "progress",
                        "data": {
                            "phase": "validating",
                            "current": i + 1,
                            "total": total_files,
                            "current_file": path,
                        },
                    }

            # Phase 2: Hashing files
            yield {
                "event": "progress",
                "data": {
                    "phase": "hashing",
                    "current": 0,
                    "total": total_files,
                    "message": "Computing file hashes...",
                },
            }

            file_hashes = calculate_file_hashes(files)
            content_hash = calculate_content_hash(files)

            yield {
                "event": "progress",
                "data": {
                    "phase": "hashing",
                    "current": total_files,
                    "total": total_files,
                    "content_hash": content_hash,
                },
            }

            # Phase 3: Serializing content
            yield {
                "event": "progress",
                "data": {
                    "phase": "serializing",
                    "current": 0,
                    "total": 1,
                    "message": "Serializing content for cache...",
                },
            }

            parts, total_tokens = serialize_content(files, mime_types)

            yield {
                "event": "progress",
                "data": {
                    "phase": "serializing",
                    "current": 1,
                    "total": 1,
                    "tokens": total_tokens,
                },
            }

            # Phase 4: Validate budget
            yield {
                "event": "progress",
                "data": {
                    "phase": "estimating",
                    "tokens": total_tokens,
                    "message": "Checking token budget...",
                },
            }

            budget_info = validate_pinned_content_budget(total_tokens, model_name)

            if budget_info["warning"]:
                yield {
                    "event": "warning",
                    "data": {
                        "type": "budget",
                        "percent": budget_info["budget_percent"],
                        "message": budget_info["warning"],
                    },
                }

            if budget_info["error"]:
                yield {
                    "event": "warning",
                    "data": {
                        "type": "budget_exceeded",
                        "percent": budget_info["budget_percent"],
                        "message": budget_info["error"],
                    },
                }
                # Continue anyway - user was warned

            # Phase 5: Create/get cache
            yield {
                "event": "progress",
                "data": {
                    "phase": "uploading",
                    "message": "Creating cache...",
                    "status": "creating_cache",
                },
            }

            cache_name = await get_cached_content(
                prompt=system_prompt or "",
                model_name=model_name,
                tool_definitions=tool_definitions,
                redis_client=self.redis_client,
                pinned_parts=parts,
                pinned_content_hash=content_hash,
            )

            # Phase 6: Store metadata in DB
            yield {
                "event": "progress",
                "data": {
                    "phase": "storing",
                    "message": "Saving metadata...",
                },
            }

            # Check if pinned content already exists
            existing = await self._get_pinned_content(conversation_id)

            if existing:
                # Update existing record
                existing.content_hash = content_hash
                existing.file_paths = list(files.keys())
                existing.file_hashes = file_hashes
                existing.total_tokens = total_tokens
                existing.pinned_at = datetime.now(UTC)
            else:
                # Create new record
                pinned = ConversationPinnedContent(
                    conversation_id=conversation_id,
                    content_hash=content_hash,
                    file_paths=list(files.keys()),
                    file_hashes=file_hashes,
                    total_tokens=total_tokens,
                    pinned_at=datetime.now(UTC),
                )
                self.db.add(pinned)

            await self.db.flush()

            # Complete
            yield {
                "event": "complete",
                "data": {
                    "cache_name": cache_name,
                    "content_hash": content_hash,
                    "total_tokens": total_tokens,
                    "budget_percent": budget_info["budget_percent"],
                    "file_count": total_files,
                },
            }

        except PinnedContentError as e:
            yield {
                "event": "error",
                "data": {
                    "code": e.code,
                    "message": e.message,
                },
            }
        except Exception as e:
            logger.exception(f"Unexpected error pinning content: {e}")
            yield {
                "event": "error",
                "data": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e),
                },
            }

    async def check_staleness(
        self,
        conversation_id: UUID,
        current_hashes: dict[str, str],
    ) -> dict[str, Any]:
        """Check if pinned content is stale.

        Compares provided file hashes against stored hashes to detect
        files that have changed since pinning.

        Args:
            conversation_id: Conversation ID.
            current_hashes: Dict mapping file paths to current SHA256 hashes.

        Returns:
            Dict with:
            - is_stale: bool
            - changed_files: list of paths that changed
            - added_files: list of new paths not in original pin
            - removed_files: list of paths no longer present
        """
        pinned = await self._get_pinned_content(conversation_id)

        if not pinned:
            return {
                "is_stale": False,
                "changed_files": [],
                "added_files": [],
                "removed_files": [],
                "has_pinned_content": False,
            }

        stored_hashes = pinned.file_hashes
        stored_paths = set(stored_hashes.keys())
        current_paths = set(current_hashes.keys())

        changed_files = [
            path
            for path in stored_paths & current_paths
            if stored_hashes.get(path) != current_hashes.get(path)
        ]
        added_files = list(current_paths - stored_paths)
        removed_files = list(stored_paths - current_paths)

        is_stale = bool(changed_files or added_files or removed_files)

        return {
            "is_stale": is_stale,
            "changed_files": changed_files,
            "added_files": added_files,
            "removed_files": removed_files,
            "has_pinned_content": True,
        }

    async def repin_content_stream(
        self,
        conversation_id: UUID,
        files: dict[str, str | bytes],
        mime_types: dict[str, str] | None,
        model_name: str,
        system_prompt: str | None = None,
        tool_definitions: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Repin content (replace existing pinned content).

        Same as pin_content_stream but explicitly for replacing existing content.
        Creates a new cache with updated files.

        Args:
            conversation_id: Target conversation ID.
            files: Dict mapping file paths to content.
            mime_types: Optional dict mapping paths to MIME types.
            model_name: Gemini model name.
            system_prompt: Optional system prompt.
            tool_definitions: Optional tool definitions.

        Yields:
            SSE event dicts.
        """
        # Repin is the same as pin - the DB record is updated
        async for event in self.pin_content_stream(
            conversation_id=conversation_id,
            files=files,
            mime_types=mime_types,
            model_name=model_name,
            system_prompt=system_prompt,
            tool_definitions=tool_definitions,
        ):
            yield event

    async def get_pinned_content_info(
        self, conversation_id: UUID
    ) -> dict[str, Any] | None:
        """Get pinned content metadata for a conversation.

        Args:
            conversation_id: Conversation ID.

        Returns:
            Dict with pinned content info or None if no content pinned.
        """
        pinned = await self._get_pinned_content(conversation_id)

        if not pinned:
            return None

        return {
            "content_hash": pinned.content_hash,
            "file_paths": pinned.file_paths,
            "file_hashes": pinned.file_hashes,
            "total_tokens": pinned.total_tokens,
            "pinned_at": pinned.pinned_at.isoformat(),
        }

    async def get_pinned_content_hash(
        self, conversation_id: UUID
    ) -> str | None:
        """Get the content hash for pinned content.

        Used by the agent flow to include in cache key derivation.

        Args:
            conversation_id: Conversation ID.

        Returns:
            Content hash string or None if no content pinned.
        """
        pinned = await self._get_pinned_content(conversation_id)
        return pinned.content_hash if pinned else None

    async def get_pinned_tokens(self, conversation_id: UUID) -> int:
        """Get the token count for pinned content.

        Used for budget calculations in context optimization.

        Args:
            conversation_id: Conversation ID.

        Returns:
            Token count or 0 if no content pinned.
        """
        pinned = await self._get_pinned_content(conversation_id)
        return pinned.total_tokens if pinned else 0

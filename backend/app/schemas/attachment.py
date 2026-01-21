"""Attachment schemas for image and file handling in chat messages.

This module contains Pydantic schemas for message attachments (images, files).
"""

from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.base import BaseSchema, TimestampSchema

# =============================================================================
# Constants
# =============================================================================

# Gemini-confirmed supported image MIME types
ALLOWED_IMAGE_MIME_TYPES: frozenset[str] = frozenset({
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/heic",
    "image/heif",
})

# Maximum total size for all attachments in a single message (20MB for Gemini inline limit)
MAX_TOTAL_ATTACHMENT_SIZE_BYTES: int = 20 * 1024 * 1024  # 20MB


# =============================================================================
# Attachment Schemas
# =============================================================================


class AttachmentBase(BaseSchema):
    """Base attachment schema."""

    s3_key: str = Field(..., description="S3 object key for the attachment")
    mime_type: str = Field(..., description="MIME type of the attachment")
    filename: str | None = Field(default=None, description="Original filename")
    size_bytes: int = Field(..., ge=0, description="File size in bytes")

    @field_validator("mime_type")
    @classmethod
    def validate_mime_type(cls, v: str) -> str:
        """Validate that mime_type is in the allowed list."""
        if v not in ALLOWED_IMAGE_MIME_TYPES:
            allowed = ", ".join(sorted(ALLOWED_IMAGE_MIME_TYPES))
            raise ValueError(f"Unsupported MIME type '{v}'. Allowed types: {allowed}")
        return v


class AttachmentCreate(AttachmentBase):
    """Schema for creating an attachment (sent with chat message)."""

    pass


class AttachmentRead(AttachmentBase, TimestampSchema):
    """Schema for reading an attachment (API response)."""

    id: UUID
    message_id: UUID


class AttachmentInMessage(BaseSchema):
    """Simplified attachment schema for WebSocket messages."""

    s3_key: str = Field(..., description="S3 object key for the attachment")
    mime_type: str = Field(..., description="MIME type of the attachment")
    size_bytes: int = Field(..., ge=0, description="File size in bytes")
    filename: str | None = Field(default=None, description="Original filename")

    @field_validator("mime_type")
    @classmethod
    def validate_mime_type(cls, v: str) -> str:
        """Validate that mime_type is in the allowed list."""
        if v not in ALLOWED_IMAGE_MIME_TYPES:
            allowed = ", ".join(sorted(ALLOWED_IMAGE_MIME_TYPES))
            raise ValueError(f"Unsupported MIME type '{v}'. Allowed types: {allowed}")
        return v


def validate_attachments_total_size(attachments: list[AttachmentInMessage]) -> None:
    """Validate that total attachment size doesn't exceed limit.

    Args:
        attachments: List of attachments to validate.

    Raises:
        ValueError: If total size exceeds MAX_TOTAL_ATTACHMENT_SIZE_BYTES.
    """
    total_size = sum(a.size_bytes for a in attachments)
    if total_size > MAX_TOTAL_ATTACHMENT_SIZE_BYTES:
        max_mb = MAX_TOTAL_ATTACHMENT_SIZE_BYTES / (1024 * 1024)
        total_mb = total_size / (1024 * 1024)
        raise ValueError(
            f"Total attachment size ({total_mb:.1f}MB) exceeds maximum allowed ({max_mb:.0f}MB)"
        )

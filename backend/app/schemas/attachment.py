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
ALLOWED_IMAGE_MIME_TYPES: frozenset[str] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/heic",
        "image/heif",
    }
)

# Gemini-supported MIME types for pinned content (context caching)
# Includes images, audio, and video formats supported by Gemini
ALLOWED_PINNED_MIME_TYPES: frozenset[str] = frozenset(
    {
        # Images (same as chat attachments)
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/heic",
        "image/heif",
        "image/gif",
        # Audio formats (Gemini multimodal support)
        "audio/wav",
        "audio/mp3",
        "audio/mpeg",
        "audio/aiff",
        "audio/aac",
        "audio/ogg",
        "audio/flac",
        # Video formats (Gemini multimodal support)
        "video/mp4",
        "video/mpeg",
        "video/mov",
        "video/avi",
        "video/x-flv",
        "video/mpg",
        "video/webm",
        "video/wmv",
        "video/3gpp",
        # Text/code (handled separately but included for validation)
        "text/plain",
        "text/html",
        "text/css",
        "text/javascript",
        "application/json",
        "application/xml",
        "text/xml",
        "text/markdown",
        "text/x-python",
        "text/x-java",
        "text/x-c",
        "text/x-typescript",
    }
)

# Text file extensions for pinned content (will be serialized as XML)
PINNED_TEXT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".txt",
        ".md",
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".json",
        ".yaml",
        ".yml",
        ".xml",
        ".html",
        ".css",
        ".csv",
        ".log",
        ".sh",
        ".bash",
        ".env",
        ".toml",
        ".ini",
        ".cfg",
        ".rst",
        ".sql",
        ".r",
        ".rb",
        ".go",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".cs",
        ".php",
        ".swift",
        ".kt",
        ".kts",
        ".scala",
        ".rs",
        ".lua",
        ".pl",
        ".pm",
        ".ex",
        ".exs",
        ".erl",
        ".hs",
        ".ml",
        ".mli",
        ".fs",
        ".fsx",
        ".clj",
        ".cljs",
        ".vue",
        ".svelte",
        ".astro",
        ".graphql",
        ".gql",
        ".proto",
        ".dockerfile",
        ".gitignore",
        ".editorconfig",
        ".prettierrc",
        ".eslintrc",
        ".babelrc",
        ".env.example",
        ".env.local",
        ".env.development",
        ".env.production",
        ".env.test",
        "makefile",
        ".mk",
        ".cmake",
        ".gradle",
        ".sbt",
        ".pom",
        ".csproj",
        ".fsproj",
        ".vbproj",
        ".sln",
    }
)

# Maximum total size for all attachments in a single message (20MB for Gemini inline limit)
MAX_TOTAL_ATTACHMENT_SIZE_BYTES: int = 20 * 1024 * 1024  # 20MB

# Maximum size for individual pinned files (100MB - Gemini media limit)
MAX_PINNED_FILE_SIZE_BYTES: int = 100 * 1024 * 1024  # 100MB


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

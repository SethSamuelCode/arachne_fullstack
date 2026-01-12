"""S3 image fetching tool for visual analysis.

This tool allows the agent to fetch images from S3 storage and inject them
into its context window for visual understanding.
"""

import mimetypes
from typing import TYPE_CHECKING

from pydantic_ai import BinaryContent, RunContext, ToolReturn

from app.schemas.attachment import ALLOWED_IMAGE_MIME_TYPES, MAX_TOTAL_ATTACHMENT_SIZE_BYTES

if TYPE_CHECKING:
    from app.schemas.assistant import Deps
    from app.schemas.spawn_agent_deps import SpawnAgentDeps


def _get_mime_type(object_name: str) -> str | None:
    """Detect MIME type from file extension."""
    mime_type, _ = mimetypes.guess_type(object_name)
    return mime_type


async def s3_fetch_image_impl(
    ctx: "RunContext[Deps | SpawnAgentDeps]",
    object_name: str,
) -> ToolReturn:
    """Fetch an image from S3 and inject it into context for visual analysis.

    Use this tool when the user asks you to look at, analyze, describe, read,
    extract information from, or understand an image stored in their S3 storage.

    WHEN TO USE:
    - User says "look at", "analyze", "describe", "read", "extract from",
      "what's in", "explain", or "understand" an image/photo/screenshot/picture
    - User references a file with image extension (.png, .jpg, .jpeg, .webp,
      .heic, .heif) and wants visual analysis
    - User asks about contents of an image file they've uploaded

    WHEN NOT TO USE:
    - For non-image files (text, CSV, JSON, etc.) — use s3_read_string_content instead
    - When the user has already attached images to the current message (they're
      already in your context)
    - For listing files — use s3_list_objects first if you don't know the exact filename

    WORKFLOW:
    1. If user doesn't provide exact filename, call s3_list_objects first to find it
    2. Call this tool with the image filename
    3. Analyze the returned image and respond to user's question

    SUPPORTED FORMATS:
    PNG (.png), JPEG (.jpg, .jpeg), WebP (.webp), HEIC (.heic), HEIF (.heif)

    SIZE LIMIT: Maximum 20MB per image

    ARGS:
        object_name: The key (name) of the image in the user's storage
                     (e.g., 'photos/receipt.png', 'screenshots/error.jpg').
                     Do NOT include 'users/<id>/' prefix — it's added automatically.

    RETURNS:
        The image loaded into your context for visual analysis. You can then
        describe, analyze, or extract information from the image.

    ERRORS:
        - File not found: The specified image doesn't exist in storage
        - Unsupported format: The file is not a supported image type
        - File too large: Image exceeds 20MB limit
    """
    from app.services.s3 import get_s3_service

    s3 = get_s3_service()

    # Build full S3 key with user prefix
    user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
    full_key = f"{user_prefix}{object_name}"

    # Detect MIME type from extension
    mime_type = _get_mime_type(object_name)
    if not mime_type or mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_MIME_TYPES))
        return ToolReturn(
            return_value=f"Error: '{object_name}' is not a supported image format. "
            f"Supported formats: {allowed}",
            content=[
                f"The file '{object_name}' cannot be loaded as an image. "
                f"Supported image formats are: {allowed}. "
                "If this is a text file, use s3_read_string_content instead."
            ],
        )

    # Download the image
    try:
        image_data = s3.download_obj(full_key)
    except Exception as e:
        error_msg = str(e)
        if "NoSuchKey" in error_msg or "not found" in error_msg.lower():
            return ToolReturn(
                return_value=f"Error: Image '{object_name}' not found in storage.",
                content=[
                    f"The image '{object_name}' was not found in your storage. "
                    "Use s3_list_objects to see available files."
                ],
            )
        return ToolReturn(
            return_value=f"Error downloading image: {error_msg}",
            content=[f"Failed to download image '{object_name}': {error_msg}"],
        )

    # Check file size
    size_bytes = len(image_data)
    if size_bytes > MAX_TOTAL_ATTACHMENT_SIZE_BYTES:
        max_mb = MAX_TOTAL_ATTACHMENT_SIZE_BYTES / (1024 * 1024)
        size_mb = size_bytes / (1024 * 1024)
        return ToolReturn(
            return_value=f"Error: Image too large ({size_mb:.1f}MB). Maximum is {max_mb:.0f}MB.",
            content=[
                f"The image '{object_name}' is {size_mb:.1f}MB, which exceeds "
                f"the maximum allowed size of {max_mb:.0f}MB."
            ],
        )

    # Return the image for visual analysis
    size_kb = size_bytes / 1024
    return ToolReturn(
        return_value=f"Image '{object_name}' loaded successfully ({size_kb:.1f}KB, {mime_type}).",
        content=[
            f"Here is the image '{object_name}' for visual analysis:",
            BinaryContent(data=image_data, media_type=mime_type),
        ],
        metadata={
            "object_name": object_name,
            "full_key": full_key,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
        },
    )

"""Repository serializer for context caching.

Serializes files (text, images, audio, video) into a format suitable for
Gemini's CachedContent API. Text files are wrapped in XML structure,
binary files are converted to Gemini Part objects with inline data.

The serialized content hash enables automatic cache reuse across
conversations with identical pinned content.
"""

import hashlib
import html
import logging
from pathlib import Path
from typing import Any

from google.genai import types as genai_types

from app.core.config import settings
from app.schemas.attachment import (
    ALLOWED_PINNED_MIME_TYPES,
    MAX_PINNED_FILE_SIZE_BYTES,
    PINNED_TEXT_EXTENSIONS,
)

logger = logging.getLogger(__name__)


# Directories to always exclude from pinned content
IGNORE_DIRS: frozenset[str] = frozenset({
    ".git",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "env",
    ".env",
    ".tox",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "coverage",
    ".coverage",
    "htmlcov",
    ".eggs",
    "*.egg-info",
})

# File patterns to always exclude
IGNORE_FILES: frozenset[str] = frozenset({
    ".DS_Store",
    "Thumbs.db",
    ".gitignore",
    ".dockerignore",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
    "composer.lock",
    "Gemfile.lock",
    "Cargo.lock",
})


def estimate_tokens(content: str | bytes) -> int:
    """Estimate token count using char/4 heuristic for text.

    For binary content (images/audio/video), uses approximate token counts
    based on Gemini's documentation:
    - Images: ~258 tokens (small) to ~1.3M (large)
    - Audio: ~32 tokens/second
    - Video: ~258 tokens/second (frames) + audio

    Args:
        content: Text string or binary bytes.

    Returns:
        Estimated token count.
    """
    if isinstance(content, str):
        return len(content) // 4
    # Binary content - rough estimate based on size
    # Gemini uses ~258-1290 tokens for most images
    # For simplicity, estimate 1 token per 100 bytes for binary
    return max(258, len(content) // 100)


def estimate_tokens_for_mime(content: bytes, mime_type: str) -> int:
    """Estimate tokens based on MIME type and content size.

    Uses Gemini's documented token counts:
    - Images: 258 tokens (small <384px) to 1290 tokens per tile
    - Audio: ~32 tokens/second (~25 bytes/token for typical audio)
    - Video: ~258 tokens/second for frames + audio track

    Args:
        content: Binary content.
        mime_type: MIME type of the content.

    Returns:
        Estimated token count.
    """
    size = len(content)

    if mime_type.startswith("image/"):
        # Images: 258-1290 tokens depending on size
        # Rough heuristic: small images (~100KB) = 258, large (~4MB) = 1290
        if size < 100_000:
            return 258
        elif size < 1_000_000:
            return 768
        else:
            return 1290

    if mime_type.startswith("audio/"):
        # Audio: ~32 tokens/second, typical bitrate ~128kbps = 16KB/s
        # So roughly 32 tokens per 16KB = 2 tokens per KB
        return max(32, (size // 1024) * 2)

    if mime_type.startswith("video/"):
        # Video: ~258 tokens/second for 1fps, plus audio
        # Typical bitrate ~1Mbps = 125KB/s, so ~2 tokens per KB
        return max(258, (size // 1024) * 2)

    # Text or unknown - use char/4 heuristic
    return max(1, size // 4)


def calculate_file_hash(content: str | bytes) -> str:
    """Calculate SHA256 hash of file content.

    Args:
        content: File content (text or binary).

    Returns:
        64-character hex SHA256 hash.
    """
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def calculate_content_hash(files: dict[str, str | bytes]) -> str:
    """Calculate a combined hash of all pinned content.

    Creates a deterministic hash by sorting files by path and hashing
    the concatenated content. This hash is used for cache key derivation
    to enable automatic cache reuse across conversations.

    Args:
        files: Dict mapping file paths to content.

    Returns:
        16-character hex hash for cache key.
    """
    hasher = hashlib.sha256()

    # Sort by path for deterministic ordering
    for path in sorted(files.keys()):
        content = files[path]
        if isinstance(content, str):
            content = content.encode("utf-8")
        # Include path in hash to distinguish files with same content
        hasher.update(path.encode("utf-8"))
        hasher.update(content)

    return hasher.hexdigest()[:16]


def calculate_file_hashes(files: dict[str, str | bytes]) -> dict[str, str]:
    """Calculate individual hashes for all files.

    Used for staleness detection - comparing current file hashes
    against stored hashes to detect changes.

    Args:
        files: Dict mapping file paths to content.

    Returns:
        Dict mapping file paths to SHA256 hashes.
    """
    return {path: calculate_file_hash(content) for path, content in files.items()}


def is_text_file(path: str, mime_type: str | None = None) -> bool:
    """Determine if a file should be treated as text.

    Args:
        path: File path.
        mime_type: Optional MIME type hint.

    Returns:
        True if file should be serialized as text XML.
    """
    p = Path(path)
    filename = p.name.lower()

    # Check compound extensions like .env.example, .env.local
    for ext in PINNED_TEXT_EXTENSIONS:
        if filename.endswith(ext):
            return True

    # Check simple extension
    suffix = p.suffix.lower()
    if suffix in PINNED_TEXT_EXTENSIONS:
        return True

    # Check MIME type
    if mime_type:
        return mime_type.startswith("text/") or mime_type in {
            "application/json",
            "application/xml",
            "application/javascript",
        }

    # Files without extension - check if common text filenames
    text_filenames = {
        "makefile",
        "dockerfile",
        "jenkinsfile",
        "vagrantfile",
        "gemfile",
        "rakefile",
        "procfile",
        "readme",
        "license",
        "changelog",
        "authors",
        "contributors",
        "todo",
        "notes",
    }
    return filename in text_filenames


def should_ignore_file(path: str) -> bool:
    """Check if a file should be ignored based on path patterns.

    Args:
        path: File path.

    Returns:
        True if file should be excluded from pinned content.
    """
    path_obj = Path(path)

    # Check directory components
    for part in path_obj.parts:
        if part in IGNORE_DIRS:
            return True

    # Check filename
    if path_obj.name in IGNORE_FILES:
        return True

    # Check for lock files by extension
    if path_obj.suffix == ".lock":
        return True

    return False


def escape_xml_content(content: str) -> str:
    """Escape content for safe XML embedding.

    Uses HTML escaping which covers XML special characters.

    Args:
        content: Raw text content.

    Returns:
        XML-safe escaped content.
    """
    return html.escape(content, quote=False)


# Preamble prepended to pinned content XML to instruct model on priority
REPOSITORY_CONTEXT_PREAMBLE = """The following files were pinned by the user as authoritative reference material.
Answer questions from this data before searching externally.
"""


def build_xml_wrapper(text_files: dict[str, str]) -> str:
    """Build XML structure for text files.

    Creates a <repository_context> XML document with each file
    wrapped in a <file path="..."> element. Includes a preamble
    instructing the model to prioritize this content.

    Args:
        text_files: Dict mapping file paths to text content.

    Returns:
        XML-formatted string with preamble.
    """
    lines = [REPOSITORY_CONTEXT_PREAMBLE.strip(), '', '<repository_context>']

    # Sort files for consistent ordering
    for path in sorted(text_files.keys()):
        content = text_files[path]
        escaped_path = html.escape(path, quote=True)
        escaped_content = escape_xml_content(content)
        lines.append(f'<file path="{escaped_path}">')
        lines.append(escaped_content)
        lines.append('</file>')

    lines.append('</repository_context>')
    return '\n'.join(lines)


def serialize_content(
    files: dict[str, str | bytes],
    mime_types: dict[str, str] | None = None,
) -> tuple[list[genai_types.Part], int]:
    """Serialize files into Gemini Part objects for caching.

    Text files are combined into a single XML-structured Part.
    Binary files (images, audio, video) become individual Parts with inline_data.

    Args:
        files: Dict mapping file paths to content (text or bytes).
        mime_types: Optional dict mapping file paths to MIME types.
            If not provided, types are inferred from extensions.

    Returns:
        Tuple of (list of Gemini Parts, total estimated tokens).
    """
    mime_types = mime_types or {}
    parts: list[genai_types.Part] = []
    total_tokens = 0

    # Separate text and binary files
    text_files: dict[str, str] = {}
    binary_files: list[tuple[str, bytes, str]] = []  # (path, content, mime_type)

    for path, content in files.items():
        if should_ignore_file(path):
            logger.debug(f"Ignoring file: {path}")
            continue

        mime_type = mime_types.get(path)

        if isinstance(content, str):
            # Text content
            text_files[path] = content
        elif isinstance(content, bytes):
            # Binary content - determine MIME type
            if not mime_type:
                suffix = Path(path).suffix.lower()
                mime_type = _infer_mime_type(suffix)

            if mime_type and mime_type in ALLOWED_PINNED_MIME_TYPES:
                # Validate size
                if len(content) > MAX_PINNED_FILE_SIZE_BYTES:
                    max_mb = MAX_PINNED_FILE_SIZE_BYTES / (1024 * 1024)
                    logger.warning(
                        f"Skipping {path}: size exceeds {max_mb}MB limit"
                    )
                    continue
                binary_files.append((path, content, mime_type))
            else:
                logger.warning(f"Skipping {path}: unsupported MIME type {mime_type}")

    # Build XML for text files
    if text_files:
        xml_content = build_xml_wrapper(text_files)
        parts.append(genai_types.Part(text=xml_content))
        total_tokens += estimate_tokens(xml_content)
        logger.info(
            f"Serialized {len(text_files)} text files with preamble "
            f"(total XML length: {len(xml_content)} chars)"
        )

    # Add binary files as inline data
    for path, content, mime_type in binary_files:
        blob = genai_types.Blob(mime_type=mime_type, data=content)
        parts.append(genai_types.Part(inline_data=blob))
        total_tokens += estimate_tokens_for_mime(content, mime_type)

    return parts, total_tokens


def validate_pinned_content_budget(
    total_tokens: int,
    model_name: str,
) -> dict[str, Any]:
    """Validate that pinned content fits within token budget.

    Returns budget status with warnings if thresholds exceeded.

    Args:
        total_tokens: Estimated token count for pinned content.
        model_name: Gemini model name for budget lookup.

    Returns:
        Dict with keys:
        - within_budget: bool
        - budget_percent: float
        - warning: str | None (if 30-40%)
        - error: str | None (if >40% and would block, but we allow with warning)
    """
    from app.agents.providers.registry import get_provider

    model_budget = get_provider(model_name).context_limit
    max_percent = settings.MAX_PINNED_CONTEXT_PERCENT
    warn_percent = settings.PINNED_CONTEXT_WARNING_PERCENT

    budget_percent = (total_tokens / model_budget) * 100

    result: dict[str, Any] = {
        "within_budget": True,
        "budget_percent": round(budget_percent, 1),
        "total_tokens": total_tokens,
        "max_allowed_tokens": int(model_budget * max_percent / 100),
        "warning": None,
        "error": None,
    }

    if budget_percent > max_percent:
        result["error"] = (
            f"Pinned content ({budget_percent:.1f}% of budget) exceeds {max_percent}% limit. "
            f"May cause degraded performance, truncated history, or failures. "
            f"Consider removing some files."
        )
        # Still allow but flag as over budget
        result["within_budget"] = False
    elif budget_percent > warn_percent:
        result["warning"] = (
            f"Large context ({budget_percent:.1f}% of budget) may slow responses "
            f"and reduce conversation history capacity."
        )

    return result


def _infer_mime_type(suffix: str) -> str | None:
    """Infer MIME type from file extension.

    Args:
        suffix: File extension including dot (e.g., '.png').

    Returns:
        MIME type string or None if unknown.
    """
    mime_map = {
        # Images
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".heic": "image/heic",
        ".heif": "image/heif",
        ".gif": "image/gif",
        # Audio
        ".wav": "audio/wav",
        ".mp3": "audio/mp3",
        ".mpeg": "audio/mpeg",
        ".aiff": "audio/aiff",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        # Video
        ".mp4": "video/mp4",
        ".mov": "video/mov",
        ".avi": "video/avi",
        ".flv": "video/x-flv",
        ".mpg": "video/mpg",
        ".webm": "video/webm",
        ".wmv": "video/wmv",
        ".3gp": "video/3gpp",
    }
    return mime_map.get(suffix.lower())

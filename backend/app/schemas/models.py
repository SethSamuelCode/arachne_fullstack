"""Shared schema primitives.

Keep these small and dependency-free; they are imported by multiple request/response schemas.
"""

from enum import Enum


class GeminiModelName(str, Enum):
    """Allowed Gemini model names.

    This enum exists to:
    - Provide a single allow-list for request validation (Pydantic)
    - Keep OpenAPI schemas stable and easy to consume

    Note: values must match the underlying provider model identifiers.
    """

    GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_5_PRO = "gemini-2.5-pro"
    GEMINI_3_FLASH = "gemini-3-flash-preview"
    GEMINI_3_PRO = "gemini-3-pro-preview"


DEFAULT_GEMINI_MODEL: GeminiModelName = GeminiModelName.GEMINI_2_5_FLASH

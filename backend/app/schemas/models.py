"""Shared schema primitives.

Keep these small and dependency-free; they are imported by multiple request/response schemas.
"""

from enum import Enum


class GeminiModelName(str, Enum):
    """Available Gemini models for agent tasks.

    Selection guide:
    - gemini-2.5-flash-lite: Fastest, cheapest. Simple lookups, formatting.
    - gemini-2.5-flash: Standard tasks, summarization, general Q&A. DEFAULT.
    - gemini-2.5-pro: Complex reasoning, coding, creative writing.
    - gemini-3-flash-preview: Fast with moderate reasoning capability.
    - gemini-3-pro-preview: MAXIMUM reasoning. Architecture, security, hard problems.

    Use stronger models only when task complexity requires it.
    """

    GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_5_PRO = "gemini-2.5-pro"
    GEMINI_3_FLASH = "gemini-3-flash-preview"
    GEMINI_3_PRO = "gemini-3-pro-preview"


DEFAULT_GEMINI_MODEL: GeminiModelName = GeminiModelName.GEMINI_2_5_FLASH

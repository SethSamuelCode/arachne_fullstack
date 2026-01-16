"""Utility functions for data serialization and processing."""

import json
import logging
from typing import Any

from pydantic_ai import ToolReturn

logger = logging.getLogger(__name__)

MAX_RESULT_LENGTH = 5000


def serialize_tool_result_for_db(result_content: Any) -> str:
    """Serialize tool result content to text for database storage.

    Extracts text summaries from ToolReturn objects and truncates large results.
    Handles error dicts with retry suggestion detection.

    Args:
        result_content: Tool result - can be ToolReturn, dict, string, or other types

    Returns:
        JSON string or plain text, truncated to MAX_RESULT_LENGTH chars
    """
    try:
        # Handle ToolReturn objects - extract return_value (text summary)
        if isinstance(result_content, ToolReturn):
            text_result = result_content.return_value
        # Handle error dicts from @safe_tool decorator
        elif isinstance(result_content, dict) and result_content.get("error") is True:
            error_message = result_content.get("message", "Unknown error")
            error_code = result_content.get("code", "ERROR")
            details = result_content.get("details")

            # Detect retryable errors by parsing message
            retry_keywords = ["retry", "rate limit", "429", "503", "timeout", "try again"]
            is_retryable = any(keyword in error_message.lower() for keyword in retry_keywords)
            retry_suggestion = "Consider retrying after a short delay" if is_retryable else None

            # Build structured error JSON
            error_dict = {
                "error": error_message,
                "code": error_code,
                "retry_suggestion": retry_suggestion,
            }
            if details:
                error_dict["details"] = details

            text_result = json.dumps(error_dict, ensure_ascii=False)
        # Handle plain dicts and lists
        elif isinstance(result_content, (dict, list)):
            text_result = json.dumps(result_content, ensure_ascii=False, default=str)
        # Handle strings
        elif isinstance(result_content, str):
            text_result = result_content
        # Handle None
        elif result_content is None:
            text_result = ""
        # Handle other types (convert to string)
        else:
            text_result = str(result_content)

        # Truncate if too long
        if len(text_result) > MAX_RESULT_LENGTH:
            return (
                text_result[:MAX_RESULT_LENGTH]
                + "\n\n...[Result truncated at 5000 chars. Full content in UI]"
            )

        return text_result

    except Exception as e:
        logger.error(f"Error serializing tool result: {e}", exc_info=True)
        return f"[Error serializing result: {e!s}]"


def detect_retry_suggestion(error_message: str) -> str | None:
    """Detect if an error message suggests the operation should be retried.

    Args:
        error_message: Error message text

    Returns:
        Retry suggestion text if applicable, otherwise None
    """
    retry_keywords = ["retry", "rate limit", "429", "503", "timeout", "try again"]
    if any(keyword in error_message.lower() for keyword in retry_keywords):
        return "Consider retrying after a short delay"
    return None

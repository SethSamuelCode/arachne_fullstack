"""Tool decorators for error handling and safety.

Provides decorators to wrap agent tools with standardized error handling,
preventing unhandled exceptions from crashing the server and ensuring
consistent error response formats for the LLM.
"""

import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


def safe_tool(
    func: Callable[P, Awaitable[T]],
) -> Callable[P, Awaitable[T | dict[str, Any]]]:
    """Decorator that catches exceptions and returns standardized error dicts.

    Wraps async tool functions to:
    1. Catch any unhandled exception (except KeyboardInterrupt/SystemExit)
    2. Log the error with full traceback
    3. Return a dict with {"error": True, "message": "...", "code": "...", "details": ...}

    The actual error message is passed through to help the LLM understand
    what went wrong and potentially recover or inform the user.

    Note: KeyboardInterrupt and SystemExit are re-raised to allow proper
    shutdown handling.

    Usage:
        @safe_tool
        async def my_tool(ctx: RunContext[TDeps], arg: str) -> dict[str, Any]:
            ...

    Error Response Format:
        {
            "error": True,
            "message": str,       # Human-readable error message
            "code": str,          # Exception class name (e.g., "NoSuchKey", "ValueError")
            "details": Any | None # Additional context if available
        }
    """

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T | dict[str, Any]:
        try:
            return await func(*args, **kwargs)
        except (KeyboardInterrupt, SystemExit):
            # Re-raise these to allow proper shutdown
            raise
        except Exception as e:
            error_type = type(e).__name__
            error_message = str(e) or "An unexpected error occurred"

            # Extract additional details for boto/AWS errors
            details = None
            if hasattr(e, "response"):
                # Botocore ClientError has response dict
                details = getattr(e, "response", {}).get("Error", {})

            logger.exception(
                "Tool %s failed with %s: %s",
                func.__name__,
                error_type,
                error_message,
            )

            return {
                "error": True,
                "message": error_message,
                "code": error_type,
                "details": details,
            }

    return wrapper

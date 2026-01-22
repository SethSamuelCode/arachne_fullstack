"""User scoping utilities for secure resource isolation.

Provides functions to validate and scope user access to resources,
preventing path traversal attacks and ensuring user isolation.
"""

import re
from urllib.parse import unquote


class UserScopeError(ValueError):
    """Raised when user scope validation fails."""

    pass


def validate_user_id(user_id: str | None) -> str:
    """Validate that user_id is present and properly formatted.

    Args:
        user_id: The user ID to validate.

    Returns:
        The validated user ID.

    Raises:
        UserScopeError: If user_id is None, empty, or contains invalid characters.
    """
    if not user_id:
        raise UserScopeError("user_id is required for this operation")

    # Convert to string if UUID
    user_id_str = str(user_id)

    # Only allow alphanumeric, hyphens, and underscores
    if not re.match(r"^[a-zA-Z0-9_-]+$", user_id_str):
        raise UserScopeError(f"Invalid user_id format: {user_id_str}")

    return user_id_str


def validate_path(path: str) -> str:
    """Validate a path component for security issues.

    Args:
        path: The path to validate.

    Returns:
        The validated and normalized path.

    Raises:
        UserScopeError: If path contains traversal attacks or invalid characters.
    """
    if not path:
        raise UserScopeError("Path cannot be empty")

    # URL decode to catch encoded traversal attempts
    decoded_path = unquote(path)

    # Check for path traversal attempts
    traversal_patterns = [
        "..",
        "./",
        ".\\",
        "//",
        "\\\\",
    ]

    for pattern in traversal_patterns:
        if pattern in decoded_path:
            raise UserScopeError(f"Path traversal attempt detected: {path}")

    # Check for absolute paths
    if decoded_path.startswith("/") or decoded_path.startswith("\\"):
        raise UserScopeError(f"Absolute paths are not allowed: {path}")

    # Check for null bytes (common attack vector)
    if "\x00" in decoded_path:
        raise UserScopeError("Null bytes are not allowed in paths")

    # Normalize the path (remove leading/trailing whitespace)
    normalized = decoded_path.strip()

    if not normalized:
        raise UserScopeError("Path cannot be empty after normalization")

    return normalized


def validate_user_path(user_id: str | None, path: str) -> str:
    """Validate and scope a path to a specific user.

    Combines user_id validation and path validation to produce
    a fully scoped, safe path.

    Args:
        user_id: The user ID to scope the path to.
        path: The path within the user's scope.

    Returns:
        The full scoped path: "users/{user_id}/{path}"

    Raises:
        UserScopeError: If validation fails.
    """
    validated_user_id = validate_user_id(user_id)
    validated_path = validate_path(path)

    return f"users/{validated_user_id}/{validated_path}"


def scope_key(user_id: str | None, key: str) -> str:
    """Generate a user-scoped key for storage.

    This is an alias for validate_user_path with clearer semantics
    for key-value storage contexts.

    Args:
        user_id: The user ID to scope the key to.
        key: The key within the user's scope.

    Returns:
        The full scoped key: "users/{user_id}/{key}"

    Raises:
        UserScopeError: If validation fails.
    """
    return validate_user_path(user_id, key)


def get_user_prefix(user_id: str | None) -> str:
    """Get the storage prefix for a user.

    Args:
        user_id: The user ID.

    Returns:
        The user's storage prefix: "users/{user_id}/"

    Raises:
        UserScopeError: If user_id is invalid.
    """
    validated_user_id = validate_user_id(user_id)
    return f"users/{validated_user_id}/"


def strip_user_prefix(user_id: str | None, full_path: str) -> str:
    """Remove the user prefix from a full path.

    Useful for returning paths relative to the user's storage root.

    Args:
        user_id: The user ID.
        full_path: The full path including user prefix.

    Returns:
        The path relative to the user's storage root.

    Raises:
        UserScopeError: If the path doesn't belong to the user.
    """
    prefix = get_user_prefix(user_id)

    if not full_path.startswith(prefix):
        raise UserScopeError(f"Path does not belong to user {user_id}: {full_path}")

    return full_path[len(prefix) :]


def is_path_in_user_scope(user_id: str | None, full_path: str) -> bool:
    """Check if a path is within a user's scope.

    Args:
        user_id: The user ID.
        full_path: The full path to check.

    Returns:
        True if the path is within the user's scope, False otherwise.
    """
    try:
        prefix = get_user_prefix(user_id)
        return full_path.startswith(prefix)
    except UserScopeError:
        return False

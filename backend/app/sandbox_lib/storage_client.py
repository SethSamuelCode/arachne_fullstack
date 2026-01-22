"""Storage client for sandbox containers.

This module provides a simple interface for sandbox containers to interact with
user-scoped storage via the storage proxy. It's designed to be bundled with
the sandbox Docker image.

Usage:
    from sandbox_lib.storage_client import StorageClient

    # Client auto-configures from environment variables
    client = StorageClient()

    # Upload a file
    client.put("data/output.csv", csv_content, content_type="text/csv")

    # Download a file
    content = client.get("data/input.txt")

    # List files
    files = client.list(prefix="data/")

    # Delete a file
    client.delete("data/temp.txt")

Environment variables (automatically set by the sandbox spawner):
    STORAGE_PROXY_URL: Base URL of the storage proxy
    STORAGE_TOKEN: JWT token for authentication
"""

import os
from typing import Any


class StorageClientError(Exception):
    """Base exception for storage client errors."""

    pass


class StorageNotFoundError(StorageClientError):
    """Raised when a requested object is not found."""

    pass


class StorageAuthError(StorageClientError):
    """Raised when authentication fails."""

    pass


class StorageClient:
    """Client for interacting with user-scoped storage via the proxy.

    Attributes:
        base_url: The base URL of the storage proxy.
        token: The JWT token for authentication.
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
    ):
        """Initialize the storage client.

        Args:
            base_url: Override the storage proxy URL (default: from env).
            token: Override the auth token (default: from env).

        Raises:
            StorageClientError: If required environment variables are missing.
        """
        self.base_url = base_url or os.environ.get("STORAGE_PROXY_URL")
        self.token = token or os.environ.get("STORAGE_TOKEN")

        if not self.base_url:
            raise StorageClientError(
                "STORAGE_PROXY_URL environment variable is required"
            )
        if not self.token:
            raise StorageClientError(
                "STORAGE_TOKEN environment variable is required"
            )

        # Remove trailing slash for consistent URL building
        self.base_url = self.base_url.rstrip("/")

    @property
    def _headers(self) -> dict[str, str]:
        """Get the authentication headers."""
        return {"Authorization": f"Bearer {self.token}"}

    def _handle_response(self, response: Any, path: str) -> Any:
        """Handle HTTP response and raise appropriate errors.

        Args:
            response: The HTTP response object.
            path: The path being accessed (for error messages).

        Returns:
            The response object if successful.

        Raises:
            StorageNotFoundError: If the object was not found (404).
            StorageAuthError: If authentication failed (401/403).
            StorageClientError: For other HTTP errors.
        """
        if response.status_code == 404:
            raise StorageNotFoundError(f"Object not found: {path}")
        if response.status_code in (401, 403):
            raise StorageAuthError("Authentication failed or token expired")
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise StorageClientError(
                f"Storage error ({response.status_code}): {detail}"
            )
        return response

    def get(self, path: str) -> bytes:
        """Download an object from storage.

        Args:
            path: The path to the object (relative to user's scope).

        Returns:
            The object content as bytes.

        Raises:
            StorageNotFoundError: If the object doesn't exist.
            StorageAuthError: If authentication fails.
            StorageClientError: For other errors.
        """
        import requests

        url = f"{self.base_url}/objects/{path.lstrip('/')}"
        response = requests.get(url, headers=self._headers, timeout=300)
        self._handle_response(response, path)
        return response.content

    def get_text(self, path: str, encoding: str = "utf-8") -> str:
        """Download an object and decode as text.

        Args:
            path: The path to the object.
            encoding: The text encoding (default: utf-8).

        Returns:
            The object content as a string.
        """
        return self.get(path).decode(encoding)

    def put(
        self,
        path: str,
        content: bytes | str,
        content_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        """Upload an object to storage.

        Args:
            path: The path for the object (relative to user's scope).
            content: The content to upload (bytes or string).
            content_type: The MIME type of the content.

        Returns:
            Dict with upload details (key, size, content_type).

        Raises:
            StorageAuthError: If authentication fails.
            StorageClientError: For other errors.
        """
        import requests

        url = f"{self.base_url}/objects/{path.lstrip('/')}"

        # Convert string to bytes if needed
        if isinstance(content, str):
            content = content.encode("utf-8")

        headers = {**self._headers, "Content-Type": content_type}
        response = requests.put(url, data=content, headers=headers, timeout=300)
        self._handle_response(response, path)
        return response.json()

    def delete(self, path: str) -> bool:
        """Delete an object from storage.

        Args:
            path: The path to the object.

        Returns:
            True if deleted successfully.

        Raises:
            StorageNotFoundError: If the object doesn't exist.
            StorageAuthError: If authentication fails.
            StorageClientError: For other errors.
        """
        import requests

        url = f"{self.base_url}/objects/{path.lstrip('/')}"
        response = requests.delete(url, headers=self._headers, timeout=60)
        self._handle_response(response, path)
        return response.json().get("deleted", True)

    def list(self, prefix: str = "") -> list[dict[str, Any]]:
        """List objects in storage.

        Args:
            prefix: Optional prefix to filter objects.

        Returns:
            List of objects with metadata (key, size, last_modified, content_type).

        Raises:
            StorageAuthError: If authentication fails.
            StorageClientError: For other errors.
        """
        import requests

        url = f"{self.base_url}/objects"
        params = {"prefix": prefix} if prefix else {}
        response = requests.get(
            url, headers=self._headers, params=params, timeout=60
        )
        self._handle_response(response, "list")
        return response.json().get("objects", [])

    def exists(self, path: str) -> bool:
        """Check if an object exists.

        Args:
            path: The path to check.

        Returns:
            True if the object exists, False otherwise.
        """
        try:
            # Use list with exact prefix to check existence
            objects = self.list(prefix=path)
            return any(obj.get("key") == path for obj in objects)
        except StorageClientError:
            return False


# Convenience function for quick access
def get_storage_client() -> StorageClient:
    """Get a storage client configured from environment variables.

    Returns:
        A configured StorageClient instance.
    """
    return StorageClient()

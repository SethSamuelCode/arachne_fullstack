"""Sandbox helper library.

This package provides utilities for sandbox containers to interact with
the main application's services (storage, etc.) in a secure manner.

The storage client uses a short-lived JWT token to access user-scoped
storage via a proxy, preventing direct access to S3 credentials.
"""

from app.sandbox_lib.storage_client import (
    StorageAuthError,
    StorageClient,
    StorageClientError,
    StorageNotFoundError,
    get_storage_client,
)

__all__ = [
    "StorageAuthError",
    "StorageClient",
    "StorageClientError",
    "StorageNotFoundError",
    "get_storage_client",
]

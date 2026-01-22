"""Tests for storage proxy router.

Tests security, user isolation, and streaming functionality
of the storage proxy for sandbox containers.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.api.routes.v1.storage_proxy import (
    create_sandbox_token,
    verify_sandbox_token,
)
from app.core.user_scope import (
    UserScopeError,
    get_user_prefix,
    is_path_in_user_scope,
    scope_key,
    validate_path,
)


class TestSandboxTokenGeneration:
    """Tests for sandbox token generation and verification."""

    def test_create_sandbox_token_returns_token_and_expiry(self):
        """Creating a sandbox token returns both token and expiration."""
        user_id = str(uuid4())
        token, expires_at = create_sandbox_token(user_id)

        assert isinstance(token, str)
        assert len(token) > 0
        assert isinstance(expires_at, datetime)
        assert expires_at > datetime.now(UTC)

    def test_verify_sandbox_token_returns_user_id(self):
        """Verifying a valid token returns the user_id."""
        user_id = str(uuid4())
        token, _ = create_sandbox_token(user_id)

        result = verify_sandbox_token(token)

        assert result == user_id

    def test_verify_sandbox_token_rejects_expired_token(self):
        """Expired tokens are rejected."""
        import jwt

        from app.core.config import settings

        user_id = str(uuid4())
        # Create an already-expired token
        expired_payload = {
            "sub": user_id,
            "type": "sandbox",
            "exp": datetime.now(UTC) - timedelta(minutes=1),
            "iat": datetime.now(UTC) - timedelta(minutes=11),
        }
        expired_token = jwt.encode(
            expired_payload,
            settings.JWT_PRIVATE_KEY,
            algorithm="EdDSA",
        )

        result = verify_sandbox_token(expired_token)

        assert result is None

    def test_verify_sandbox_token_rejects_wrong_type(self):
        """Tokens with wrong type are rejected."""
        import jwt

        from app.core.config import settings

        user_id = str(uuid4())
        # Create a token with wrong type
        wrong_type_payload = {
            "sub": user_id,
            "type": "access",  # Wrong type
            "exp": datetime.now(UTC) + timedelta(minutes=10),
            "iat": datetime.now(UTC),
        }
        wrong_type_token = jwt.encode(
            wrong_type_payload,
            settings.JWT_PRIVATE_KEY,
            algorithm="EdDSA",
        )

        result = verify_sandbox_token(wrong_type_token)

        assert result is None

    def test_verify_sandbox_token_rejects_invalid_signature(self):
        """Tokens with invalid signatures are rejected."""
        import jwt
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
        )

        user_id = str(uuid4())
        # Create a token with a different key
        different_key = Ed25519PrivateKey.generate()
        different_key_pem = different_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        ).decode("utf-8")

        invalid_payload = {
            "sub": user_id,
            "type": "sandbox",
            "exp": datetime.now(UTC) + timedelta(minutes=10),
            "iat": datetime.now(UTC),
        }
        invalid_token = jwt.encode(
            invalid_payload,
            different_key_pem,
            algorithm="EdDSA",
        )

        result = verify_sandbox_token(invalid_token)

        assert result is None


class TestUserScopeValidation:
    """Tests for user scope path validation."""

    def test_validate_path_allows_valid_paths(self):
        """Valid paths are allowed."""
        # These should all pass without raising
        validate_path("file.txt")
        validate_path("subdir/file.txt")
        validate_path("a/b/c/file.txt")

    def test_validate_path_blocks_parent_traversal(self):
        """Parent directory traversal is blocked."""
        with pytest.raises(UserScopeError, match="traversal"):
            validate_path("../other/file.txt")

        with pytest.raises(UserScopeError, match="traversal"):
            validate_path("subdir/../../file.txt")

    def test_validate_path_blocks_encoded_traversal(self):
        """URL-encoded traversal attempts are blocked."""
        with pytest.raises(UserScopeError, match="traversal"):
            validate_path("%2e%2e/file.txt")

        with pytest.raises(UserScopeError, match="traversal"):
            validate_path("%2f../file.txt")

    def test_validate_path_blocks_null_bytes(self):
        """Null byte injection is blocked."""
        # Note: null bytes may be filtered by Python string handling
        # Test with URL-encoded null byte instead
        with pytest.raises(UserScopeError):
            validate_path("%00file.txt")

    def test_scope_key_adds_prefix(self):
        """scope_key correctly adds user prefix."""
        user_id = "user123"

        result = scope_key(user_id, "file.txt")
        assert result == "users/user123/file.txt"

        result = scope_key(user_id, "subdir/file.txt")
        assert result == "users/user123/subdir/file.txt"

    def test_scope_key_rejects_traversal(self):
        """scope_key rejects path traversal attempts."""
        user_id = "user123"

        with pytest.raises(UserScopeError, match="traversal"):
            scope_key(user_id, "../other/file.txt")

    def test_get_user_prefix(self):
        """get_user_prefix returns correct format."""
        assert get_user_prefix("user123") == "users/user123/"
        assert get_user_prefix("abc-def") == "users/abc-def/"

    def test_is_path_in_user_scope(self):
        """is_path_in_user_scope correctly checks ownership."""
        user_id = "user123"

        assert is_path_in_user_scope(user_id, "users/user123/file.txt") is True
        assert is_path_in_user_scope(user_id, "users/user123/sub/file.txt") is True
        assert is_path_in_user_scope(user_id, "users/user456/file.txt") is False
        assert is_path_in_user_scope(user_id, "file.txt") is False
        assert is_path_in_user_scope(user_id, "other/user123/file.txt") is False


class TestStorageProxyEndpoints:
    """Tests for storage proxy HTTP endpoints."""

    @pytest.mark.anyio
    async def test_list_objects_filters_by_user(self):
        """List endpoint only returns objects in user's scope (unit test)."""
        from app.core.user_scope import get_user_prefix, is_path_in_user_scope

        user_id = str(uuid4())
        user_prefix = get_user_prefix(user_id)

        # Simulate the filtering logic from the endpoint
        all_objects = [
            {"key": f"{user_prefix}file1.txt", "size": 100},
            {"key": f"{user_prefix}subdir/file2.txt", "size": 200},
            {"key": "users/other_user/file.txt", "size": 50},
        ]

        # This is what the endpoint does to filter
        filtered = [
            obj for obj in all_objects
            if is_path_in_user_scope(user_id, obj["key"])
        ]

        assert len(filtered) == 2
        keys = [obj["key"] for obj in filtered]
        assert f"{user_prefix}file1.txt" in keys
        assert f"{user_prefix}subdir/file2.txt" in keys
        assert "users/other_user/file.txt" not in keys

    def test_path_traversal_blocked_by_scope_key(self):
        """Path traversal is blocked by scope_key validation."""
        from app.core.user_scope import UserScopeError, scope_key

        user_id = str(uuid4())

        # These should all raise UserScopeError
        with pytest.raises(UserScopeError):
            scope_key(user_id, "../../../etc/passwd")

        with pytest.raises(UserScopeError):
            scope_key(user_id, "..\\..\\etc\\passwd")

        with pytest.raises(UserScopeError):
            scope_key(user_id, "foo/../../../etc/passwd")

    def test_url_encoded_traversal_blocked(self):
        """URL-encoded path traversal is blocked."""
        from app.core.user_scope import UserScopeError, scope_key

        user_id = str(uuid4())

        # URL-encoded traversal attempts
        with pytest.raises(UserScopeError):
            scope_key(user_id, "%2e%2e/etc/passwd")

        with pytest.raises(UserScopeError):
            scope_key(user_id, "foo/%2e%2e/%2e%2e/etc/passwd")

    @pytest.mark.anyio
    async def test_endpoints_reject_missing_token(self, client):
        """Endpoints reject requests without auth token."""
        # List - should return 401
        response = await client.get("/api/v1/storage/objects")
        assert response.status_code == 401

        # Download - should return 401
        response = await client.get("/api/v1/storage/objects/file.txt")
        assert response.status_code == 401

        # Delete - should return 401 or 403 (some frameworks return 403 for unauthorized writes)
        response = await client.delete("/api/v1/storage/objects/file.txt")
        assert response.status_code in (401, 403)

    @pytest.mark.anyio
    async def test_endpoints_reject_invalid_token(self, client):
        """Endpoints reject requests with invalid token."""
        response = await client.get(
            "/api/v1/storage/objects",
            headers={"Authorization": "Bearer invalid_token_here"},
        )
        assert response.status_code == 401
        assert "Invalid or expired" in response.json()["detail"]


class TestStorageClientLibrary:
    """Tests for the sandbox storage client library."""

    def test_storage_client_requires_env_vars(self):
        """StorageClient requires environment variables."""
        from app.sandbox_lib.storage_client import StorageClient, StorageClientError

        # Without any env vars set, should raise
        with pytest.raises(StorageClientError, match="STORAGE_PROXY_URL"):
            StorageClient()

    def test_storage_client_accepts_explicit_params(self):
        """StorageClient accepts explicit URL and token."""
        from app.sandbox_lib.storage_client import StorageClient

        client = StorageClient(
            base_url="http://localhost:8000/api/v1/storage",
            token="test_token",
        )

        assert client.base_url == "http://localhost:8000/api/v1/storage"
        assert client.token == "test_token"

    def test_storage_client_strips_trailing_slash(self):
        """StorageClient strips trailing slash from base URL."""
        from app.sandbox_lib.storage_client import StorageClient

        client = StorageClient(
            base_url="http://localhost:8000/api/v1/storage/",
            token="test_token",
        )

        assert client.base_url == "http://localhost:8000/api/v1/storage"

"""Tests for file storage routes.

Tests the file upload, download, list, and batch presigned URL endpoints.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


class MockUser:
    """Mock user for testing."""

    def __init__(self, user_id=None):
        self.id = user_id or uuid4()
        self.email = "test@example.com"
        self.is_active = True


@pytest.fixture
def mock_user() -> MockUser:
    """Create a mock user."""
    return MockUser()


@pytest.fixture
def mock_s3_service() -> MagicMock:
    """Create a mock S3 service."""
    service = MagicMock()
    service.list_objs_with_metadata = MagicMock(return_value=[])
    service.list_objs = MagicMock(return_value=[])
    service.generate_presigned_post = MagicMock(
        return_value={
            "url": "https://s3.example.com/bucket",
            "fields": {"key": "test-key", "policy": "test-policy"},
        }
    )
    service.generate_presigned_posts_batch = MagicMock(
        return_value=[
            {
                "url": "https://s3.example.com/bucket",
                "fields": {"key": "file1.txt", "policy": "test-policy"},
            },
            {
                "url": "https://s3.example.com/bucket",
                "fields": {"key": "folder/file2.txt", "policy": "test-policy"},
            },
        ]
    )
    service.generate_presigned_download_url = MagicMock(
        return_value="https://s3.example.com/bucket/file?signed=true"
    )
    service.delete_obj = MagicMock(return_value=None)
    service.delete_objects_by_prefix = MagicMock(return_value=0)
    return service


@pytest.fixture
def patch_s3_service(mock_s3_service: MagicMock):
    """Patch the get_s3_service function to return our mock."""
    with patch(
        "app.api.routes.v1.files.get_s3_service", return_value=mock_s3_service
    ):
        yield mock_s3_service


@pytest.fixture
async def authenticated_client(
    mock_user: MockUser,
    patch_s3_service: MagicMock,
    mock_db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncClient:
    """Client with mocked auth and S3 service."""
    from app.api.deps import get_current_user, get_db_session
    from app.core import config

    # Set internal API key for bypassing CSRF
    test_api_key = "test-internal-api-key"
    monkeypatch.setattr(config.settings, "INTERNAL_API_KEY", test_api_key)

    # Override get_current_user directly to return mock user
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Internal-API-Key": test_api_key},
    ) as client:
        yield client

    # Clean up overrides
    app.dependency_overrides.clear()


class TestFileList:
    """Tests for file listing endpoint."""

    @pytest.mark.anyio
    async def test_list_files_empty(
        self,
        authenticated_client: AsyncClient,
        patch_s3_service: MagicMock,
    ):
        """Test listing files when no files exist."""
        response = await authenticated_client.get("/api/v1/files")

        assert response.status_code == 200
        data = response.json()
        assert data["files"] == []
        assert data["total"] == 0

    @pytest.mark.anyio
    async def test_list_files_with_content(
        self,
        authenticated_client: AsyncClient,
        patch_s3_service: MagicMock,
        mock_user: MockUser,
    ):
        """Test listing files with existing files."""
        from datetime import UTC, datetime

        patch_s3_service.list_objs_with_metadata.return_value = [
            {
                "key": f"users/{mock_user.id}/test.txt",
                "size": 1024,
                "last_modified": datetime.now(UTC),
                "content_type": "text/plain",
            },
            {
                "key": f"users/{mock_user.id}/folder/nested.txt",
                "size": 2048,
                "last_modified": datetime.now(UTC),
                "content_type": "text/plain",
            },
        ]

        response = await authenticated_client.get("/api/v1/files")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["files"]) == 2
        # Keys should have user prefix stripped
        assert data["files"][0]["key"] == "test.txt"
        assert data["files"][1]["key"] == "folder/nested.txt"


class TestPresignedUpload:
    """Tests for presigned upload URL endpoint."""

    @pytest.mark.anyio
    async def test_get_presigned_upload_url(
        self,
        authenticated_client: AsyncClient,
        patch_s3_service: MagicMock,
    ):
        """Test getting a presigned upload URL."""
        response = await authenticated_client.post(
            "/api/v1/files/presign",
            json={"filename": "test.txt", "content_type": "text/plain"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "url" in data
        assert "fields" in data
        assert data["key"] == "test.txt"
        patch_s3_service.generate_presigned_post.assert_called_once()

    @pytest.mark.anyio
    async def test_get_presigned_upload_url_with_path(
        self,
        authenticated_client: AsyncClient,
        patch_s3_service: MagicMock,
        mock_user: MockUser,
    ):
        """Test getting a presigned upload URL with nested path."""
        response = await authenticated_client.post(
            "/api/v1/files/presign",
            json={"filename": "folder/subfolder/test.txt"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["key"] == "folder/subfolder/test.txt"

        # Verify the full path was passed to S3
        call_args = patch_s3_service.generate_presigned_post.call_args
        expected_key = f"users/{mock_user.id}/folder/subfolder/test.txt"
        assert call_args[0][0] == expected_key


class TestBatchPresignedUpload:
    """Tests for batch presigned upload URL endpoint."""

    @pytest.mark.anyio
    async def test_get_batch_presigned_urls(
        self,
        authenticated_client: AsyncClient,
        patch_s3_service: MagicMock,
    ):
        """Test getting batch presigned upload URLs."""
        response = await authenticated_client.post(
            "/api/v1/files/presign/batch",
            json={
                "files": [
                    {"filename": "file1.txt", "content_type": "text/plain"},
                    {"filename": "folder/file2.txt", "content_type": "text/plain"},
                ]
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["uploads"]) == 2
        assert data["uploads"][0]["filename"] == "file1.txt"
        assert data["uploads"][1]["filename"] == "folder/file2.txt"
        patch_s3_service.generate_presigned_posts_batch.assert_called_once()

    @pytest.mark.anyio
    async def test_get_batch_presigned_urls_empty_list(
        self,
        authenticated_client: AsyncClient,
        patch_s3_service: MagicMock,
    ):
        """Test batch presigned with empty file list."""
        patch_s3_service.generate_presigned_posts_batch.return_value = []

        response = await authenticated_client.post(
            "/api/v1/files/presign/batch",
            json={"files": []},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["uploads"] == []

    @pytest.mark.anyio
    async def test_get_batch_presigned_urls_preserves_paths(
        self,
        authenticated_client: AsyncClient,
        patch_s3_service: MagicMock,
        mock_user: MockUser,
    ):
        """Test that batch presigned URLs preserve folder paths."""
        # Set up mock to return the same number of responses
        patch_s3_service.generate_presigned_posts_batch.return_value = [
            {"url": "https://s3.example.com", "fields": {"key": "k1"}},
            {"url": "https://s3.example.com", "fields": {"key": "k2"}},
            {"url": "https://s3.example.com", "fields": {"key": "k3"}},
        ]

        files = [
            {"filename": "root.txt"},
            {"filename": "folder/nested.txt"},
            {"filename": "folder/sub/deep.txt"},
        ]

        response = await authenticated_client.post(
            "/api/v1/files/presign/batch",
            json={"files": files},
        )

        assert response.status_code == 200
        data = response.json()

        # Verify all paths are preserved
        filenames = [u["filename"] for u in data["uploads"]]
        assert "root.txt" in filenames
        assert "folder/nested.txt" in filenames
        assert "folder/sub/deep.txt" in filenames

        # Verify S3 service was called with full user-scoped paths
        call_args = patch_s3_service.generate_presigned_posts_batch.call_args
        object_names = call_args[0][0]
        assert f"users/{mock_user.id}/root.txt" in object_names
        assert f"users/{mock_user.id}/folder/nested.txt" in object_names
        assert f"users/{mock_user.id}/folder/sub/deep.txt" in object_names


class TestPathSanitization:
    """Tests for path traversal prevention."""

    @pytest.mark.anyio
    async def test_path_traversal_blocked_single(
        self,
        authenticated_client: AsyncClient,
        patch_s3_service: MagicMock,
        mock_user: MockUser,
    ):
        """Test that path traversal is blocked in single upload."""
        response = await authenticated_client.post(
            "/api/v1/files/presign",
            json={"filename": "../../../etc/passwd"},
        )

        assert response.status_code == 200
        # The path should be sanitized
        call_args = patch_s3_service.generate_presigned_post.call_args
        sanitized_key = call_args[0][0]
        assert ".." not in sanitized_key
        assert "etc/passwd" in sanitized_key

    @pytest.mark.anyio
    async def test_path_traversal_blocked_batch(
        self,
        authenticated_client: AsyncClient,
        patch_s3_service: MagicMock,
        mock_user: MockUser,
    ):
        """Test that path traversal is blocked in batch upload."""
        patch_s3_service.generate_presigned_posts_batch.return_value = [
            {"url": "https://s3.example.com", "fields": {"key": "k1"}},
        ]

        response = await authenticated_client.post(
            "/api/v1/files/presign/batch",
            json={"files": [{"filename": "../../secret.txt"}]},
        )

        assert response.status_code == 200
        call_args = patch_s3_service.generate_presigned_posts_batch.call_args
        object_names = call_args[0][0]
        # All paths should be sanitized
        for path in object_names:
            assert ".." not in path


class TestFolderDelete:
    """Tests for folder deletion endpoint."""

    @pytest.mark.anyio
    async def test_delete_folder_success(
        self,
        authenticated_client: AsyncClient,
        patch_s3_service: MagicMock,
        mock_user: MockUser,
    ):
        """Test successful folder deletion."""
        folder_path = "my-folder"
        user_prefix = f"users/{mock_user.id}/{folder_path}/"

        # Mock list_objs to return files in the folder
        patch_s3_service.list_objs.return_value = [
            f"{user_prefix}file1.txt",
            f"{user_prefix}file2.txt",
            f"{user_prefix}subfolder/file3.txt",
        ]
        patch_s3_service.delete_objects_by_prefix.return_value = 3

        response = await authenticated_client.delete(f"/api/v1/files/folder/{folder_path}")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["prefix"] == folder_path
        assert data["deleted_count"] == 3

        # Verify S3 service was called with correct prefix
        patch_s3_service.delete_objects_by_prefix.assert_called_once_with(user_prefix)

    @pytest.mark.anyio
    async def test_delete_folder_not_found(
        self,
        authenticated_client: AsyncClient,
        patch_s3_service: MagicMock,
        mock_user: MockUser,
    ):
        """Test folder deletion when folder doesn't exist."""
        folder_path = "nonexistent-folder"

        # Mock list_objs to return empty list
        patch_s3_service.list_objs.return_value = []

        response = await authenticated_client.delete(f"/api/v1/files/folder/{folder_path}")

        assert response.status_code == 404
        data = response.json()
        assert "Folder not found or empty" in data["detail"]

    @pytest.mark.anyio
    async def test_delete_nested_folder(
        self,
        authenticated_client: AsyncClient,
        patch_s3_service: MagicMock,
        mock_user: MockUser,
    ):
        """Test deletion of a nested folder."""
        folder_path = "parent/child/grandchild"
        user_prefix = f"users/{mock_user.id}/{folder_path}/"

        patch_s3_service.list_objs.return_value = [
            f"{user_prefix}file.txt",
        ]
        patch_s3_service.delete_objects_by_prefix.return_value = 1

        response = await authenticated_client.delete(f"/api/v1/files/folder/{folder_path}")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["prefix"] == folder_path
        assert data["deleted_count"] == 1

    @pytest.mark.anyio
    async def test_delete_folder_trailing_slash_handled(
        self,
        authenticated_client: AsyncClient,
        patch_s3_service: MagicMock,
        mock_user: MockUser,
    ):
        """Test that trailing slashes in folder path are handled correctly."""
        folder_path = "my-folder/"  # With trailing slash
        expected_prefix = f"users/{mock_user.id}/my-folder/"

        patch_s3_service.list_objs.return_value = [
            f"{expected_prefix}file.txt",
        ]
        patch_s3_service.delete_objects_by_prefix.return_value = 1

        response = await authenticated_client.delete(f"/api/v1/files/folder/{folder_path}")

        assert response.status_code == 200
        # Should still work correctly
        patch_s3_service.delete_objects_by_prefix.assert_called_once_with(expected_prefix)

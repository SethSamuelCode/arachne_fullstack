"""File storage routes for S3 operations.

Provides endpoints for:
- Listing user's files
- Getting presigned upload URLs for direct S3 uploads
- Getting presigned download URLs
- Deleting files

All file operations are scoped to the authenticated user's storage prefix.
"""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser
from app.schemas.file import (
    BatchPresignedUploadItem,
    BatchPresignedUploadRequest,
    BatchPresignedUploadResponse,
    FileContentResponse,
    FileDeleteResponse,
    FileInfo,
    FileListResponse,
    FolderDeleteResponse,
    PresignedDownloadResponse,
    PresignedUploadRequest,
    PresignedUploadResponse,
)
from app.services.s3 import get_s3_service

router = APIRouter()


def _get_user_prefix(user_id: str) -> str:
    """Get the S3 prefix for a user's files."""
    return f"users/{user_id}/"


def _get_user_path(user_id: str, filename: str) -> str:
    """Get the full S3 key for a user's file."""
    # Sanitize filename to prevent path traversal
    safe_filename = filename.replace("..", "").lstrip("/")
    return f"{_get_user_prefix(user_id)}{safe_filename}"


def _strip_user_prefix(user_id: str, key: str) -> str:
    """Strip the user prefix from an S3 key to get relative path."""
    prefix = _get_user_prefix(user_id)
    if key.startswith(prefix):
        return key[len(prefix) :]
    return key


@router.get("", response_model=FileListResponse)
async def list_files(current_user: CurrentUser) -> FileListResponse:
    """List all files in the user's storage.

    Returns a list of files with their metadata (key, size, last_modified).
    """
    s3 = get_s3_service()
    user_prefix = _get_user_prefix(str(current_user.id))

    try:
        # Get all objects and filter by user prefix
        all_objects = s3.list_objs_with_metadata(prefix=user_prefix)

        files = [
            FileInfo(
                key=_strip_user_prefix(str(current_user.id), obj["key"]),
                size=obj["size"],
                last_modified=obj["last_modified"],
                content_type=obj.get("content_type"),
            )
            for obj in all_objects
        ]

        return FileListResponse(files=files, total=len(files))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list files: {e!s}",
        ) from e


@router.post("/presign", response_model=PresignedUploadResponse)
async def get_presigned_upload_url(
    request: PresignedUploadRequest,
    current_user: CurrentUser,
) -> PresignedUploadResponse:
    """Get a presigned POST URL for direct file upload to S3.

    The client should POST the file directly to the returned URL with the
    provided fields included as form data.
    """
    s3 = get_s3_service()
    full_key = _get_user_path(str(current_user.id), request.filename)

    try:
        presigned = s3.generate_presigned_post(full_key, expiration=3600)
        return PresignedUploadResponse(
            url=presigned["url"],
            fields=presigned["fields"],
            key=request.filename,  # Return relative key to user
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate upload URL: {e!s}",
        ) from e


@router.post("/presign/batch", response_model=BatchPresignedUploadResponse)
async def get_batch_presigned_upload_urls(
    request: BatchPresignedUploadRequest,
    current_user: CurrentUser,
) -> BatchPresignedUploadResponse:
    """Get presigned POST URLs for multiple files for direct upload to S3.

    Useful for folder uploads where many files need presigned URLs at once.
    The client should POST each file directly to its returned URL with the
    provided fields included as form data.
    """
    s3 = get_s3_service()

    try:
        # Build full paths and generate presigned URLs
        file_items = []
        object_names = []
        for file_item in request.files:
            full_key = _get_user_path(str(current_user.id), file_item.filename)
            object_names.append(full_key)
            file_items.append(file_item)

        presigned_results = s3.generate_presigned_posts_batch(object_names, expiration=3600)

        uploads = [
            BatchPresignedUploadItem(
                filename=file_items[i].filename,
                url=presigned["url"],
                fields=presigned["fields"],
                key=file_items[i].filename,  # Return relative key to user
            )
            for i, presigned in enumerate(presigned_results)
        ]

        return BatchPresignedUploadResponse(uploads=uploads, total=len(uploads))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate batch upload URLs: {e!s}",
        ) from e


# Max file size for preview (1MB)
MAX_PREVIEW_SIZE = 1024 * 1024

# Text file extensions that can be previewed
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
    ".xml", ".html", ".css", ".csv", ".log", ".sh", ".bash", ".env", ".toml",
    ".ini", ".cfg", ".rst", ".sql", ".r", ".rb", ".go", ".java", ".c", ".cpp",
    ".h", ".hpp", ".rs", ".swift", ".kt", ".scala", ".php", ".pl", ".lua",
}


@router.get("/{file_key:path}/content", response_model=FileContentResponse)
async def get_file_content(
    file_key: str,
    current_user: CurrentUser,
) -> FileContentResponse:
    """Get file content for preview.

    Returns the file content as text if it's a text file, or base64 encoded if binary.
    Large files (>1MB) will be truncated.
    """
    import base64
    from pathlib import Path

    s3 = get_s3_service()
    full_key = _get_user_path(str(current_user.id), file_key)

    try:
        # Verify file exists and get metadata
        objects = s3.list_objs_with_metadata(prefix=full_key)
        file_obj = next((obj for obj in objects if obj["key"] == full_key), None)

        if not file_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File not found: {file_key}",
            )

        file_size = file_obj["size"]
        content_type = file_obj.get("content_type")

        # Determine if file is text based on extension
        ext = Path(file_key).suffix.lower()
        is_text = ext in TEXT_EXTENSIONS or (content_type and content_type.startswith("text/"))

        # Download file content
        content_bytes = s3.download_obj(full_key)
        is_truncated = False

        if len(content_bytes) > MAX_PREVIEW_SIZE:
            content_bytes = content_bytes[:MAX_PREVIEW_SIZE]
            is_truncated = True

        if is_text:
            try:
                content = content_bytes.decode("utf-8")
                is_binary = False
            except UnicodeDecodeError:
                content = base64.b64encode(content_bytes).decode("ascii")
                is_binary = True
        else:
            content = base64.b64encode(content_bytes).decode("ascii")
            is_binary = True

        return FileContentResponse(
            key=file_key,
            content=content,
            content_type=content_type,
            size=file_size,
            is_binary=is_binary,
            is_truncated=is_truncated,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get file content: {e!s}",
        ) from e


@router.get("/{file_key:path}/download-url", response_model=PresignedDownloadResponse)
async def get_download_url(
    file_key: str,
    current_user: CurrentUser,
) -> PresignedDownloadResponse:
    """Get a presigned URL for downloading a file.

    The file_key should be the relative path within the user's storage.
    """
    s3 = get_s3_service()
    full_key = _get_user_path(str(current_user.id), file_key)

    try:
        # Verify file exists
        objects = s3.list_objs()
        if full_key not in objects:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File not found: {file_key}",
            )

        url = s3.generate_presigned_download_url(full_key, expiration=3600)
        return PresignedDownloadResponse(url=url, expires_in=3600)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate download URL: {e!s}",
        ) from e


@router.delete("/folder/{folder_path:path}", response_model=FolderDeleteResponse)
async def delete_folder(
    folder_path: str,
    current_user: CurrentUser,
) -> FolderDeleteResponse:
    """Delete a folder and all its contents from the user's storage.

    The folder_path should be the relative path within the user's storage.
    All files with keys starting with this prefix will be deleted.
    """
    s3 = get_s3_service()
    # Ensure the prefix ends with / to only match folder contents
    folder_prefix = folder_path.rstrip("/") + "/"
    full_prefix = _get_user_path(str(current_user.id), folder_prefix)

    try:
        # Check if folder has any contents
        objects = s3.list_objs(prefix=full_prefix)
        if not objects:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Folder not found or empty: {folder_path}",
            )

        deleted_count = s3.delete_objects_by_prefix(full_prefix)
        return FolderDeleteResponse(
            success=True,
            prefix=folder_path,
            deleted_count=deleted_count,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete folder: {e!s}",
        ) from e


@router.delete("/{file_key:path}", response_model=FileDeleteResponse)
async def delete_file(
    file_key: str,
    current_user: CurrentUser,
) -> FileDeleteResponse:
    """Delete a file from the user's storage.

    The file_key should be the relative path within the user's storage.
    """
    s3 = get_s3_service()
    full_key = _get_user_path(str(current_user.id), file_key)

    try:
        # Verify file exists before deleting
        objects = s3.list_objs()
        if full_key not in objects:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File not found: {file_key}",
            )

        s3.delete_obj(full_key)
        return FileDeleteResponse(success=True, key=file_key)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete file: {e!s}",
        ) from e

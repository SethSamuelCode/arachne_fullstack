"""File storage routes for S3 operations.

Provides endpoints for:
- Listing user's files
- Getting presigned upload URLs for direct S3 uploads
- Getting presigned download URLs
- Deleting files
- Renaming files and folders (with SSE progress for folders)

All file operations are scoped to the authenticated user's storage prefix.
"""

import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, HTTPException, Request, status
from sse_starlette.sse import EventSourceResponse

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
    FolderRenameProgress,
    MoveRequest,
    MoveResponse,
    PresignedDownloadResponse,
    PresignedUploadRequest,
    PresignedUploadResponse,
    RenameRequest,
    RenameResponse,
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


# Max file size for preview (200MB)
MAX_PREVIEW_SIZE = 200 * 1024 * 1024

# Text file extensions that can be previewed
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
    ".xml", ".html", ".css", ".csv", ".log", ".sh", ".bash", ".env", ".toml",
    ".ini", ".cfg", ".rst", ".sql", ".r", ".rb", ".go", ".java", ".c", ".cpp",
    ".h", ".hpp", ".rs", ".swift", ".kt", ".scala", ".php", ".pl", ".lua",
}

# Magic bytes signatures for common file types
# Format: (magic_bytes, offset, mime_type)
MAGIC_SIGNATURES: list[tuple[bytes, int, str]] = [
    # Images
    (b"\x89PNG\r\n\x1a\n", 0, "image/png"),
    (b"\xff\xd8\xff", 0, "image/jpeg"),
    (b"GIF87a", 0, "image/gif"),
    (b"GIF89a", 0, "image/gif"),
    (b"RIFF", 0, "image/webp"),  # WebP starts with RIFF, need to check WEBP at offset 8
    (b"BM", 0, "image/bmp"),
    (b"\x00\x00\x01\x00", 0, "image/x-icon"),  # ICO
    (b"\x00\x00\x02\x00", 0, "image/x-icon"),  # CUR (cursor, similar to ICO)
    # SVG detection handled separately (XML-based)
    # PDF
    (b"%PDF", 0, "application/pdf"),
    # Archives
    (b"PK\x03\x04", 0, "application/zip"),
    (b"\x1f\x8b", 0, "application/gzip"),
    (b"Rar!\x1a\x07", 0, "application/x-rar-compressed"),
    # Audio/Video
    (b"ID3", 0, "audio/mpeg"),
    (b"\xff\xfb", 0, "audio/mpeg"),
    (b"\xff\xfa", 0, "audio/mpeg"),
    (b"OggS", 0, "audio/ogg"),
    (b"fLaC", 0, "audio/flac"),
    (b"\x00\x00\x00\x1cftyp", 0, "video/mp4"),
    (b"\x00\x00\x00\x20ftyp", 0, "video/mp4"),
    # Documents
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", 0, "application/msword"),  # DOC/XLS/PPT
]


def detect_mime_type_from_magic(content_bytes: bytes) -> str | None:
    """Detect MIME type from file magic bytes.

    Args:
        content_bytes: The file content bytes.

    Returns:
        The detected MIME type or None if not detected.
    """
    if len(content_bytes) < 12:
        return None

    # Check for WebP specifically (RIFF....WEBP)
    if content_bytes[:4] == b"RIFF" and content_bytes[8:12] == b"WEBP":
        return "image/webp"

    # Check for SVG (XML-based)
    # Look for <?xml or <svg in first 1000 bytes
    header = content_bytes[:1000]
    try:
        header_str = header.decode("utf-8", errors="ignore").lower()
        if "<svg" in header_str or ("<?xml" in header_str and "svg" in header_str):
            return "image/svg+xml"
    except Exception:
        pass

    # Check magic signatures
    for magic, offset, mime_type in MAGIC_SIGNATURES:
        if content_bytes[offset:offset + len(magic)] == magic:
            return mime_type

    return None


@router.post("/rename", response_model=RenameResponse)
async def rename_file(
    request: RenameRequest,
    current_user: CurrentUser,
) -> RenameResponse:
    """Rename a single file in the user's storage.

    This performs a copy-then-delete operation since S3 doesn't support rename.
    For folders, use the /rename/folder endpoint which streams progress via SSE.
    """
    s3 = get_s3_service()
    old_full_key = _get_user_path(str(current_user.id), request.old_path)
    new_full_key = _get_user_path(str(current_user.id), request.new_path)

    try:
        # Verify source file exists
        objects = s3.list_objs()
        if old_full_key not in objects:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File not found: {request.old_path}",
            )

        # Check destination doesn't exist
        if new_full_key in objects:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"File already exists: {request.new_path}",
            )

        # Copy to new location then delete original
        s3.copy_file(old_full_key, new_full_key)
        s3.delete_obj(old_full_key)

        return RenameResponse(
            success=True,
            old_path=request.old_path,
            new_path=request.new_path,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to rename file: {e!s}",
        ) from e


def _is_path_nested(parent: str, child: str) -> bool:
    """Check if child path is nested under parent path.

    Used to prevent moving a folder into itself or its descendants.
    """
    # Normalize paths: remove trailing slashes and ensure consistent format
    parent_normalized = parent.rstrip("/")
    child_normalized = child.rstrip("/")

    # Check if child starts with parent path followed by /
    return child_normalized.startswith(parent_normalized + "/") or child_normalized == parent_normalized


@router.post("/move", response_model=MoveResponse)
async def move_file_or_folder(
    request: MoveRequest,
    current_user: CurrentUser,
) -> MoveResponse:
    """Move a file or folder to a new location.

    Supports moving:
    - Single files to a new path/name
    - Entire folders (all contents moved recursively)

    Validates:
    - Source must exist
    - Destination must not exist
    - Cannot move a folder into itself or its descendants
    """
    s3 = get_s3_service()
    user_id = str(current_user.id)

    source_path = request.source_path.rstrip("/")
    dest_path = request.destination_path.rstrip("/")

    # Check if trying to move folder into itself
    if _is_path_nested(source_path, dest_path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot move a folder into itself or its subdirectories",
        )

    source_full_key = _get_user_path(user_id, source_path)
    dest_full_key = _get_user_path(user_id, dest_path)

    try:
        # Check if source is a file (exact match)
        all_objects = s3.list_objs()
        is_file = source_full_key in all_objects

        if is_file:
            # Moving a single file
            if dest_full_key in all_objects:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Destination already exists: {dest_path}",
                )

            s3.copy_file(source_full_key, dest_full_key)
            s3.delete_obj(source_full_key)

            return MoveResponse(
                success=True,
                source_path=source_path,
                destination_path=dest_path,
                is_folder=False,
                files_moved=1,
            )

        # Check if source is a folder (prefix match)
        source_prefix = source_full_key + "/"
        source_files = [k for k in all_objects if k.startswith(source_prefix)]

        if not source_files:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File or folder not found: {source_path}",
            )

        # Moving a folder
        dest_prefix = dest_full_key + "/"

        # Check if destination folder already has contents
        dest_files = [k for k in all_objects if k.startswith(dest_prefix)]
        if dest_files:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Destination folder already exists: {dest_path}",
            )

        # Move all files in the folder
        files_moved = 0
        for source_key in source_files:
            relative_path = source_key[len(source_prefix):]
            dest_key = dest_prefix + relative_path

            s3.copy_file(source_key, dest_key)
            s3.delete_obj(source_key)
            files_moved += 1

        return MoveResponse(
            success=True,
            source_path=source_path,
            destination_path=dest_path,
            is_folder=True,
            files_moved=files_moved,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to move: {e!s}",
        ) from e


@router.get("/rename/folder")
async def rename_folder_sse(
    request: Request,
    old_path: str,
    new_path: str,
    current_user: CurrentUser,
) -> EventSourceResponse:
    """Rename a folder and all its contents, streaming progress via SSE.

    This moves all files under the old_path prefix to new_path.
    Progress events are streamed as SSE with types: 'progress', 'complete', 'error'.
    """
    s3 = get_s3_service()
    user_id = str(current_user.id)

    # Ensure paths end with / for folder operations
    old_prefix = old_path.rstrip("/") + "/"
    new_prefix = new_path.rstrip("/") + "/"
    old_full_prefix = _get_user_path(user_id, old_prefix)
    new_full_prefix = _get_user_path(user_id, new_prefix)

    async def event_generator() -> AsyncGenerator[dict, None]:
        try:
            # List all files in the source folder
            source_files = s3.list_objs(prefix=old_full_prefix)

            if not source_files:
                yield {
                    "event": "error",
                    "data": json.dumps(
                        FolderRenameProgress(
                            event="error",
                            total=0,
                            completed=0,
                            old_path=old_path,
                            new_path=new_path,
                            error=f"Folder not found or empty: {old_path}",
                        ).model_dump()
                    ),
                }
                return

            total = len(source_files)
            completed = 0

            # Check if any destination files already exist
            dest_files = s3.list_objs(prefix=new_full_prefix)
            if dest_files:
                yield {
                    "event": "error",
                    "data": json.dumps(
                        FolderRenameProgress(
                            event="error",
                            total=total,
                            completed=0,
                            old_path=old_path,
                            new_path=new_path,
                            error=f"Destination folder already exists: {new_path}",
                        ).model_dump()
                    ),
                }
                return

            # Move each file
            for source_key in source_files:
                # Check if client disconnected
                if await request.is_disconnected():
                    return

                # Calculate new key
                relative_path = source_key[len(old_full_prefix) :]
                dest_key = new_full_prefix + relative_path
                current_file = _strip_user_prefix(user_id, source_key)

                # Send progress event
                yield {
                    "event": "progress",
                    "data": json.dumps(
                        FolderRenameProgress(
                            event="progress",
                            total=total,
                            completed=completed,
                            current_file=current_file,
                            old_path=old_path,
                            new_path=new_path,
                        ).model_dump()
                    ),
                }

                # Copy and delete
                s3.copy_file(source_key, dest_key)
                s3.delete_obj(source_key)
                completed += 1

            # Send completion event
            yield {
                "event": "complete",
                "data": json.dumps(
                    FolderRenameProgress(
                        event="complete",
                        total=total,
                        completed=completed,
                        old_path=old_path,
                        new_path=new_path,
                    ).model_dump()
                ),
            }

        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps(
                    FolderRenameProgress(
                        event="error",
                        total=0,
                        completed=0,
                        old_path=old_path,
                        new_path=new_path,
                        error=str(e),
                    ).model_dump()
                ),
            }

    return EventSourceResponse(event_generator())


@router.get("/{file_key:path}/content", response_model=FileContentResponse)
async def get_file_content(
    file_key: str,
    current_user: CurrentUser,
) -> FileContentResponse:
    """Get file content for preview.

    Returns the file content as text if it's a text file, or base64 encoded if binary.
    Large files (>200MB) will be truncated.
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
        stored_content_type = file_obj.get("content_type")

        # Download file content
        content_bytes = s3.download_obj(full_key)
        is_truncated = False

        if len(content_bytes) > MAX_PREVIEW_SIZE:
            content_bytes = content_bytes[:MAX_PREVIEW_SIZE]
            is_truncated = True

        # Detect content type from magic bytes first, then fall back to stored/extension
        detected_content_type = detect_mime_type_from_magic(content_bytes)
        content_type = detected_content_type or stored_content_type

        # Determine if file is text based on extension or content type
        ext = Path(file_key).suffix.lower()
        is_text = ext in TEXT_EXTENSIONS or (content_type and content_type.startswith("text/"))

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

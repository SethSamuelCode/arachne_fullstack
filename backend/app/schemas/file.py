"""File storage schemas for S3 operations."""

from datetime import datetime

from pydantic import Field

from app.schemas.base import BaseSchema


class FileInfo(BaseSchema):
    """Information about a file in S3 storage."""

    key: str = Field(description="File key/path (relative to user's storage)")
    size: int = Field(description="File size in bytes")
    last_modified: datetime = Field(description="Last modification timestamp")
    content_type: str | None = Field(default=None, description="MIME type of the file")


class FileListResponse(BaseSchema):
    """Response containing list of files."""

    files: list[FileInfo] = Field(default_factory=list, description="List of files")
    total: int = Field(description="Total number of files")


class PresignedUploadRequest(BaseSchema):
    """Request for generating a presigned upload URL."""

    filename: str = Field(description="Name of the file to upload")
    content_type: str | None = Field(default=None, description="MIME type of the file (optional)")


class PresignedUploadResponse(BaseSchema):
    """Response containing presigned POST URL and fields for direct S3 upload."""

    url: str = Field(description="URL to POST the file to")
    fields: dict[str, str] = Field(description="Form fields to include in the POST request")
    key: str = Field(description="The S3 key where the file will be stored")


class PresignedDownloadResponse(BaseSchema):
    """Response containing presigned download URL."""

    url: str = Field(description="Presigned URL for downloading the file")
    expires_in: int = Field(default=3600, description="URL expiration time in seconds")


class FileDeleteResponse(BaseSchema):
    """Response for file deletion."""

    success: bool = Field(default=True, description="Whether deletion was successful")
    key: str = Field(description="Key of the deleted file")


class FolderDeleteResponse(BaseSchema):
    """Response for folder deletion."""

    success: bool = Field(default=True, description="Whether deletion was successful")
    prefix: str = Field(description="Prefix/path of the deleted folder")
    deleted_count: int = Field(description="Number of files deleted")


class BatchFileItem(BaseSchema):
    """Single file item in a batch upload request."""

    filename: str = Field(description="Name/path of the file to upload")
    content_type: str | None = Field(default=None, description="MIME type of the file (optional)")


class BatchPresignedUploadRequest(BaseSchema):
    """Request for generating presigned upload URLs for multiple files."""

    files: list[BatchFileItem] = Field(description="List of files to get presigned URLs for")


class BatchPresignedUploadItem(BaseSchema):
    """Single presigned upload URL result."""

    filename: str = Field(description="Original filename from request")
    url: str = Field(description="URL to POST the file to")
    fields: dict[str, str] = Field(description="Form fields to include in the POST request")
    key: str = Field(description="The S3 key where the file will be stored")


class BatchPresignedUploadResponse(BaseSchema):
    """Response containing presigned POST URLs for multiple files."""

    uploads: list[BatchPresignedUploadItem] = Field(description="List of presigned upload URLs")
    total: int = Field(description="Total number of presigned URLs generated")


class FileContentResponse(BaseSchema):
    """Response containing file content for preview."""

    key: str = Field(description="File key/path")
    content: str = Field(description="File content (text or base64 encoded)")
    content_type: str | None = Field(default=None, description="MIME type of the file")
    size: int = Field(description="File size in bytes")
    is_binary: bool = Field(default=False, description="Whether content is base64 encoded binary")
    is_truncated: bool = Field(
        default=False, description="Whether content was truncated due to size"
    )


class RenameRequest(BaseSchema):
    """Request to rename a file or folder."""

    old_path: str = Field(description="Current path of the file or folder")
    new_path: str = Field(description="New path for the file or folder")


class RenameResponse(BaseSchema):
    """Response for a successful rename operation."""

    success: bool = Field(default=True, description="Whether rename was successful")
    old_path: str = Field(description="Original path")
    new_path: str = Field(description="New path")


class FolderRenameProgress(BaseSchema):
    """Progress event for folder rename operation (SSE)."""

    event: str = Field(description="Event type: 'progress', 'complete', or 'error'")
    total: int = Field(default=0, description="Total number of files to move")
    completed: int = Field(default=0, description="Number of files moved so far")
    current_file: str | None = Field(default=None, description="Currently processing file")
    old_path: str = Field(description="Original folder path")
    new_path: str = Field(description="New folder path")
    error: str | None = Field(default=None, description="Error message if event is 'error'")


class MoveRequest(BaseSchema):
    """Request to move a file or folder to a new location."""

    source_path: str = Field(description="Current path of the file or folder to move")
    destination_path: str = Field(
        description="New path (including new name) for the file or folder"
    )


class MoveResponse(BaseSchema):
    """Response for a successful move operation."""

    success: bool = Field(default=True, description="Whether move was successful")
    source_path: str = Field(description="Original path")
    destination_path: str = Field(description="New path")
    is_folder: bool = Field(default=False, description="Whether a folder was moved")
    files_moved: int = Field(default=1, description="Number of files moved (>1 for folders)")

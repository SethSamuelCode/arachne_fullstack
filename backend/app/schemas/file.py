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
    content_type: str | None = Field(
        default=None, description="MIME type of the file (optional)"
    )


class PresignedUploadResponse(BaseSchema):
    """Response containing presigned POST URL and fields for direct S3 upload."""

    url: str = Field(description="URL to POST the file to")
    fields: dict[str, str] = Field(
        description="Form fields to include in the POST request"
    )
    key: str = Field(description="The S3 key where the file will be stored")


class PresignedDownloadResponse(BaseSchema):
    """Response containing presigned download URL."""

    url: str = Field(description="Presigned URL for downloading the file")
    expires_in: int = Field(default=3600, description="URL expiration time in seconds")


class FileDeleteResponse(BaseSchema):
    """Response for file deletion."""

    success: bool = Field(default=True, description="Whether deletion was successful")
    key: str = Field(description="Key of the deleted file")

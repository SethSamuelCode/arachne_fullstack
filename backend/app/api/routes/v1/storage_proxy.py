"""Storage proxy router for sandbox container S3 access.

This router provides a secure proxy for ephemeral sandbox containers to access
user-scoped S3 storage without having direct access to S3 credentials.

Security model:
- Sandbox containers receive a short-lived JWT with user_id claim
- All operations are scoped to users/{user_id}/ prefix
- Path traversal attacks are blocked at multiple layers
- Streaming is used for large file transfers to avoid memory issues

Endpoints:
- GET /storage/objects - List objects in user's scope
- GET /storage/objects/{path:path} - Download an object (streaming)
- PUT /storage/objects/{path:path} - Upload an object (streaming)
- DELETE /storage/objects/{path:path} - Delete an object
- POST /storage/token - Generate sandbox token (internal use)
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import CurrentUser
from app.core.config import settings
from app.core.user_scope import (
    UserScopeError,
    get_user_prefix,
    is_path_in_user_scope,
    scope_key,
)
from app.services.s3 import get_s3_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Sandbox token configuration
_SANDBOX_TOKEN_TYPE = "sandbox"
_SANDBOX_TOKEN_EXPIRE_MINUTES = 10
_ALGORITHM = "EdDSA"


class SandboxTokenRequest(BaseModel):
    """Request to generate a sandbox access token."""

    pass  # Currently no additional parameters needed


class SandboxTokenResponse(BaseModel):
    """Response containing sandbox access token."""

    token: str
    expires_at: datetime
    user_prefix: str


class ObjectInfo(BaseModel):
    """Information about a storage object."""

    key: str
    size: int
    last_modified: datetime
    content_type: str | None = None


class ObjectListResponse(BaseModel):
    """Response containing list of objects."""

    objects: list[ObjectInfo]
    prefix: str


class DeleteResponse(BaseModel):
    """Response for delete operation."""

    deleted: bool
    key: str


def _get_signing_key() -> str:
    """Get the Ed25519 private key for signing JWTs."""
    if not settings.JWT_PRIVATE_KEY:
        raise ValueError("JWT_PRIVATE_KEY is required")
    return settings.JWT_PRIVATE_KEY


def _get_verification_key() -> str:
    """Get the Ed25519 public key for verifying JWTs."""
    if not settings.JWT_PUBLIC_KEY:
        raise ValueError("JWT_PUBLIC_KEY is required")
    return settings.JWT_PUBLIC_KEY


def create_sandbox_token(user_id: str) -> tuple[str, datetime]:
    """Create a short-lived JWT for sandbox container access.

    Args:
        user_id: The user ID to scope access to.

    Returns:
        Tuple of (token, expiration_datetime).
    """
    expire = datetime.now(UTC) + timedelta(minutes=_SANDBOX_TOKEN_EXPIRE_MINUTES)

    payload = {
        "sub": user_id,
        "type": _SANDBOX_TOKEN_TYPE,
        "exp": expire,
        "iat": datetime.now(UTC),
    }

    token = jwt.encode(payload, _get_signing_key(), algorithm=_ALGORITHM)
    return token, expire


def verify_sandbox_token(token: str) -> str | None:
    """Verify a sandbox token and return the user_id.

    Args:
        token: The JWT token to verify.

    Returns:
        The user_id if valid, None otherwise.
    """
    try:
        payload = jwt.decode(
            token,
            _get_verification_key(),
            algorithms=[_ALGORITHM],
        )

        # Verify token type
        if payload.get("type") != _SANDBOX_TOKEN_TYPE:
            logger.warning("Invalid token type: expected sandbox token")
            return None

        user_id = payload.get("sub")
        if not user_id:
            logger.warning("Sandbox token missing user_id claim")
            return None

        return user_id

    except jwt.ExpiredSignatureError:
        logger.debug("Sandbox token expired")
        return None
    except jwt.InvalidSignatureError:
        logger.warning("Sandbox token has invalid signature")
        return None
    except jwt.PyJWTError as e:
        logger.warning(f"Sandbox token verification failed: {e}")
        return None


async def get_sandbox_user_id(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """Dependency to extract and verify user_id from sandbox token.

    Args:
        authorization: Bearer token from Authorization header.

    Returns:
        The verified user_id.

    Raises:
        HTTPException: If token is missing, invalid, or expired.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format",
        )

    token = authorization[7:]  # Strip "Bearer " prefix
    user_id = verify_sandbox_token(token)

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired sandbox token",
        )

    return user_id


SandboxUserId = Annotated[str, Depends(get_sandbox_user_id)]


# =============================================================================
# Internal endpoint for token generation (called by server, not sandbox)
# =============================================================================


@router.post("/token", response_model=SandboxTokenResponse)
async def generate_sandbox_token(
    current_user: CurrentUser,
) -> SandboxTokenResponse:
    """Generate a short-lived sandbox access token for the current user.

    This endpoint is called by the server before spawning a sandbox container.
    The token is passed to the container as an environment variable.

    Requires regular authentication (not sandbox token).
    """
    user_id = str(current_user.id)
    token, expires_at = create_sandbox_token(user_id)

    return SandboxTokenResponse(
        token=token,
        expires_at=expires_at,
        user_prefix=get_user_prefix(user_id),
    )


# =============================================================================
# Sandbox-accessible endpoints (require sandbox token)
# =============================================================================


@router.get("/objects", response_model=ObjectListResponse)
async def list_objects(
    user_id: SandboxUserId,
    prefix: str = "",
) -> ObjectListResponse:
    """List objects in the user's storage scope.

    Args:
        user_id: User ID from sandbox token (injected).
        prefix: Optional prefix within user's scope to filter by.

    Returns:
        List of objects with metadata.
    """
    s3 = get_s3_service()
    user_prefix = get_user_prefix(user_id)

    # Combine user prefix with requested prefix
    full_prefix = f"{user_prefix}{prefix.lstrip('/')}" if prefix else user_prefix

    try:
        all_objects = s3.list_objs_with_metadata(prefix=full_prefix)

        # Strip user prefix from keys for cleaner response
        objects = [
            ObjectInfo(
                key=obj["key"][len(user_prefix) :] if obj["key"].startswith(user_prefix) else obj["key"],
                size=obj["size"],
                last_modified=obj["last_modified"],
                content_type=obj.get("content_type"),
            )
            for obj in all_objects
            # Extra safety: only include objects that are in user's scope
            if is_path_in_user_scope(obj["key"], user_id)
        ]

        return ObjectListResponse(objects=objects, prefix=prefix)

    except Exception as e:
        logger.exception("Error listing objects")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing objects: {e}",
        ) from e


@router.get("/objects/{path:path}")
async def download_object(
    path: str,
    user_id: SandboxUserId,
) -> StreamingResponse:
    """Download an object from user's storage (streaming).

    Args:
        path: Path to the object relative to user's scope.
        user_id: User ID from sandbox token (injected).

    Returns:
        StreamingResponse with file content.
    """
    # Validate and scope the path
    try:
        full_key = scope_key(user_id, path)
    except (ValueError, UserScopeError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    s3 = get_s3_service()

    try:
        # Try to get the object - will raise if not found
        try:
            obj_data = s3.download_obj(full_key)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Object not found: {path}",
            )

        # Determine content type from file extension
        import mimetypes
        content_type, _ = mimetypes.guess_type(path)
        if not content_type:
            content_type = "application/octet-stream"

        # Return as streaming response
        def stream_generator():
            """Generator that yields the object data in chunks."""
            chunk_size = 1024 * 1024  # 1MB chunks
            for i in range(0, len(obj_data), chunk_size):
                yield obj_data[i:i + chunk_size]

        return StreamingResponse(
            stream_generator(),
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{path.split("/")[-1]}"',
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error downloading object")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error downloading object: {e}",
        ) from e


@router.put("/objects/{path:path}")
async def upload_object(
    path: str,
    request: Request,
    user_id: SandboxUserId,
    content_type: Annotated[str, Header()] = "application/octet-stream",
) -> dict[str, Any]:
    """Upload an object to user's storage (streaming).

    Args:
        path: Path to store the object relative to user's scope.
        request: Request object to stream body from.
        user_id: User ID from sandbox token (injected).
        content_type: Content type of the uploaded file.

    Returns:
        Upload confirmation with key and size.
    """
    # Validate and scope the path
    try:
        full_key = scope_key(user_id, path)
    except (ValueError, UserScopeError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    s3 = get_s3_service()

    try:
        # Read entire body (for now, could be improved with multipart upload for large files)
        body = await request.body()
        size = len(body)

        # Upload to S3 using the existing interface
        s3.upload_obj(body, full_key)

        logger.info(f"Uploaded object: {full_key} ({size} bytes)")

        return {
            "key": path,
            "full_key": full_key,
            "size": size,
            "content_type": content_type,
        }

    except Exception as e:
        logger.exception("Error uploading object")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading object: {e}",
        ) from e


@router.delete("/objects/{path:path}", response_model=DeleteResponse)
async def delete_object(
    path: str,
    user_id: SandboxUserId,
) -> DeleteResponse:
    """Delete an object from user's storage.

    Args:
        path: Path to the object relative to user's scope.
        user_id: User ID from sandbox token (injected).

    Returns:
        Delete confirmation.
    """
    # Validate and scope the path
    try:
        full_key = scope_key(user_id, path)
    except (ValueError, UserScopeError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    s3 = get_s3_service()

    try:
        # Check if object exists by trying to list it
        objects = s3.list_objs(prefix=full_key)
        if full_key not in objects:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Object not found: {path}",
            )

        # Delete the object
        s3.delete_obj(full_key)

        logger.info(f"Deleted object: {full_key}")

        return DeleteResponse(deleted=True, key=path)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error deleting object")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting object: {e}",
        ) from e

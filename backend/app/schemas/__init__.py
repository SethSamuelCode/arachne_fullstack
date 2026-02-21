"""Pydantic schemas."""
# ruff: noqa: I001, RUF022 - Imports structured for Jinja2 template conditionals

from app.schemas.token import Token, TokenPayload
from app.schemas.user import UserCreate, UserRead, UserRegister, UserUpdate

from app.schemas.session import SessionRead, SessionListResponse, LogoutAllResponse

from app.schemas.item import ItemCreate, ItemRead, ItemUpdate

from app.schemas.conversation import (
    ConversationCreate,
    ConversationRead,
    ConversationUpdate,
    MessageCreate,
    MessageRead,
    ToolCallRead,
)

from app.schemas.webhook import (
    WebhookCreate,
    WebhookRead,
    WebhookUpdate,
    WebhookDeliveryRead,
    WebhookListResponse,
    WebhookDeliveryListResponse,
    WebhookTestResponse,
)

from app.schemas.models import ModelInfo, ModalitySupport, DEFAULT_GEMINI_MODEL
from app.schemas.web_search import (
    WebSearchRequest,
    WebSearchResult,
    WebSearchResponse,
    FetchUrlRequest,
    FetchUrlResponse,
)
from app.schemas.assistant import Deps
from app.schemas.spawn_agent_deps import SpawnAgentDeps

from app.schemas.file import (
    FileInfo,
    FileListResponse,
    PresignedUploadRequest,
    PresignedUploadResponse,
    PresignedDownloadResponse,
    FileDeleteResponse,
)

from app.schemas.attachment import (
    ALLOWED_IMAGE_MIME_TYPES,
    MAX_TOTAL_ATTACHMENT_SIZE_BYTES,
    AttachmentCreate,
    AttachmentRead,
    AttachmentInMessage,
    validate_attachments_total_size,
)

__all__ = [
    "UserCreate",
    "UserRead",
    "UserUpdate",
    "UserRegister",
    "Token",
    "TokenPayload",
    "SessionRead",
    "SessionListResponse",
    "LogoutAllResponse",
    "ItemCreate",
    "ItemRead",
    "ItemUpdate",
    "ConversationCreate",
    "ConversationRead",
    "ConversationUpdate",
    "MessageCreate",
    "MessageRead",
    "ToolCallRead",
    "WebhookCreate",
    "WebhookRead",
    "WebhookUpdate",
    "WebhookDeliveryRead",
    "WebhookListResponse",
    "WebhookDeliveryListResponse",
    "WebhookTestResponse",
    "ModelInfo",
    "ModalitySupport",
    "DEFAULT_GEMINI_MODEL",
    "WebSearchRequest",
    "WebSearchResult",
    "WebSearchResponse",
    "FetchUrlRequest",
    "FetchUrlResponse",
    "Deps",
    "SpawnAgentDeps",
    "FileInfo",
    "FileListResponse",
    "PresignedUploadRequest",
    "PresignedUploadResponse",
    "PresignedDownloadResponse",
    "FileDeleteResponse",
    "ALLOWED_IMAGE_MIME_TYPES",
    "MAX_TOTAL_ATTACHMENT_SIZE_BYTES",
    "AttachmentCreate",
    "AttachmentRead",
    "AttachmentInMessage",
    "validate_attachments_total_size",
]

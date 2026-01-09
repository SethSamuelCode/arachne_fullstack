"""Token schemas."""

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.schemas.user import UserRead


class Token(BaseModel):
    """OAuth2 token response with refresh token."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenWithUser(Token):
    """Token response that includes user data for login."""

    user: "UserRead"


class TokenPayload(BaseModel):
    """JWT token payload."""

    sub: str | None = None
    exp: int | None = None
    type: Literal["access", "refresh"] | None = None


class RefreshTokenRequest(BaseModel):
    """Request body for token refresh."""

    refresh_token: str

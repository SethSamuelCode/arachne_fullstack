"""Authentication routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import CurrentUser, SessionSvc, UserSvc
from app.core.exceptions import AuthenticationError
from app.core.rate_limit import limiter
from app.core.security import create_access_token, create_refresh_token
from app.schemas.token import RefreshTokenRequest, Token, TokenWithUser
from app.schemas.user import UserCreate, UserRead

router = APIRouter()


@router.post("/login", response_model=TokenWithUser)
@limiter.limit("5/minute")
async def login(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    user_service: UserSvc,
    session_service: SessionSvc,
):
    """OAuth2 compatible token login.

    Returns access token, refresh token, and user data.
    Raises domain exceptions handled by exception handlers.
    Rate limited to 5 attempts per minute to prevent brute-force attacks.
    """
    user = await user_service.authenticate(form_data.username, form_data.password)
    access_token = create_access_token(subject=str(user.id))
    refresh_token = create_refresh_token(subject=str(user.id))

    # Create session to track this login
    await session_service.create_session(
        user_id=user.id,
        refresh_token=refresh_token,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return TokenWithUser(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserRead.model_validate(user),
    )


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(
    user_in: UserCreate,
    user_service: UserSvc,
):
    """Register a new user.

    Raises AlreadyExistsError if email is already registered.
    """
    user = await user_service.register(user_in)
    return user


@router.post("/refresh", response_model=Token)
async def refresh_token(
    request: Request,
    body: RefreshTokenRequest,
    user_service: UserSvc,
    session_service: SessionSvc,
):
    """Get new access token using refresh token.

    Raises AuthenticationError if refresh token is invalid or expired.
    """

    # Validate refresh token against stored session
    session = await session_service.validate_refresh_token(body.refresh_token)
    if not session:
        raise AuthenticationError(message="Invalid or expired refresh token")

    user = await user_service.get_by_id(session.user_id)
    if not user.is_active:
        raise AuthenticationError(message="User account is disabled")

    access_token = create_access_token(subject=str(user.id))
    new_refresh_token = create_refresh_token(subject=str(user.id))

    # Invalidate old session and create new one
    await session_service.logout_by_refresh_token(body.refresh_token)
    await session_service.create_session(
        user_id=user.id,
        refresh_token=new_refresh_token,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return Token(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: RefreshTokenRequest,
    session_service: SessionSvc,
):
    """Logout and invalidate the current session.

    Invalidates the refresh token, preventing further token refresh.
    """
    await session_service.logout_by_refresh_token(body.refresh_token)


@router.get("/me", response_model=UserRead)
async def get_current_user_info(current_user: CurrentUser):
    """Get current authenticated user information."""
    return current_user

# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals
"""User management routes."""

from typing import Annotated

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi_pagination import Page
from fastapi_pagination.ext.sqlalchemy import paginate
from sqlalchemy import or_, select

from app.api.deps import (
    DBSession,
    RoleChecker,
    UserSvc,
    get_current_user,
)
from app.db.models.user import User, UserRole
from app.schemas.user import UserRead, UserUpdate

router = APIRouter()


@router.get("/me", response_model=UserRead)
async def read_current_user(
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Get current user.

    Returns the authenticated user's profile including their role.
    """
    return current_user


@router.patch("/me", response_model=UserRead)
async def update_current_user(
    user_in: UserUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    user_service: UserSvc,
):
    """Update current user.

    Users can update their own profile (email, full_name).
    Role changes require admin privileges.
    """
    # Prevent non-admin users from changing their own role
    if user_in.role is not None and not current_user.has_role(UserRole.ADMIN):
        user_in.role = None
    user = await user_service.update(current_user.id, user_in)
    return user


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_current_user(
    current_user: Annotated[User, Depends(get_current_user)],
    user_service: UserSvc,
):
    """Delete current user's account (soft delete).

    This will:
    - Deactivate the user account (soft delete)
    - Invalidate all active sessions
    - The user will be logged out immediately
    """
    await user_service.delete(current_user.id)


@router.get("", response_model=Page[UserRead])
async def read_users(
    db: DBSession,
    current_user: Annotated[User, Depends(RoleChecker(UserRole.ADMIN))],
    include_deleted: bool = Query(
        default=False,
        description="Include soft-deleted (inactive) users in results",
    ),
    search: str | None = Query(
        default=None,
        description="Search by email or full name (case-insensitive)",
        max_length=255,
    ),
    role: str | None = Query(
        default=None,
        description="Filter by role (admin, user)",
    ),
):
    """Get all users (admin only).

    Supports filtering by:
    - include_deleted: Show soft-deleted users (default: false)
    - search: Search by email or full name
    - role: Filter by user role
    """
    query = select(User)

    # Filter by active status (soft delete)
    if not include_deleted:
        query = query.where(User.is_active == True)  # noqa: E712

    # Search by email or full name
    if search:
        search_pattern = f"%{search}%"
        query = query.where(
            or_(
                User.email.ilike(search_pattern),
                User.full_name.ilike(search_pattern),
            )
        )

    # Filter by role
    if role:
        query = query.where(User.role == role)

    # Order by creation date (newest first)
    query = query.order_by(User.created_at.desc())

    return await paginate(db, query)


@router.get("/{user_id}", response_model=UserRead)
async def read_user(
    user_id: UUID,
    user_service: UserSvc,
    current_user: Annotated[User, Depends(RoleChecker(UserRole.ADMIN))],
):
    """Get user by ID (admin only).

    Raises NotFoundError if user does not exist.
    """
    user = await user_service.get_by_id(user_id)
    return user


@router.patch("/{user_id}", response_model=UserRead)
async def update_user_by_id(
    user_id: UUID,
    user_in: UserUpdate,
    user_service: UserSvc,
    current_user: Annotated[User, Depends(RoleChecker(UserRole.ADMIN))],
):
    """Update user by ID (admin only).

    Admins can update any user including their role.

    Raises NotFoundError if user does not exist.
    """
    user = await user_service.update(user_id, user_in)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_by_id(
    user_id: UUID,
    user_service: UserSvc,
    current_user: Annotated[User, Depends(RoleChecker(UserRole.ADMIN))],
):
    """Soft delete user by ID (admin only).

    This will deactivate the user account and invalidate all their sessions.
    The user can be restored using the restore endpoint.

    Raises NotFoundError if user does not exist.
    """
    await user_service.delete(user_id)


@router.post("/{user_id}/restore", response_model=UserRead)
async def restore_user_by_id(
    user_id: UUID,
    user_service: UserSvc,
    current_user: Annotated[User, Depends(RoleChecker(UserRole.ADMIN))],
):
    """Restore a soft-deleted user (admin only).

    Re-enables a previously deleted user account by setting is_active=True.

    Raises NotFoundError if user does not exist.
    """
    user = await user_service.restore(user_id)
    return user

"""Admin settings routes.

Provides endpoints for administrators to manage runtime application settings.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import RoleChecker, RuntimeSettingsSvc
from app.db.models.user import User, UserRole
from app.schemas.base import BaseSchema


class SettingsRead(BaseSchema):
    """Schema for reading runtime settings."""

    registration_enabled: bool


class SettingsUpdate(BaseSchema):
    """Schema for updating runtime settings."""

    registration_enabled: bool | None = None


router = APIRouter()


@router.get("", response_model=SettingsRead)
async def get_settings(
    settings_service: RuntimeSettingsSvc,
    current_user: Annotated[User, Depends(RoleChecker(UserRole.ADMIN))],
):
    """Get current runtime settings (admin only).

    Returns all configurable runtime settings and their current values.
    """
    return SettingsRead(
        registration_enabled=await settings_service.is_registration_enabled(),
    )


@router.patch("", response_model=SettingsRead)
async def update_settings(
    settings_in: SettingsUpdate,
    settings_service: RuntimeSettingsSvc,
    current_user: Annotated[User, Depends(RoleChecker(UserRole.ADMIN))],
):
    """Update runtime settings (admin only).

    Allows administrators to modify application behavior without restart.
    Only provided fields will be updated.
    """
    if settings_in.registration_enabled is not None:
        await settings_service.set_registration_enabled(settings_in.registration_enabled)

    return SettingsRead(
        registration_enabled=await settings_service.is_registration_enabled(),
    )

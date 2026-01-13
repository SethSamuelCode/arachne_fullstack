"""Runtime settings service.

Provides runtime-configurable settings stored in Redis.
These settings can be changed without restarting the application.
"""

from app.clients.redis import RedisClient

# Redis key prefix for runtime settings
SETTINGS_PREFIX = "arachne_fullstack:settings:"

# Setting keys
REGISTRATION_ENABLED_KEY = "registration_enabled"

# Default values
DEFAULTS: dict[str, str] = {
    REGISTRATION_ENABLED_KEY: "true",
}


class RuntimeSettingsService:
    """Service for managing runtime-configurable settings via Redis.

    USAGE:
        Use this service when you need to read or update application settings
        that can be changed at runtime without restart.

    ARGS:
        redis: RedisClient instance from dependency injection.

    AVAILABLE SETTINGS:
        - registration_enabled: "true" or "false" - Controls public user registration.
    """

    def __init__(self, redis: RedisClient) -> None:
        self.redis = redis

    def _key(self, setting: str) -> str:
        """Build full Redis key for a setting."""
        return f"{SETTINGS_PREFIX}{setting}"

    async def get(self, setting: str) -> str:
        """Get a runtime setting value.

        ARGS:
            setting: The setting key (e.g., "registration_enabled").

        RETURNS:
            The setting value as a string, or the default if not set.
        """
        value = await self.redis.get(self._key(setting))
        if value is None:
            return DEFAULTS.get(setting, "")
        return value

    async def set(self, setting: str, value: str) -> None:
        """Set a runtime setting value.

        ARGS:
            setting: The setting key (e.g., "registration_enabled").
            value: The value to set (stored as string).
        """
        await self.redis.set(self._key(setting), value)

    async def get_bool(self, setting: str) -> bool:
        """Get a runtime setting as a boolean.

        ARGS:
            setting: The setting key.

        RETURNS:
            True if value is "true" (case-insensitive), False otherwise.
        """
        value = await self.get(setting)
        return value.lower() == "true"

    async def set_bool(self, setting: str, value: bool) -> None:
        """Set a runtime setting as a boolean.

        ARGS:
            setting: The setting key.
            value: Boolean value to set.
        """
        await self.set(setting, "true" if value else "false")

    async def is_registration_enabled(self) -> bool:
        """Check if public registration is enabled.

        RETURNS:
            True if registration is enabled, False otherwise.
        """
        return await self.get_bool(REGISTRATION_ENABLED_KEY)

    async def set_registration_enabled(self, enabled: bool) -> None:
        """Enable or disable public registration.

        ARGS:
            enabled: Whether registration should be enabled.
        """
        await self.set_bool(REGISTRATION_ENABLED_KEY, enabled)

    async def get_all(self) -> dict[str, str]:
        """Get all runtime settings with their current values.

        RETURNS:
            Dictionary of setting keys to their current values.
        """
        result = {}
        for key in DEFAULTS:
            result[key] = await self.get(key)
        return result

"""Tests for core modules."""

from app.core.config import settings
from app.core.exceptions import (
    AlreadyExistsError,
    AppException,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    ValidationError,
)


class TestSettings:
    """Tests for settings configuration."""

    def test_project_name_is_set(self):
        """Test project name is configured."""
        assert settings.PROJECT_NAME == "arachne_fullstack"

    def test_api_v1_str_is_set(self):
        """Test API version string is set."""
        assert settings.API_V1_STR == "/api/v1"

    def test_debug_mode_default(self):
        """Test debug mode has default value."""
        assert isinstance(settings.DEBUG, bool)

    def test_cors_origins_is_list(self):
        """Test CORS origins is a list."""
        assert isinstance(settings.CORS_ORIGINS, list)

    def test_openalex_api_key_setting_exists(self):
        """Test OPENALEX_API_KEY setting is defined (optional, can be None)."""
        assert hasattr(settings, "OPENALEX_API_KEY")
        assert settings.OPENALEX_API_KEY is None or isinstance(
            settings.OPENALEX_API_KEY, str
        )

    def test_google_cache_ttl_default(self):
        """Test GOOGLE_CACHE_TTL_SECONDS has correct default value."""
        assert settings.GOOGLE_CACHE_TTL_SECONDS == 900  # 15 minutes

    def test_google_cache_ttl_minimum_validation(self):
        """Test GOOGLE_CACHE_TTL_SECONDS rejects values below 60 seconds."""
        import os

        import pytest
        from pydantic import ValidationError as PydanticValidationError

        from app.core.config import Settings

        # Test that value below 60 raises ValidationError
        with pytest.raises(PydanticValidationError) as exc_info:
            Settings(GOOGLE_CACHE_TTL_SECONDS=59, _env_file=None)  # type: ignore[call-arg]

        assert "GOOGLE_CACHE_TTL_SECONDS must be at least 60 seconds" in str(
            exc_info.value
        )

        # Test that exactly 60 is valid
        valid_settings = Settings(GOOGLE_CACHE_TTL_SECONDS=60, _env_file=None)  # type: ignore[call-arg]
        assert valid_settings.GOOGLE_CACHE_TTL_SECONDS == 60


class TestExceptions:
    """Tests for custom exceptions."""

    def test_app_exception(self):
        """Test AppException initialization."""
        error = AppException(message="Test error", code="TEST_ERROR")
        assert error.message == "Test error"
        assert error.code == "TEST_ERROR"
        assert str(error) == "Test error"

    def test_not_found_error(self):
        """Test NotFoundError."""
        error = NotFoundError(message="Item not found")
        assert error.status_code == 404
        assert error.code == "NOT_FOUND"

    def test_already_exists_error(self):
        """Test AlreadyExistsError."""
        error = AlreadyExistsError(message="Item already exists")
        assert error.status_code == 409
        assert error.code == "ALREADY_EXISTS"

    def test_authentication_error(self):
        """Test AuthenticationError."""
        error = AuthenticationError(message="Invalid credentials")
        assert error.status_code == 401
        assert error.code == "AUTHENTICATION_ERROR"

    def test_authorization_error(self):
        """Test AuthorizationError."""
        error = AuthorizationError(message="Not authorized")
        assert error.status_code == 403
        assert error.code == "AUTHORIZATION_ERROR"

    def test_validation_error(self):
        """Test ValidationError."""
        error = ValidationError(message="Invalid input")
        assert error.status_code == 422
        assert error.code == "VALIDATION_ERROR"


class TestCacheSetup:
    """Tests for cache setup."""

    def test_setup_cache_function_exists(self):
        """Test setup_cache function exists."""
        from app.core.cache import setup_cache

        assert setup_cache is not None
        assert callable(setup_cache)


class TestMiddleware:
    """Tests for middleware."""

    def test_request_id_middleware_exists(self):
        """Test request ID middleware is configured."""
        from app.core.middleware import RequestIDMiddleware

        assert RequestIDMiddleware is not None


class TestRateLimit:
    """Tests for rate limiting."""

    def test_limiter_exists(self):
        """Test rate limiter is configured."""
        from app.core.rate_limit import limiter

        assert limiter is not None


from unittest.mock import patch  # noqa: E402


class TestLogfireSetup:
    """Tests for Logfire setup."""

    @patch("app.core.logfire_setup.logfire")
    def test_setup_logfire_configures(self, mock_logfire):
        """Test setup_logfire calls configure."""
        from app.core.logfire_setup import setup_logfire

        setup_logfire()
        mock_logfire.configure.assert_called_once()

    @patch("app.core.logfire_setup.logfire")
    def test_instrument_app_instruments_fastapi(self, mock_logfire):
        """Test instrument_app instruments FastAPI."""
        from fastapi import FastAPI

        from app.core.logfire_setup import instrument_app

        app = FastAPI()
        instrument_app(app)
        mock_logfire.instrument_fastapi.assert_called()

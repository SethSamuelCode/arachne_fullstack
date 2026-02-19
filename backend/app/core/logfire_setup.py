"""Logfire observability configuration."""

import logfire

from app.core.config import settings


def setup_logfire() -> None:
    """Configure Logfire instrumentation.

    Only configures Logfire if LOGFIRE_TOKEN is provided.
    Otherwise, disables sending telemetry to avoid export errors.
    """
    if not settings.LOGFIRE_TOKEN:
        # Disable Logfire completely when no token is present
        logfire.configure(send_to_logfire=False)
        return

    logfire.configure(
        token=settings.LOGFIRE_TOKEN,
        service_name=settings.LOGFIRE_SERVICE_NAME,
        environment=settings.LOGFIRE_ENVIRONMENT,
        send_to_logfire=True,
    )


def instrument_app(app):
    """Instrument FastAPI app with Logfire."""
    logfire.instrument_fastapi(app)


def instrument_pydantic_ai():
    """Instrument PydanticAI for AI agent observability."""
    logfire.instrument_pydantic_ai()

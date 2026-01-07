"""Date and time utilities for agents."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import settings


def get_current_datetime() -> str:
    """Get the current date and time.

    Returns:
        A string with the current date and time.
    """
    timeZone = ZoneInfo(settings.TZ)
    now = datetime.now(tz=timeZone)
    return f"Current date: {now.strftime('%Y-%m-%d')}, Current time: {now.strftime('%H:%M:%S')}"

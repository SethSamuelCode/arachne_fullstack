"""SQLModel base model."""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlmodel import Field, SQLModel

# Alias SQLModel as Base for compatibility with existing code
Base = SQLModel

# Naming convention for database constraints and indexes
# This ensures consistent naming across all migrations
NAMING_CONVENTION = {
    "ix": "%(column_0_label)s_idx",
    "uq": "%(table_name)s_%(column_0_name)s_key",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}

# Apply naming convention to SQLModel metadata
SQLModel.metadata.naming_convention = NAMING_CONVENTION


class TimestampMixin(SQLModel):
    """Mixin for created_at and updated_at timestamps."""

    created_at: datetime = Field(
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={
            "server_default": func.now(),
            "nullable": False,
        },
    )
    updated_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={
            "onupdate": func.now(),
            "nullable": True,
        },
    )

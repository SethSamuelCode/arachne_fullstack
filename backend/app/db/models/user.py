"""User database model using SQLModel."""

import uuid
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Column, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, Relationship, SQLModel

from app.db.base import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.session import Session


class UserRole(str, Enum):
    """User role enumeration.

    Roles hierarchy (higher includes lower permissions):
    - ADMIN: Full system access, can manage users and settings
    - USER: Standard user access
    """

    ADMIN = "admin"
    USER = "user"


class User(TimestampMixin, SQLModel, table=True):
    """User model."""

    __tablename__ = "users"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True),
    )
    email: str = Field(
        sa_column=Column(String(255), unique=True, index=True, nullable=False),
    )
    hashed_password: str | None = Field(default=None, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    is_active: bool = Field(default=True)
    is_superuser: bool = Field(default=False)
    role: str = Field(default=UserRole.USER.value, max_length=50)
    default_system_prompt: str | None = Field(default=None, sa_column=Column(Text, nullable=True))

    # Relationship to sessions
    sessions: list["Session"] = Relationship(back_populates="user")

    @property
    def user_role(self) -> UserRole:
        """Get role as enum."""
        return UserRole(self.role)

    def has_role(self, required_role: UserRole) -> bool:
        """Check if user has the required role or higher.

        Admin role has access to everything.
        """
        if self.role == UserRole.ADMIN.value:
            return True
        return self.role == required_role.value

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"

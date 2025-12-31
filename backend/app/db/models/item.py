"""Item database model using SQLModel - example CRUD entity."""

import uuid

from sqlalchemy import Column, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel

from app.db.base import TimestampMixin


class Item(TimestampMixin, SQLModel, table=True):
    """Item model - example entity for demonstrating CRUD operations.

    This is a simple example model. You can use it as a template
    for creating your own models or remove it if not needed.
    """

    __tablename__ = "items"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True),
    )
    title: str = Field(
        sa_column=Column(String(255), nullable=False, index=True),
    )
    description: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    is_active: bool = Field(default=True)

    def __repr__(self) -> str:
        return f"<Item(id={self.id}, title={self.title})>"

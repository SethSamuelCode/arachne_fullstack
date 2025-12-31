"""Webhook database models using SQLModel (PostgreSQL async)."""

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, Relationship, SQLModel

from app.db.base import TimestampMixin


class WebhookEventType(str, Enum):
    """Webhook event types."""

    # User events
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"

    # Custom events (extend as needed)
    ITEM_CREATED = "item.created"
    ITEM_UPDATED = "item.updated"
    ITEM_DELETED = "item.deleted"


class Webhook(TimestampMixin, SQLModel, table=True):
    """Webhook subscription model."""

    __tablename__ = "webhooks"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True),
    )
    name: str = Field(max_length=255)
    url: str = Field(max_length=2048)
    secret: str = Field(max_length=255)
    events: list[str] = Field(sa_column=Column(ARRAY(String), nullable=False))
    is_active: bool = Field(default=True)
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    user_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True),
    )

    # Relationship to delivery logs
    deliveries: list["WebhookDelivery"] = Relationship(
        back_populates="webhook",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class WebhookDelivery(SQLModel, table=True):
    """Webhook delivery log model."""

    __tablename__ = "webhook_deliveries"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True),
    )
    webhook_id: uuid.UUID = Field(
        sa_column=Column(PG_UUID(as_uuid=True), ForeignKey("webhooks.id"), nullable=False),
    )
    event_type: str = Field(max_length=100)
    payload: str = Field(sa_column=Column(Text, nullable=False))
    response_status: int | None = Field(default=None)
    response_body: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    error_message: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    attempt_count: int = Field(default=1)
    success: bool = Field(default=False)
    created_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    delivered_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )

    # Relationship
    webhook: "Webhook" = Relationship(back_populates="deliveries")

"""Message attachment model for storing image references with chat messages."""

import uuid

from sqlalchemy import Column, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, Relationship, SQLModel

from app.db.base import TimestampMixin


class MessageAttachment(TimestampMixin, SQLModel, table=True):
    """MessageAttachment model - stores references to images attached to messages.

    Attributes:
        id: Unique attachment identifier
        message_id: The message this attachment belongs to
        s3_key: S3 object key for the file
        mime_type: MIME type of the attachment (e.g., image/png)
        filename: Original filename (optional)
        size_bytes: File size in bytes
    """

    __tablename__ = "message_attachments"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True),
    )
    message_id: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    s3_key: str = Field(sa_column=Column(Text, nullable=False))
    mime_type: str = Field(max_length=100)  # e.g., image/png, image/jpeg
    filename: str | None = Field(default=None, max_length=255)
    size_bytes: int = Field(default=0)

    # Relationships
    message: "Message" = Relationship(back_populates="attachments")  # noqa: F821

    def __repr__(self) -> str:
        return f"<MessageAttachment(id={self.id}, mime_type={self.mime_type})>"

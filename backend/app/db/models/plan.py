"""Plan and PlanTask models for AI assistant planning functionality.

Plans represent structured task lists that can be created, tracked, and
updated by AI agents. Each plan belongs to a specific user (user-scoped).
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Column, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, Relationship, SQLModel

from app.db.base import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.user import User


class Plan(TimestampMixin, SQLModel, table=True):
    """Plan model - represents a structured task list.

    Plans are user-scoped: each plan belongs to exactly one user and
    cannot be accessed by other users.

    Attributes:
        id: Unique plan identifier (auto-generated UUID)
        user_id: Owner of this plan (required, CASCADE delete)
        name: Human-readable plan name
        description: Detailed plan description
        notes: Additional notes or context
        is_completed: Whether all tasks are done
        tasks: List of tasks in this plan
    """

    __tablename__ = "plans"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True),
    )
    user_id: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    name: str = Field(default="", max_length=255)
    description: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    notes: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    is_completed: bool = Field(default=False)

    # Relationships
    tasks: list["PlanTask"] = Relationship(
        back_populates="plan",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "PlanTask.position",
        },
    )
    user: "User" = Relationship(
        sa_relationship_kwargs={"lazy": "noload"},
    )

    def __repr__(self) -> str:
        return f"<Plan(id={self.id}, name={self.name}, user_id={self.user_id})>"


class PlanTask(TimestampMixin, SQLModel, table=True):
    """PlanTask model - individual task within a plan.

    Tasks are ordered by position and belong to exactly one plan.
    When the plan is deleted, all tasks are cascade deleted.

    Attributes:
        id: Unique task identifier (auto-generated UUID)
        plan_id: Parent plan (required, CASCADE delete)
        description: What needs to be done
        notes: Additional context or details
        status: Current task status (pending/in_progress/completed)
        position: Order in the task list (0-indexed)
        is_completed: Whether the task is done
    """

    __tablename__ = "plan_tasks"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True),
    )
    plan_id: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("plans.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    description: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    notes: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    status: str = Field(default="pending", max_length=20)  # pending, in_progress, completed
    position: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    is_completed: bool = Field(default=False)

    # Relationships
    plan: Plan = Relationship(back_populates="tasks")

    def __repr__(self) -> str:
        return f"<PlanTask(id={self.id}, position={self.position}, status={self.status})>"

"""Plan and PlanTask schemas for AI assistant planning functionality.

These schemas define the API contract for plan operations.
Plans are user-scoped - each plan belongs to exactly one user.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema, TimestampSchema

# =============================================================================
# PlanTask Schemas
# =============================================================================


class PlanTaskBase(BaseSchema):
    """Base plan task schema with common fields."""

    description: str = Field(
        default="",
        description="Description of the task and what needs to be done.",
        examples=["Write unit tests for the new feature", "Design the database schema"],
    )
    notes: str | None = Field(
        default=None,
        description="Additional notes or context for the task.",
        examples=["Remember to follow coding standards", "Consider scalability"],
    )
    status: Literal["pending", "in_progress", "completed"] = Field(
        default="pending",
        description="Current status of the task.",
    )
    is_completed: bool = Field(
        default=False,
        description="Indicates whether the task has been completed.",
    )


class PlanTaskCreate(PlanTaskBase):
    """Schema for creating a new task.

    Position is optional - if not provided, the task will be appended
    at the end of the task list.
    """

    position: int | None = Field(
        default=None,
        ge=0,
        description="Position of the task in the list (0-indexed). If not provided, appends at end.",
    )


class PlanTaskUpdate(BaseSchema):
    """Schema for updating an existing task.

    All fields are optional - only provided fields will be updated.
    """

    description: str | None = Field(default=None)
    notes: str | None = Field(default=None)
    status: Literal["pending", "in_progress", "completed"] | None = Field(default=None)
    position: int | None = Field(default=None, ge=0)
    is_completed: bool | None = Field(default=None)


class PlanTaskRead(PlanTaskBase, TimestampSchema):
    """Schema for reading a task (API response)."""

    id: UUID
    plan_id: UUID
    position: int


# =============================================================================
# Plan Schemas
# =============================================================================


class PlanBase(BaseSchema):
    """Base plan schema with common fields."""

    name: str = Field(
        default="",
        max_length=255,
        description="Name of the plan.",
        examples=["Project Launch Plan", "Marketing Strategy Plan"],
    )
    description: str = Field(
        default="",
        description="Detailed description of the plan and its objectives.",
        examples=["This plan outlines the steps to successfully launch the new product."],
    )
    notes: str | None = Field(
        default=None,
        description="Additional notes or context for the plan.",
        examples=["Include budget considerations.", "Outline key milestones."],
    )


class PlanCreate(PlanBase):
    """Schema for creating a new plan.

    Tasks can be included during creation - they will be created
    with auto-generated UUIDs and sequential positions.
    """

    is_completed: bool = Field(
        default=False,
        description="Indicates whether the plan has been completed.",
    )
    tasks: list[PlanTaskCreate] = Field(
        default_factory=list,
        description="Initial list of tasks for the plan.",
    )


class PlanUpdate(BaseSchema):
    """Schema for updating an existing plan.

    All fields are optional - only provided fields will be updated.
    To update tasks, use the dedicated task endpoints.
    """

    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None)
    notes: str | None = Field(default=None)
    is_completed: bool | None = Field(default=None)


class PlanRead(PlanBase, TimestampSchema):
    """Schema for reading a plan (API response)."""

    id: UUID
    user_id: UUID
    is_completed: bool
    tasks: list[PlanTaskRead] = Field(default_factory=list)


class PlanSummary(BaseSchema):
    """Schema for plan list/summary view (without full task details)."""

    id: UUID
    name: str
    description: str
    is_completed: bool
    task_count: int = Field(description="Total number of tasks in the plan")
    completed_task_count: int = Field(description="Number of completed tasks")
    created_at: datetime
    updated_at: datetime | None = None

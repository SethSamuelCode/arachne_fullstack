"""Plan and PlanTask schemas for AI assistant planning functionality.

These schemas define the API contract for plan operations.
Plans are user-scoped - each plan belongs to exactly one user.

IMPORTANT FOR LLM TOOL USAGE:
- Use create_plan to create a new plan with optional initial tasks
- Use add_task_to_plan to add tasks to an existing plan
- Use update_task to modify task status/description
- Use update_plan to modify plan metadata (NOT tasks)
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
        description=(
            "Clear, actionable description of what needs to be done. "
            "Be specific enough that progress can be measured. "
            "Example: 'Implement user authentication with JWT' rather than 'Do auth'."
        ),
        examples=[
            "Write unit tests for the payment processing module",
            "Design database schema for user profiles",
            "Review and merge PR #42 for API refactoring",
        ],
    )
    notes: str | None = Field(
        default=None,
        description=(
            "Additional context, blockers, dependencies, or implementation details. "
            "Use for information that doesn't fit in the description."
        ),
        examples=[
            "Blocked by: waiting for API credentials from vendor",
            "Dependencies: requires database migration to complete first",
            "Note: use the new logging framework for this task",
        ],
    )
    status: Literal["pending", "in_progress", "completed"] = Field(
        default="pending",
        description=(
            "Current workflow status. "
            "'pending' = not started, "
            "'in_progress' = actively being worked on, "
            "'completed' = finished (also set is_completed=True)."
        ),
    )
    is_completed: bool = Field(
        default=False,
        description=(
            "Whether the task is done. Set to True when status='completed'. "
            "A plan is complete when all its tasks have is_completed=True."
        ),
    )


class PlanTaskCreate(PlanTaskBase):
    """Schema for creating a new task within a plan.

    Use with add_task_to_plan tool or include in PlanCreate.tasks array.
    Position is auto-assigned if not specified (appended to end).
    """

    position: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Zero-indexed position in task list. "
            "0 = first task, None = append at end. "
            "Use to insert tasks at specific positions for ordered workflows."
        ),
        examples=[0, 1, 5],
    )


class PlanTaskUpdate(BaseSchema):
    """Schema for updating an existing task (partial update).

    Only include fields you want to change - omitted fields are unchanged.
    Use with update_task tool.
    """

    description: str | None = Field(
        default=None,
        description="New task description. Omit to keep existing.",
    )
    notes: str | None = Field(
        default=None,
        description="New notes. Omit to keep existing. Set to empty string to clear.",
    )
    status: Literal["pending", "in_progress", "completed"] | None = Field(
        default=None,
        description="New status. When setting to 'completed', also set is_completed=True.",
    )
    position: int | None = Field(
        default=None,
        ge=0,
        description="New position in task list (0-indexed). Other tasks shift automatically.",
    )
    is_completed: bool | None = Field(
        default=None,
        description="Mark task as done (True) or reopen (False).",
    )


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
        description=(
            "Short, descriptive title for the plan. "
            "Should clearly indicate the goal or project."
        ),
        examples=[
            "Q1 Product Launch",
            "Website Redesign Project",
            "Bug Fix Sprint - Week 12",
            "User Research Plan",
        ],
    )
    description: str = Field(
        default="",
        description=(
            "Detailed explanation of the plan's purpose, scope, and success criteria. "
            "Include context that helps understand why this plan exists."
        ),
        examples=[
            "Launch the new mobile app by March 15. Success = 1000 downloads in first week.",
            "Redesign the checkout flow to reduce cart abandonment by 20%.",
            "Fix all P1 bugs reported in the last sprint before release.",
        ],
    )
    notes: str | None = Field(
        default=None,
        description=(
            "Additional context: stakeholders, constraints, risks, or references. "
            "Use for metadata that doesn't fit in description."
        ),
        examples=[
            "Stakeholders: Product team, Marketing. Budget: $50k.",
            "Risk: Depends on third-party API availability.",
            "Reference: See design doc at /docs/design/checkout-v2.md",
        ],
    )


class PlanCreate(PlanBase):
    """Schema for creating a new plan with optional initial tasks.

    Use create_plan tool. You can create an empty plan and add tasks later,
    or include tasks in the 'tasks' array for atomic creation.
    """

    is_completed: bool = Field(
        default=False,
        description="Set True only if creating an already-completed plan (rare). Usually leave as False.",
    )
    tasks: list[PlanTaskCreate] = Field(
        default_factory=list,
        description=(
            "Optional list of tasks to create with the plan. "
            "Tasks are created in array order (position 0, 1, 2...). "
            "You can also add tasks later with add_task_to_plan."
        ),
    )


class PlanUpdate(BaseSchema):
    """Schema for updating plan metadata (NOT tasks).

    Only include fields you want to change - omitted fields unchanged.
    Use update_plan tool. To modify tasks, use update_task or add_task_to_plan.
    """

    name: str | None = Field(
        default=None,
        max_length=255,
        description="New plan name. Omit to keep existing.",
    )
    description: str | None = Field(
        default=None,
        description="New description. Omit to keep existing.",
    )
    notes: str | None = Field(
        default=None,
        description="New notes. Omit to keep existing. Set to empty string to clear.",
    )
    is_completed: bool | None = Field(
        default=None,
        description=(
            "Mark entire plan as complete (True) or reopen (False). "
            "Usually set this after all tasks are completed."
        ),
    )


class PlanRead(PlanBase, TimestampSchema):
    """Schema for reading a plan with all tasks (API response)."""

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

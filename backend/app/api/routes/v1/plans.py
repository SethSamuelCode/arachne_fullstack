"""Plan CRUD routes for AI assistant planning functionality.

Plans are user-scoped - each user can only access their own plans.

Endpoints:
- GET /plans - List all plans (with pagination and optional completed filter)
- POST /plans - Create a new plan
- GET /plans/{plan_id} - Get a single plan with tasks
- PATCH /plans/{plan_id} - Update a plan
- DELETE /plans/{plan_id} - Delete a plan

Task Endpoints:
- POST /plans/{plan_id}/tasks - Add a task to a plan
- PATCH /tasks/{task_id} - Update a task
- DELETE /tasks/{task_id} - Delete a task
- PUT /plans/{plan_id}/tasks/reorder - Reorder tasks in a plan
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, PlanSvc
from app.schemas.plan import (
    PlanCreate,
    PlanRead,
    PlanSummary,
    PlanTaskCreate,
    PlanTaskRead,
    PlanTaskUpdate,
    PlanUpdate,
)

router = APIRouter()


class PlanListResponse(BaseModel):
    """Response schema for paginated plan list."""

    items: list[PlanSummary]
    total: int
    skip: int
    limit: int


class TaskReorderRequest(BaseModel):
    """Request schema for reordering tasks."""

    task_ids: list[UUID] = Field(
        description="Complete list of task IDs in the desired order. "
        "Must include all task IDs belonging to the plan."
    )


# =============================================================================
# Plan Endpoints
# =============================================================================


@router.get("", response_model=PlanListResponse)
async def list_plans(
    plan_service: PlanSvc,
    current_user: CurrentUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    include_completed: Annotated[bool, Query()] = True,
) -> PlanListResponse:
    """List all plans for the current user.

    Returns a paginated list of plan summaries with task counts.

    Args:
        skip: Number of records to skip (for pagination)
        limit: Maximum number of records to return (1-100)
        include_completed: Whether to include completed plans (default: True)
    """
    items, total = await plan_service.list_plans(
        current_user.id,
        skip=skip,
        limit=limit,
        include_completed=include_completed,
    )
    return PlanListResponse(items=items, total=total, skip=skip, limit=limit)


@router.post("", response_model=PlanRead, status_code=status.HTTP_201_CREATED)
async def create_plan(
    plan_in: PlanCreate,
    plan_service: PlanSvc,
    current_user: CurrentUser,
) -> PlanRead:
    """Create a new plan.

    Creates a plan with the provided details. Initial tasks can be
    included in the request body.
    """
    return await plan_service.create_plan(current_user.id, plan_in)


@router.get("/{plan_id}", response_model=PlanRead)
async def get_plan(
    plan_id: UUID,
    plan_service: PlanSvc,
    current_user: CurrentUser,
) -> PlanRead:
    """Get a single plan by ID.

    Returns the plan with all its tasks.

    Raises 404 if the plan does not exist or is not owned by the current user.
    """
    return await plan_service.get_plan(plan_id, current_user.id)


@router.patch("/{plan_id}", response_model=PlanRead)
async def update_plan(
    plan_id: UUID,
    plan_in: PlanUpdate,
    plan_service: PlanSvc,
    current_user: CurrentUser,
) -> PlanRead:
    """Update a plan.

    Supports partial updates - only provided fields are updated.
    To update tasks, use the dedicated task endpoints.

    Raises 404 if the plan does not exist or is not owned by the current user.
    """
    return await plan_service.update_plan(plan_id, current_user.id, plan_in)


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan(
    plan_id: UUID,
    plan_service: PlanSvc,
    current_user: CurrentUser,
) -> None:
    """Delete a plan and all its tasks.

    Raises 404 if the plan does not exist or is not owned by the current user.
    """
    await plan_service.delete_plan(plan_id, current_user.id)


# =============================================================================
# Task Endpoints
# =============================================================================


@router.post("/{plan_id}/tasks", response_model=PlanTaskRead, status_code=status.HTTP_201_CREATED)
async def add_task(
    plan_id: UUID,
    task_in: PlanTaskCreate,
    plan_service: PlanSvc,
    current_user: CurrentUser,
) -> PlanTaskRead:
    """Add a task to a plan.

    If position is not provided, the task will be appended at the end.

    Raises 404 if the plan does not exist or is not owned by the current user.
    """
    return await plan_service.add_task(plan_id, current_user.id, task_in)


@router.patch("/tasks/{task_id}", response_model=PlanTaskRead)
async def update_task(
    task_id: UUID,
    task_in: PlanTaskUpdate,
    plan_service: PlanSvc,
    current_user: CurrentUser,
) -> PlanTaskRead:
    """Update a task.

    Supports partial updates - only provided fields are updated.

    Raises 404 if the task does not exist or the plan is not owned by the current user.
    """
    return await plan_service.update_task(task_id, current_user.id, task_in)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: UUID,
    plan_service: PlanSvc,
    current_user: CurrentUser,
) -> None:
    """Delete a task from its plan.

    Raises 404 if the task does not exist or the plan is not owned by the current user.
    """
    await plan_service.remove_task(task_id, current_user.id)


@router.put("/{plan_id}/tasks/reorder", response_model=PlanRead)
async def reorder_tasks(
    plan_id: UUID,
    reorder_request: TaskReorderRequest,
    plan_service: PlanSvc,
    current_user: CurrentUser,
) -> PlanRead:
    """Reorder tasks in a plan.

    The task_ids list must contain all task IDs belonging to the plan,
    in the desired order.

    Raises 404 if the plan does not exist or is not owned by the current user.
    Raises 400 if the task IDs don't match the plan's tasks.
    """
    return await plan_service.reorder_tasks(plan_id, current_user.id, reorder_request.task_ids)

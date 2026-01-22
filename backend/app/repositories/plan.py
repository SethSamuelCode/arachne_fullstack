"""Plan repository (PostgreSQL async).

Contains database operations for Plan and PlanTask entities.
All operations enforce user-scoping for security.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.plan import Plan, PlanTask
from app.schemas.plan import PlanCreate, PlanTaskCreate, PlanTaskUpdate, PlanUpdate

# =============================================================================
# Plan Operations
# =============================================================================


async def get_plan_by_id(
    db: AsyncSession,
    plan_id: UUID,
    user_id: UUID,
    *,
    include_tasks: bool = True,
) -> Plan | None:
    """Get plan by ID, enforcing user ownership.

    Args:
        db: Database session
        plan_id: The plan's UUID
        user_id: The owner's UUID (enforced)
        include_tasks: Whether to eagerly load tasks

    Returns:
        The plan if found and owned by user, None otherwise.
    """
    query = select(Plan).where(Plan.id == plan_id, Plan.user_id == user_id)
    if include_tasks:
        query = query.options(selectinload(Plan.tasks))
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_plans_by_user(
    db: AsyncSession,
    user_id: UUID,
    *,
    skip: int = 0,
    limit: int = 50,
    include_completed: bool = True,
    include_tasks: bool = False,
) -> list[Plan]:
    """Get all plans for a user with pagination.

    Args:
        db: Database session
        user_id: The owner's UUID
        skip: Number of records to skip
        limit: Maximum records to return
        include_completed: Whether to include completed plans
        include_tasks: Whether to eagerly load tasks

    Returns:
        List of plans owned by the user.
    """
    query = select(Plan).where(Plan.user_id == user_id)
    if not include_completed:
        query = query.where(Plan.is_completed == False)  # noqa: E712
    if include_tasks:
        query = query.options(selectinload(Plan.tasks))
    query = query.order_by(Plan.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def count_plans(
    db: AsyncSession,
    user_id: UUID,
    *,
    include_completed: bool = True,
) -> int:
    """Count plans for a user.

    Args:
        db: Database session
        user_id: The owner's UUID
        include_completed: Whether to include completed plans

    Returns:
        Number of plans owned by the user.
    """
    query = select(func.count(Plan.id)).where(Plan.user_id == user_id)
    if not include_completed:
        query = query.where(Plan.is_completed == False)  # noqa: E712
    result = await db.execute(query)
    return result.scalar() or 0


async def create_plan(
    db: AsyncSession,
    user_id: UUID,
    plan_data: PlanCreate,
) -> Plan:
    """Create a new plan with optional initial tasks.

    Args:
        db: Database session
        user_id: The owner's UUID
        plan_data: Plan creation data

    Returns:
        The newly created plan with tasks loaded.
    """
    # Create the plan
    plan = Plan(
        user_id=user_id,
        name=plan_data.name,
        description=plan_data.description,
        notes=plan_data.notes,
        is_completed=plan_data.is_completed,
    )
    db.add(plan)
    await db.flush()

    # Create tasks if provided
    for position, task_data in enumerate(plan_data.tasks):
        task_position = task_data.position if task_data.position is not None else position
        task = PlanTask(
            plan_id=plan.id,
            description=task_data.description,
            notes=task_data.notes,
            status=task_data.status,
            position=task_position,
            is_completed=task_data.is_completed,
        )
        db.add(task)

    await db.flush()
    await db.refresh(plan)

    # Load tasks relationship
    query = select(Plan).where(Plan.id == plan.id).options(selectinload(Plan.tasks))
    result = await db.execute(query)
    return result.scalar_one()


async def update_plan(
    db: AsyncSession,
    plan_id: UUID,
    user_id: UUID,
    plan_data: PlanUpdate,
) -> Plan | None:
    """Update a plan (does not update tasks - use task operations for that).

    Args:
        db: Database session
        plan_id: The plan's UUID
        user_id: The owner's UUID (enforced)
        plan_data: Partial update data

    Returns:
        The updated plan if found and owned by user, None otherwise.
    """
    plan = await get_plan_by_id(db, plan_id, user_id, include_tasks=False)
    if not plan:
        return None

    # Only update provided fields
    update_dict = plan_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(plan, field, value)

    db.add(plan)
    await db.flush()
    await db.refresh(plan)

    # Load tasks for return
    query = select(Plan).where(Plan.id == plan.id).options(selectinload(Plan.tasks))
    result = await db.execute(query)
    return result.scalar_one()


async def delete_plan(
    db: AsyncSession,
    plan_id: UUID,
    user_id: UUID,
) -> bool:
    """Delete a plan and all its tasks (cascade).

    Args:
        db: Database session
        plan_id: The plan's UUID
        user_id: The owner's UUID (enforced)

    Returns:
        True if deleted, False if not found or not owned by user.
    """
    plan = await get_plan_by_id(db, plan_id, user_id, include_tasks=False)
    if not plan:
        return False

    await db.delete(plan)
    await db.flush()
    return True


# =============================================================================
# PlanTask Operations
# =============================================================================


async def get_task_by_id(
    db: AsyncSession,
    task_id: UUID,
    user_id: UUID,
) -> PlanTask | None:
    """Get a task by ID, enforcing user ownership through plan.

    Args:
        db: Database session
        task_id: The task's UUID
        user_id: The owner's UUID (enforced via plan)

    Returns:
        The task if found and plan is owned by user, None otherwise.
    """
    query = (
        select(PlanTask)
        .join(Plan)
        .where(PlanTask.id == task_id, Plan.user_id == user_id)
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_max_task_position(db: AsyncSession, plan_id: UUID) -> int:
    """Get the maximum task position in a plan.

    Args:
        db: Database session
        plan_id: The plan's UUID

    Returns:
        The maximum position, or -1 if no tasks exist.
    """
    query = select(func.max(PlanTask.position)).where(PlanTask.plan_id == plan_id)
    result = await db.execute(query)
    max_pos = result.scalar()
    return max_pos if max_pos is not None else -1


async def add_task_to_plan(
    db: AsyncSession,
    plan_id: UUID,
    user_id: UUID,
    task_data: PlanTaskCreate,
) -> PlanTask | None:
    """Add a task to a plan.

    Args:
        db: Database session
        plan_id: The plan's UUID
        user_id: The owner's UUID (enforced)
        task_data: Task creation data

    Returns:
        The newly created task, or None if plan not found/not owned.
    """
    # Verify plan ownership
    plan = await get_plan_by_id(db, plan_id, user_id, include_tasks=False)
    if not plan:
        return None

    # Determine position
    if task_data.position is not None:
        position = task_data.position
        # Shift existing tasks at or after this position
        await db.execute(
            sql_update(PlanTask)
            .where(PlanTask.plan_id == plan_id, PlanTask.position >= position)
            .values(position=PlanTask.position + 1)
        )
    else:
        # Append at end
        position = await get_max_task_position(db, plan_id) + 1

    task = PlanTask(
        plan_id=plan_id,
        description=task_data.description,
        notes=task_data.notes,
        status=task_data.status,
        position=position,
        is_completed=task_data.is_completed,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


async def update_task(
    db: AsyncSession,
    task_id: UUID,
    user_id: UUID,
    task_data: PlanTaskUpdate,
) -> PlanTask | None:
    """Update a task.

    Args:
        db: Database session
        task_id: The task's UUID
        user_id: The owner's UUID (enforced via plan)
        task_data: Partial update data

    Returns:
        The updated task, or None if not found/not owned.
    """
    task = await get_task_by_id(db, task_id, user_id)
    if not task:
        return None

    update_dict = task_data.model_dump(exclude_unset=True)

    # Handle position change separately (requires shifting other tasks)
    if "position" in update_dict and update_dict["position"] != task.position:
        new_position = update_dict.pop("position")
        old_position = task.position

        if new_position > old_position:
            # Moving down: shift tasks between old and new position up
            await db.execute(
                sql_update(PlanTask)
                .where(
                    PlanTask.plan_id == task.plan_id,
                    PlanTask.position > old_position,
                    PlanTask.position <= new_position,
                )
                .values(position=PlanTask.position - 1)
            )
        else:
            # Moving up: shift tasks between new and old position down
            await db.execute(
                sql_update(PlanTask)
                .where(
                    PlanTask.plan_id == task.plan_id,
                    PlanTask.position >= new_position,
                    PlanTask.position < old_position,
                )
                .values(position=PlanTask.position + 1)
            )

        task.position = new_position

    # Update other fields
    for field, value in update_dict.items():
        setattr(task, field, value)

    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


async def remove_task_from_plan(
    db: AsyncSession,
    task_id: UUID,
    user_id: UUID,
) -> bool:
    """Remove a task from a plan.

    Args:
        db: Database session
        task_id: The task's UUID
        user_id: The owner's UUID (enforced via plan)

    Returns:
        True if deleted, False if not found/not owned.
    """
    task = await get_task_by_id(db, task_id, user_id)
    if not task:
        return False

    plan_id = task.plan_id
    position = task.position

    await db.delete(task)
    await db.flush()

    # Shift remaining tasks to close the gap
    await db.execute(
        sql_update(PlanTask)
        .where(PlanTask.plan_id == plan_id, PlanTask.position > position)
        .values(position=PlanTask.position - 1)
    )
    await db.flush()

    return True


async def reorder_tasks(
    db: AsyncSession,
    plan_id: UUID,
    user_id: UUID,
    task_ids: list[UUID],
) -> bool:
    """Reorder tasks in a plan by providing the complete task ID list in desired order.

    Args:
        db: Database session
        plan_id: The plan's UUID
        user_id: The owner's UUID (enforced)
        task_ids: Complete list of task IDs in desired order

    Returns:
        True if successful, False if plan not found/not owned or task IDs invalid.
    """
    # Verify plan ownership
    plan = await get_plan_by_id(db, plan_id, user_id, include_tasks=True)
    if not plan:
        return False

    # Verify all task IDs belong to this plan
    existing_ids = {task.id for task in plan.tasks}
    if set(task_ids) != existing_ids:
        return False

    # Update positions
    for position, task_id in enumerate(task_ids):
        await db.execute(
            sql_update(PlanTask)
            .where(PlanTask.id == task_id)
            .values(position=position)
        )

    await db.flush()
    return True

"""Plan service (PostgreSQL async).

Contains business logic for plan and task operations.
All operations enforce user-scoping for security.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models.plan import Plan, PlanTask
from app.repositories import plan as plan_repo
from app.schemas.plan import (
    PlanCreate,
    PlanRead,
    PlanSummary,
    PlanTaskCreate,
    PlanTaskRead,
    PlanTaskUpdate,
    PlanUpdate,
)


class PlanService:
    """Service for plan-related business logic.

    All methods require user_id and enforce user-scoping:
    a user can only access their own plans and tasks.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # =========================================================================
    # Plan Methods
    # =========================================================================

    async def get_plan(
        self,
        plan_id: UUID,
        user_id: UUID,
    ) -> PlanRead:
        """Get a plan by ID.

        Args:
            plan_id: The plan's UUID
            user_id: The requesting user's UUID (enforced)

        Returns:
            The plan with tasks.

        Raises:
            NotFoundError: If plan does not exist or is not owned by user.
        """
        plan = await plan_repo.get_plan_by_id(self.db, plan_id, user_id, include_tasks=True)
        if not plan:
            raise NotFoundError(
                message="Plan not found",
                details={"plan_id": str(plan_id)},
            )
        return self._plan_to_read(plan)

    async def list_plans(
        self,
        user_id: UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        include_completed: bool = True,
    ) -> tuple[list[PlanSummary], int]:
        """List plans for a user with pagination.

        Args:
            user_id: The requesting user's UUID
            skip: Number of records to skip
            limit: Maximum records to return
            include_completed: Whether to include completed plans

        Returns:
            Tuple of (plan summaries, total count).
        """
        plans = await plan_repo.get_plans_by_user(
            self.db,
            user_id,
            skip=skip,
            limit=limit,
            include_completed=include_completed,
            include_tasks=True,  # Need tasks for summary counts
        )
        total = await plan_repo.count_plans(
            self.db,
            user_id,
            include_completed=include_completed,
        )
        summaries = [self._plan_to_summary(plan) for plan in plans]
        return summaries, total

    async def get_all_plan_summaries(
        self,
        user_id: UUID,
    ) -> list[PlanSummary]:
        """Get summaries of all plans for a user (for tool usage).

        Args:
            user_id: The requesting user's UUID

        Returns:
            List of plan summaries.
        """
        plans = await plan_repo.get_plans_by_user(
            self.db,
            user_id,
            skip=0,
            limit=1000,  # Reasonable max for tool usage
            include_completed=True,
            include_tasks=True,
        )
        return [self._plan_to_summary(plan) for plan in plans]

    async def create_plan(
        self,
        user_id: UUID,
        data: PlanCreate,
    ) -> PlanRead:
        """Create a new plan.

        Args:
            user_id: The owner's UUID
            data: Plan creation data (may include initial tasks)

        Returns:
            The newly created plan with tasks.
        """
        plan = await plan_repo.create_plan(self.db, user_id, data)
        return self._plan_to_read(plan)

    async def update_plan(
        self,
        plan_id: UUID,
        user_id: UUID,
        data: PlanUpdate,
    ) -> PlanRead:
        """Update a plan (does not update tasks).

        Args:
            plan_id: The plan's UUID
            user_id: The requesting user's UUID (enforced)
            data: Partial update data

        Returns:
            The updated plan with tasks.

        Raises:
            NotFoundError: If plan does not exist or is not owned by user.
        """
        plan = await plan_repo.update_plan(self.db, plan_id, user_id, data)
        if not plan:
            raise NotFoundError(
                message="Plan not found",
                details={"plan_id": str(plan_id)},
            )
        return self._plan_to_read(plan)

    async def delete_plan(
        self,
        plan_id: UUID,
        user_id: UUID,
    ) -> bool:
        """Delete a plan and all its tasks.

        Args:
            plan_id: The plan's UUID
            user_id: The requesting user's UUID (enforced)

        Returns:
            True if deleted.

        Raises:
            NotFoundError: If plan does not exist or is not owned by user.
        """
        deleted = await plan_repo.delete_plan(self.db, plan_id, user_id)
        if not deleted:
            raise NotFoundError(
                message="Plan not found",
                details={"plan_id": str(plan_id)},
            )
        return True

    # =========================================================================
    # Task Methods
    # =========================================================================

    async def add_task(
        self,
        plan_id: UUID,
        user_id: UUID,
        data: PlanTaskCreate,
    ) -> PlanTaskRead:
        """Add a task to a plan.

        Args:
            plan_id: The plan's UUID
            user_id: The requesting user's UUID (enforced)
            data: Task creation data

        Returns:
            The newly created task.

        Raises:
            NotFoundError: If plan does not exist or is not owned by user.
        """
        task = await plan_repo.add_task_to_plan(self.db, plan_id, user_id, data)
        if not task:
            raise NotFoundError(
                message="Plan not found",
                details={"plan_id": str(plan_id)},
            )
        return self._task_to_read(task)

    async def update_task(
        self,
        task_id: UUID,
        user_id: UUID,
        data: PlanTaskUpdate,
    ) -> PlanTaskRead:
        """Update a task.

        Args:
            task_id: The task's UUID
            user_id: The requesting user's UUID (enforced via plan)
            data: Partial update data

        Returns:
            The updated task.

        Raises:
            NotFoundError: If task does not exist or plan is not owned by user.
        """
        task = await plan_repo.update_task(self.db, task_id, user_id, data)
        if not task:
            raise NotFoundError(
                message="Task not found",
                details={"task_id": str(task_id)},
            )
        return self._task_to_read(task)

    async def remove_task(
        self,
        task_id: UUID,
        user_id: UUID,
    ) -> bool:
        """Remove a task from its plan.

        Args:
            task_id: The task's UUID
            user_id: The requesting user's UUID (enforced via plan)

        Returns:
            True if deleted.

        Raises:
            NotFoundError: If task does not exist or plan is not owned by user.
        """
        deleted = await plan_repo.remove_task_from_plan(self.db, task_id, user_id)
        if not deleted:
            raise NotFoundError(
                message="Task not found",
                details={"task_id": str(task_id)},
            )
        return True

    async def reorder_tasks(
        self,
        plan_id: UUID,
        user_id: UUID,
        task_ids: list[UUID],
    ) -> PlanRead:
        """Reorder tasks in a plan.

        Args:
            plan_id: The plan's UUID
            user_id: The requesting user's UUID (enforced)
            task_ids: Complete list of task IDs in desired order

        Returns:
            The plan with reordered tasks.

        Raises:
            NotFoundError: If plan does not exist or is not owned by user.
            ValueError: If task_ids don't match the plan's tasks.
        """
        success = await plan_repo.reorder_tasks(self.db, plan_id, user_id, task_ids)
        if not success:
            # Could be plan not found or task IDs mismatch
            plan = await plan_repo.get_plan_by_id(self.db, plan_id, user_id, include_tasks=False)
            if not plan:
                raise NotFoundError(
                    message="Plan not found",
                    details={"plan_id": str(plan_id)},
                )
            raise ValueError("Task IDs do not match the plan's tasks")

        # Reload and return the plan
        return await self.get_plan(plan_id, user_id)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _plan_to_read(self, plan: Plan) -> PlanRead:
        """Convert a Plan model to PlanRead schema."""
        return PlanRead(
            id=plan.id,
            user_id=plan.user_id,
            name=plan.name,
            description=plan.description,
            notes=plan.notes,
            is_completed=plan.is_completed,
            created_at=plan.created_at,
            updated_at=plan.updated_at,
            tasks=[self._task_to_read(task) for task in plan.tasks],
        )

    def _plan_to_summary(self, plan: Plan) -> PlanSummary:
        """Convert a Plan model to PlanSummary schema."""
        return PlanSummary(
            id=plan.id,
            name=plan.name,
            description=plan.description,
            is_completed=plan.is_completed,
            task_count=len(plan.tasks),
            completed_task_count=sum(1 for t in plan.tasks if t.is_completed),
            created_at=plan.created_at,
            updated_at=plan.updated_at,
        )

    def _task_to_read(self, task: PlanTask) -> PlanTaskRead:
        """Convert a PlanTask model to PlanTaskRead schema."""
        return PlanTaskRead(
            id=task.id,
            plan_id=task.plan_id,
            description=task.description,
            notes=task.notes,
            status=task.status,
            position=task.position,
            is_completed=task.is_completed,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

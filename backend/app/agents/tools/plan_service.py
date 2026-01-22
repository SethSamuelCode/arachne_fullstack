from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.schemas.planning import Plan, PlanUpdate, SingleTask, SingleTaskUpdate

tz = ZoneInfo(settings.TZ)


class PlanStore:
    def __init__(self):
        self.plans: dict[str, Plan] = {}

    def update_plan(self, plan_id: str, plan_data: PlanUpdate) -> str:
        """Update a plan with partial update semantics.

        Only fields explicitly provided in plan_data will be updated.
        Missing fields retain their existing values.

        Args:
            plan_id: The unique identifier of the plan to update.
            plan_data: The partial update data.

        Returns:
            A confirmation message or error string.
        """
        if plan_id not in self.plans:
            return f"plan {plan_id} not found"

        existing_plan = self.plans[plan_id]

        # Get only explicitly provided fields (exclude unset)
        update_data = plan_data.model_dump(exclude_unset=True)

        # Handle steps separately due to nested partial update logic
        steps_update = update_data.pop("steps", None)

        # Update plan-level fields
        for key, value in update_data.items():
            setattr(existing_plan, key, value)

        # Handle step updates if provided
        if steps_update is not None:
            # Build lookup dict for existing steps
            existing_steps_by_id = {step.id: step for step in existing_plan.steps}

            # Validate all incoming step IDs exist
            unknown_ids = [
                step_data["id"]
                for step_data in steps_update
                if step_data["id"] not in existing_steps_by_id
            ]
            if unknown_ids:
                return f"unknown task IDs: {', '.join(unknown_ids)}. Use add_task_to_plan to create new tasks."

            # Apply partial updates to matched steps
            for step_data in steps_update:
                step_id = step_data["id"]
                existing_step = existing_steps_by_id[step_id]

                # Get the original SingleTaskUpdate to use exclude_unset properly
                # We need to find which fields were actually set in the original input
                step_update = SingleTaskUpdate(**step_data)
                step_update_data = step_update.model_dump(exclude_unset=True)

                # Remove id since we don't want to update it
                step_update_data.pop("id", None)

                for key, value in step_update_data.items():
                    setattr(existing_step, key, value)

        existing_plan.updated_at = datetime.now(tz=tz)

        return f"plan {plan_id} updated"

    def add_task(self, plan_id: str, task: SingleTask) -> str:
        """Add a new task to an existing plan.

        Args:
            plan_id: The unique identifier of the plan.
            task: The task to add.

        Returns:
            The task ID on success, or an error message.
        """
        if plan_id not in self.plans:
            return f"plan {plan_id} not found"

        existing_plan = self.plans[plan_id]

        # Check for duplicate task ID
        existing_task_ids = {step.id for step in existing_plan.steps}
        if task.id in existing_task_ids:
            return f"task {task.id} already exists in plan {plan_id}"

        existing_plan.steps.append(task)
        existing_plan.updated_at = datetime.now(tz=tz)

        return f"task {task.id} added to plan {plan_id}"

    def remove_task(self, plan_id: str, task_id: str) -> str:
        """Remove a task from an existing plan.

        Args:
            plan_id: The unique identifier of the plan.
            task_id: The unique identifier of the task to remove.

        Returns:
            A confirmation message or error string.
        """
        if plan_id not in self.plans:
            return f"plan {plan_id} not found"

        existing_plan = self.plans[plan_id]

        # Find and remove the task
        for i, step in enumerate(existing_plan.steps):
            if step.id == task_id:
                existing_plan.steps.pop(i)
                existing_plan.updated_at = datetime.now(tz=tz)
                return f"task {task_id} removed from plan {plan_id}"

        return f"task {task_id} not found in plan {plan_id}"

    def create_plan(self, plan_data: Plan) -> str:
        plan_id = plan_data.id
        self.plans[plan_id] = plan_data
        return plan_id

    def get_plan(self, plan_id: str) -> Plan | str:
        if plan_id in self.plans:
            return self.plans[plan_id]
        else:
            return f"plan {plan_id} not found"

    def delete_plan(self, plan_id: str) -> str:
        if plan_id in self.plans:
            del self.plans[plan_id]
            return f"plan {plan_id} deleted"
        return f"plan {plan_id} not found"

    def get_all_plans(self) -> list:
        export_list = []
        for plan in self.plans.values():
            export_list.append((plan.id, plan.name, plan.plan_description))
        return export_list


plan_service = PlanStore()


def get_plan_service():
    return plan_service

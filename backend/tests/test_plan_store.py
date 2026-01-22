"""Tests for PlanStore partial update functionality."""

import pytest

from app.agents.tools.plan_service import PlanStore
from app.schemas.planning import Plan, PlanUpdate, SingleTask, SingleTaskUpdate


@pytest.fixture
def plan_store() -> PlanStore:
    """Create a fresh PlanStore instance for each test."""
    return PlanStore()


@pytest.fixture
def sample_plan() -> Plan:
    """Create a sample plan with tasks for testing."""
    return Plan(
        id="test-plan-123",
        name="Build Rocket",
        plan_description="A plan to build a rocket and launch it to space.",
        steps=[
            SingleTask(
                id="task-1",
                task_description="Buy fuel",
                task_notes="Get premium rocket fuel",
                task_status="pending",
                task_completed=False,
                task_position=0,
            ),
            SingleTask(
                id="task-2",
                task_description="Assemble engines",
                task_notes="Follow safety protocols",
                task_status="pending",
                task_completed=False,
                task_position=1,
            ),
        ],
        plan_notes="High priority project",
        plan_completed=False,
    )


class TestUpdatePlanPartialUpdates:
    """Tests for partial update semantics in update_plan."""

    def test_update_plan_partial_preserves_descriptions(
        self, plan_store: PlanStore, sample_plan: Plan
    ):
        """Updating only task_status should preserve task_description and plan_description."""
        # Arrange: Create the plan
        plan_store.create_plan(sample_plan)

        # Act: Update only task status (simulating what an LLM would send)
        update_data = PlanUpdate(
            steps=[
                SingleTaskUpdate(id="task-1", task_status="completed", task_completed=True)
            ]
        )
        result = plan_store.update_plan("test-plan-123", update_data)

        # Assert: Descriptions are preserved
        assert result == "plan test-plan-123 updated"
        updated_plan = plan_store.get_plan("test-plan-123")
        assert isinstance(updated_plan, Plan)

        # Plan-level fields preserved
        assert updated_plan.name == "Build Rocket"
        assert updated_plan.plan_description == "A plan to build a rocket and launch it to space."
        assert updated_plan.plan_notes == "High priority project"

        # Task 1: status updated, description preserved
        task_1 = next(t for t in updated_plan.steps if t.id == "task-1")
        assert task_1.task_status == "completed"
        assert task_1.task_completed is True
        assert task_1.task_description == "Buy fuel"
        assert task_1.task_notes == "Get premium rocket fuel"

        # Task 2: completely unchanged
        task_2 = next(t for t in updated_plan.steps if t.id == "task-2")
        assert task_2.task_status == "pending"
        assert task_2.task_completed is False
        assert task_2.task_description == "Assemble engines"

    def test_update_plan_partial_plan_level_fields(
        self, plan_store: PlanStore, sample_plan: Plan
    ):
        """Updating only plan-level fields should preserve tasks."""
        # Arrange
        plan_store.create_plan(sample_plan)

        # Act: Update only plan name
        update_data = PlanUpdate(name="Build Super Rocket")
        result = plan_store.update_plan("test-plan-123", update_data)

        # Assert
        assert result == "plan test-plan-123 updated"
        updated_plan = plan_store.get_plan("test-plan-123")
        assert isinstance(updated_plan, Plan)

        # Name updated
        assert updated_plan.name == "Build Super Rocket"

        # Other plan fields preserved
        assert updated_plan.plan_description == "A plan to build a rocket and launch it to space."
        assert updated_plan.plan_notes == "High priority project"

        # Tasks completely preserved
        assert len(updated_plan.steps) == 2
        assert updated_plan.steps[0].task_description == "Buy fuel"
        assert updated_plan.steps[1].task_description == "Assemble engines"

    def test_update_plan_empty_update_preserves_all(
        self, plan_store: PlanStore, sample_plan: Plan
    ):
        """An empty update should preserve all existing data."""
        # Arrange
        plan_store.create_plan(sample_plan)

        # Act: Empty update (only updated_at should change)
        update_data = PlanUpdate()
        result = plan_store.update_plan("test-plan-123", update_data)

        # Assert
        assert result == "plan test-plan-123 updated"
        updated_plan = plan_store.get_plan("test-plan-123")
        assert isinstance(updated_plan, Plan)

        assert updated_plan.name == "Build Rocket"
        assert updated_plan.plan_description == "A plan to build a rocket and launch it to space."
        assert len(updated_plan.steps) == 2


class TestUpdatePlanValidation:
    """Tests for validation in update_plan."""

    def test_update_plan_unknown_plan_id(self, plan_store: PlanStore):
        """Updating a non-existent plan should return an error."""
        update_data = PlanUpdate(name="New Name")
        result = plan_store.update_plan("nonexistent-plan", update_data)
        assert result == "plan nonexistent-plan not found"

    def test_update_plan_unknown_step_id_returns_error(
        self, plan_store: PlanStore, sample_plan: Plan
    ):
        """Updating with an unknown task ID should return an error listing the unknown IDs."""
        # Arrange
        plan_store.create_plan(sample_plan)

        # Act: Try to update a task that doesn't exist
        update_data = PlanUpdate(
            steps=[
                SingleTaskUpdate(id="nonexistent-task", task_status="completed")
            ]
        )
        result = plan_store.update_plan("test-plan-123", update_data)

        # Assert: Error message includes the unknown ID
        assert "unknown task IDs" in result
        assert "nonexistent-task" in result
        assert "add_task_to_plan" in result

    def test_update_plan_multiple_unknown_step_ids(
        self, plan_store: PlanStore, sample_plan: Plan
    ):
        """Multiple unknown task IDs should all be listed in the error."""
        # Arrange
        plan_store.create_plan(sample_plan)

        # Act
        update_data = PlanUpdate(
            steps=[
                SingleTaskUpdate(id="unknown-1", task_status="completed"),
                SingleTaskUpdate(id="unknown-2", task_status="in_progress"),
            ]
        )
        result = plan_store.update_plan("test-plan-123", update_data)

        # Assert
        assert "unknown task IDs" in result
        assert "unknown-1" in result
        assert "unknown-2" in result


class TestAddTaskToPlan:
    """Tests for add_task functionality."""

    def test_add_task_to_plan_success(self, plan_store: PlanStore, sample_plan: Plan):
        """Adding a task to an existing plan should succeed."""
        # Arrange
        plan_store.create_plan(sample_plan)
        new_task = SingleTask(
            id="task-3",
            task_description="Launch rocket",
            task_status="pending",
        )

        # Act
        result = plan_store.add_task("test-plan-123", new_task)

        # Assert
        assert "task task-3 added" in result
        updated_plan = plan_store.get_plan("test-plan-123")
        assert isinstance(updated_plan, Plan)
        assert len(updated_plan.steps) == 3
        assert updated_plan.steps[2].id == "task-3"
        assert updated_plan.steps[2].task_description == "Launch rocket"

    def test_add_task_to_plan_unknown_plan(self, plan_store: PlanStore):
        """Adding a task to a non-existent plan should return an error."""
        new_task = SingleTask(id="task-1", task_description="Test task")
        result = plan_store.add_task("nonexistent-plan", new_task)
        assert result == "plan nonexistent-plan not found"

    def test_add_task_duplicate_id_returns_error(
        self, plan_store: PlanStore, sample_plan: Plan
    ):
        """Adding a task with a duplicate ID should return an error."""
        # Arrange
        plan_store.create_plan(sample_plan)
        duplicate_task = SingleTask(
            id="task-1",  # Already exists
            task_description="Duplicate task",
        )

        # Act
        result = plan_store.add_task("test-plan-123", duplicate_task)

        # Assert
        assert "task task-1 already exists" in result


class TestRemoveTaskFromPlan:
    """Tests for remove_task functionality."""

    def test_remove_task_from_plan_success(
        self, plan_store: PlanStore, sample_plan: Plan
    ):
        """Removing an existing task should succeed."""
        # Arrange
        plan_store.create_plan(sample_plan)

        # Act
        result = plan_store.remove_task("test-plan-123", "task-1")

        # Assert
        assert "task task-1 removed" in result
        updated_plan = plan_store.get_plan("test-plan-123")
        assert isinstance(updated_plan, Plan)
        assert len(updated_plan.steps) == 1
        assert updated_plan.steps[0].id == "task-2"

    def test_remove_task_unknown_plan(self, plan_store: PlanStore):
        """Removing a task from a non-existent plan should return an error."""
        result = plan_store.remove_task("nonexistent-plan", "task-1")
        assert result == "plan nonexistent-plan not found"

    def test_remove_task_unknown_task_id(
        self, plan_store: PlanStore, sample_plan: Plan
    ):
        """Removing a non-existent task should return an error."""
        # Arrange
        plan_store.create_plan(sample_plan)

        # Act
        result = plan_store.remove_task("test-plan-123", "nonexistent-task")

        # Assert
        assert "task nonexistent-task not found" in result


class TestUpdatePlanTimestamp:
    """Tests for updated_at timestamp behavior."""

    def test_update_plan_sets_updated_at(
        self, plan_store: PlanStore, sample_plan: Plan
    ):
        """Updating a plan should set the updated_at timestamp."""
        # Arrange
        plan_store.create_plan(sample_plan)
        original_updated_at = plan_store.get_plan("test-plan-123").updated_at

        # Act
        update_data = PlanUpdate(name="Updated Name")
        plan_store.update_plan("test-plan-123", update_data)

        # Assert
        updated_plan = plan_store.get_plan("test-plan-123")
        assert isinstance(updated_plan, Plan)
        assert updated_plan.updated_at is not None
        assert updated_plan.updated_at != original_updated_at

    def test_add_task_sets_updated_at(self, plan_store: PlanStore, sample_plan: Plan):
        """Adding a task should set the updated_at timestamp."""
        # Arrange
        plan_store.create_plan(sample_plan)

        # Act
        new_task = SingleTask(id="task-3", task_description="New task")
        plan_store.add_task("test-plan-123", new_task)

        # Assert
        updated_plan = plan_store.get_plan("test-plan-123")
        assert isinstance(updated_plan, Plan)
        assert updated_plan.updated_at is not None

    def test_remove_task_sets_updated_at(
        self, plan_store: PlanStore, sample_plan: Plan
    ):
        """Removing a task should set the updated_at timestamp."""
        # Arrange
        plan_store.create_plan(sample_plan)

        # Act
        plan_store.remove_task("test-plan-123", "task-1")

        # Assert
        updated_plan = plan_store.get_plan("test-plan-123")
        assert isinstance(updated_plan, Plan)
        assert updated_plan.updated_at is not None

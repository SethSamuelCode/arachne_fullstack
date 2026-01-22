"""Tests for plan repository and service.

Tests user-scoped plan and task operations with database persistence.
Uses mock database sessions for unit testing.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import NotFoundError
from app.db.models.plan import Plan, PlanTask
from app.schemas.plan import (
    PlanCreate,
    PlanRead,
    PlanSummary,
    PlanTaskCreate,
    PlanTaskRead,
    PlanTaskUpdate,
    PlanUpdate,
)
from app.services.plan import PlanService


@pytest.fixture
def user_id() -> UUID:
    """Create a test user ID."""
    return uuid4()


@pytest.fixture
def other_user_id() -> UUID:
    """Create a different user ID for isolation tests."""
    return uuid4()


@pytest.fixture
def plan_id() -> UUID:
    """Create a test plan ID."""
    return uuid4()


@pytest.fixture
def task_id() -> UUID:
    """Create a test task ID."""
    return uuid4()


@pytest.fixture
def mock_db() -> AsyncMock:
    """Create a mock async database session."""
    mock = AsyncMock()
    mock.add = MagicMock()
    mock.flush = AsyncMock()
    mock.refresh = AsyncMock()
    mock.delete = AsyncMock()
    mock.execute = AsyncMock()
    mock.scalar = AsyncMock()
    return mock


@pytest.fixture
def sample_plan(plan_id: UUID, user_id: UUID) -> Plan:
    """Create a sample plan model for testing."""
    plan = Plan(
        id=plan_id,
        user_id=user_id,
        name="Build Rocket",
        description="A plan to build a rocket",
        notes="High priority",
        is_completed=False,
    )
    plan.tasks = []  # Initialize empty tasks list (normally done by relationship)
    return plan


@pytest.fixture
def sample_task(task_id: UUID, plan_id: UUID) -> PlanTask:
    """Create a sample task model for testing."""
    return PlanTask(
        id=task_id,
        plan_id=plan_id,
        description="Buy rocket fuel",
        notes="Premium grade only",
        status="pending",
        position=0,
        is_completed=False,
    )


class TestPlanServiceUserIsolation:
    """Tests for user isolation in PlanService."""

    @pytest.mark.anyio
    async def test_get_plan_returns_user_plan(
        self, mock_db: AsyncMock, user_id: UUID, sample_plan: Plan
    ):
        """Users can only get their own plans."""
        with patch("app.repositories.plan.get_plan_by_id") as mock_get:
            mock_get.return_value = sample_plan
            service = PlanService(mock_db)

            result = await service.get_plan(sample_plan.id, user_id)

            assert isinstance(result, PlanRead)
            assert result.id == sample_plan.id
            assert result.name == "Build Rocket"
            mock_get.assert_called_once_with(
                mock_db, sample_plan.id, user_id, include_tasks=True
            )

    @pytest.mark.anyio
    async def test_get_plan_raises_not_found_for_other_user(
        self, mock_db: AsyncMock, user_id: UUID, plan_id: UUID, other_user_id: UUID
    ):
        """Getting another user's plan raises NotFoundError."""
        with patch("app.repositories.plan.get_plan_by_id") as mock_get:
            # Repository returns None when user doesn't own the plan
            mock_get.return_value = None
            service = PlanService(mock_db)

            with pytest.raises(NotFoundError) as exc_info:
                await service.get_plan(plan_id, other_user_id)

            assert "Plan not found" in str(exc_info.value.message)

    @pytest.mark.anyio
    async def test_delete_plan_requires_ownership(
        self, mock_db: AsyncMock, user_id: UUID, plan_id: UUID, other_user_id: UUID
    ):
        """Deleting requires ownership of the plan."""
        with patch("app.repositories.plan.delete_plan") as mock_delete:
            mock_delete.return_value = False  # Simulates not found or not owned
            service = PlanService(mock_db)

            with pytest.raises(NotFoundError):
                await service.delete_plan(plan_id, other_user_id)


class TestPlanServiceCRUD:
    """Tests for CRUD operations in PlanService."""

    @pytest.mark.anyio
    async def test_create_plan_with_tasks(self, mock_db: AsyncMock, user_id: UUID):
        """Creating a plan with initial tasks works correctly."""
        plan_data = PlanCreate(
            name="Test Plan",
            description="Test description",
            tasks=[
                PlanTaskCreate(description="Task 1"),
                PlanTaskCreate(description="Task 2"),
            ],
        )

        # Mock the repository to return a plan with tasks
        created_plan = Plan(
            id=uuid4(),
            user_id=user_id,
            name="Test Plan",
            description="Test description",
        )
        created_plan.tasks = [
            PlanTask(id=uuid4(), plan_id=created_plan.id, description="Task 1", position=0),
            PlanTask(id=uuid4(), plan_id=created_plan.id, description="Task 2", position=1),
        ]

        with patch("app.repositories.plan.create_plan") as mock_create:
            mock_create.return_value = created_plan
            service = PlanService(mock_db)

            result = await service.create_plan(user_id, plan_data)

            assert isinstance(result, PlanRead)
            assert result.name == "Test Plan"
            assert len(result.tasks) == 2
            mock_create.assert_called_once_with(mock_db, user_id, plan_data)

    @pytest.mark.anyio
    async def test_update_plan_preserves_unset_fields(
        self, mock_db: AsyncMock, user_id: UUID, sample_plan: Plan
    ):
        """Partial update only changes specified fields."""
        update_data = PlanUpdate(name="Updated Rocket")  # Only name changed

        updated_plan = Plan(
            id=sample_plan.id,
            user_id=user_id,
            name="Updated Rocket",
            description=sample_plan.description,  # Preserved
            notes=sample_plan.notes,  # Preserved
        )
        updated_plan.tasks = []

        with patch("app.repositories.plan.update_plan") as mock_update:
            mock_update.return_value = updated_plan
            service = PlanService(mock_db)

            result = await service.update_plan(sample_plan.id, user_id, update_data)

            assert result.name == "Updated Rocket"
            assert result.description == "A plan to build a rocket"
            assert result.notes == "High priority"

    @pytest.mark.anyio
    async def test_list_plans_returns_summaries(
        self, mock_db: AsyncMock, user_id: UUID, sample_plan: Plan
    ):
        """Listing plans returns summary objects."""
        sample_plan.tasks = [
            PlanTask(
                id=uuid4(),
                plan_id=sample_plan.id,
                description="Task",
                position=0,
                is_completed=True,
            ),
            PlanTask(
                id=uuid4(),
                plan_id=sample_plan.id,
                description="Task 2",
                position=1,
                is_completed=False,
            ),
        ]

        with (
            patch("app.repositories.plan.get_plans_by_user") as mock_list,
            patch("app.repositories.plan.count_plans") as mock_count,
        ):
            mock_list.return_value = [sample_plan]
            mock_count.return_value = 1
            service = PlanService(mock_db)

            summaries, total = await service.list_plans(user_id)

            assert total == 1
            assert len(summaries) == 1
            assert isinstance(summaries[0], PlanSummary)
            assert summaries[0].task_count == 2
            assert summaries[0].completed_task_count == 1


class TestPlanServiceTaskOperations:
    """Tests for task operations in PlanService."""

    @pytest.mark.anyio
    async def test_add_task_to_plan(
        self, mock_db: AsyncMock, user_id: UUID, plan_id: UUID
    ):
        """Adding a task to a plan works correctly."""
        task_data = PlanTaskCreate(
            description="New task",
            notes="Important task",
        )
        created_task = PlanTask(
            id=uuid4(),
            plan_id=plan_id,
            description="New task",
            notes="Important task",
            position=0,
        )

        with patch("app.repositories.plan.add_task_to_plan") as mock_add:
            mock_add.return_value = created_task
            service = PlanService(mock_db)

            result = await service.add_task(plan_id, user_id, task_data)

            assert isinstance(result, PlanTaskRead)
            assert result.description == "New task"
            mock_add.assert_called_once_with(mock_db, plan_id, user_id, task_data)

    @pytest.mark.anyio
    async def test_add_task_to_nonexistent_plan(
        self, mock_db: AsyncMock, user_id: UUID, plan_id: UUID
    ):
        """Adding a task to nonexistent/unauthorized plan raises NotFoundError."""
        task_data = PlanTaskCreate(description="New task")

        with patch("app.repositories.plan.add_task_to_plan") as mock_add:
            mock_add.return_value = None  # Plan not found
            service = PlanService(mock_db)

            with pytest.raises(NotFoundError) as exc_info:
                await service.add_task(plan_id, user_id, task_data)

            assert "Plan not found" in str(exc_info.value.message)

    @pytest.mark.anyio
    async def test_update_task(
        self, mock_db: AsyncMock, user_id: UUID, task_id: UUID, sample_task: PlanTask
    ):
        """Updating a task works correctly."""
        update_data = PlanTaskUpdate(status="in_progress")
        sample_task.status = "in_progress"

        with patch("app.repositories.plan.update_task") as mock_update:
            mock_update.return_value = sample_task
            service = PlanService(mock_db)

            result = await service.update_task(task_id, user_id, update_data)

            assert isinstance(result, PlanTaskRead)
            assert result.status == "in_progress"
            mock_update.assert_called_once_with(mock_db, task_id, user_id, update_data)

    @pytest.mark.anyio
    async def test_remove_task(
        self, mock_db: AsyncMock, user_id: UUID, task_id: UUID
    ):
        """Removing a task works correctly."""
        with patch("app.repositories.plan.remove_task_from_plan") as mock_remove:
            mock_remove.return_value = True
            service = PlanService(mock_db)

            result = await service.remove_task(task_id, user_id)

            assert result is True
            mock_remove.assert_called_once_with(mock_db, task_id, user_id)

    @pytest.mark.anyio
    async def test_remove_task_not_found(
        self, mock_db: AsyncMock, user_id: UUID, task_id: UUID
    ):
        """Removing nonexistent task raises NotFoundError."""
        with patch("app.repositories.plan.remove_task_from_plan") as mock_remove:
            mock_remove.return_value = False
            service = PlanService(mock_db)

            with pytest.raises(NotFoundError) as exc_info:
                await service.remove_task(task_id, user_id)

            assert "Task not found" in str(exc_info.value.message)

    @pytest.mark.anyio
    async def test_reorder_tasks(
        self, mock_db: AsyncMock, user_id: UUID, plan_id: UUID, sample_plan: Plan
    ):
        """Reordering tasks updates their positions."""
        task1_id = uuid4()
        task2_id = uuid4()

        sample_plan.tasks = [
            PlanTask(id=task1_id, plan_id=plan_id, description="Task 1", position=0),
            PlanTask(id=task2_id, plan_id=plan_id, description="Task 2", position=1),
        ]

        with (
            patch("app.repositories.plan.reorder_tasks") as mock_reorder,
            patch("app.repositories.plan.get_plan_by_id") as mock_get_plan,
        ):
            mock_reorder.return_value = True  # reorder_tasks returns bool
            mock_get_plan.return_value = sample_plan  # get_plan needs the plan
            service = PlanService(mock_db)

            result = await service.reorder_tasks(
                plan_id, user_id, [task2_id, task1_id]  # Reversed order
            )

            assert isinstance(result, PlanRead)
            mock_reorder.assert_called_once_with(
                mock_db, plan_id, user_id, [task2_id, task1_id]
            )


class TestUserScopeUtilities:
    """Tests for user scoping utility functions."""

    def test_validate_path_blocks_traversal(self):
        """Path traversal attempts are blocked."""
        from app.core.user_scope import UserScopeError, validate_path

        # These should all raise UserScopeError
        with pytest.raises(UserScopeError, match="traversal"):
            validate_path("../other_user/file.txt")

        with pytest.raises(UserScopeError, match="traversal"):
            validate_path("subdir/../../file.txt")

    def test_validate_path_blocks_url_encoding(self):
        """URL-encoded traversal attempts are blocked."""
        from app.core.user_scope import UserScopeError, validate_path

        with pytest.raises(UserScopeError, match="traversal"):
            validate_path("%2e%2e/file.txt")

        with pytest.raises(UserScopeError, match="traversal"):
            validate_path("%2F../file.txt")

    def test_validate_path_accepts_valid_paths(self):
        """Valid paths are accepted."""
        from app.core.user_scope import validate_path

        # These should all pass
        validate_path("file.txt")
        validate_path("subdir/file.txt")
        validate_path("deep/nested/path/file.txt")

    def test_scope_key_adds_prefix(self):
        """scope_key correctly adds user prefix."""
        from app.core.user_scope import scope_key

        user_id = "user123"
        result = scope_key(user_id, "file.txt")
        assert result == "users/user123/file.txt"

        result = scope_key(user_id, "subdir/file.txt")
        assert result == "users/user123/subdir/file.txt"

    def test_get_user_prefix(self):
        """get_user_prefix returns correct prefix."""
        from app.core.user_scope import get_user_prefix

        assert get_user_prefix("user123") == "users/user123/"
        assert get_user_prefix("abc-def-ghi") == "users/abc-def-ghi/"

    def test_is_path_in_user_scope(self):
        """is_path_in_user_scope correctly checks ownership."""
        from app.core.user_scope import is_path_in_user_scope

        user_id = "user123"

        assert is_path_in_user_scope(user_id, "users/user123/file.txt") is True
        assert is_path_in_user_scope(user_id, "users/user123/sub/file.txt") is True
        assert is_path_in_user_scope(user_id, "users/other/file.txt") is False
        assert is_path_in_user_scope(user_id, "file.txt") is False

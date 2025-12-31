"""Tests for Celery worker tasks."""

from unittest.mock import MagicMock, patch

import pytest


class TestExampleTask:
    """Tests for example_task."""

    def test_example_task_success(self):
        """Test example_task completes successfully."""
        from app.worker.tasks.examples import example_task

        # Create a mock for self (the task)
        mock_self = MagicMock()
        mock_self.request.id = "test-task-id"

        with patch("app.worker.tasks.examples.time.sleep"):
            result = example_task.run(mock_self, "test message")

        assert result["status"] == "completed"
        assert "test message" in result["message"]
        assert result["task_id"] == "test-task-id"

    def test_example_task_retry_on_error(self):
        """Test example_task retries on error."""
        from app.worker.tasks.examples import example_task

        mock_self = MagicMock()
        mock_self.request.id = "test-task-id"
        mock_self.request.retries = 0

        with patch("app.worker.tasks.examples.time.sleep", side_effect=Exception("Test error")):
            mock_self.retry = MagicMock(side_effect=Exception("Retry"))
            with pytest.raises(Exception, match="Retry"):
                example_task.run(mock_self, "test message")
            mock_self.retry.assert_called_once()


class TestLongRunningTask:
    """Tests for long_running_task."""

    def test_long_running_task_completes(self):
        """Test long_running_task completes with progress."""
        from app.worker.tasks.examples import long_running_task

        mock_self = MagicMock()
        mock_self.request.id = "test-task-id"

        with patch("app.worker.tasks.examples.time.sleep"):
            result = long_running_task.run(mock_self, duration=3)

        assert result["status"] == "completed"
        assert result["duration"] == 3
        # Check progress updates were made
        assert mock_self.update_state.call_count == 3


class TestSendEmailTask:
    """Tests for send_email_task."""

    def test_send_email_task_success(self):
        """Test send_email_task sends email."""
        from app.worker.tasks.examples import send_email_task

        with patch("app.worker.tasks.examples.time.sleep"):
            result = send_email_task("test@example.com", "Subject", "Body")

        assert result["status"] == "sent"
        assert result["to"] == "test@example.com"
        assert result["subject"] == "Subject"


class TestCeleryAppConfiguration:
    """Tests for Celery app configuration."""

    def test_celery_app_exists(self):
        """Test Celery app is configured."""
        from app.worker.celery_app import celery_app

        assert celery_app is not None
        assert celery_app.main == "arachne_fullstack"

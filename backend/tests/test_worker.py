"""Tests for Celery worker tasks."""

from unittest.mock import MagicMock, patch

import pytest


class TestExampleTask:
    """Tests for example_task."""

    def test_example_task_success(self):
        """Test example_task completes successfully."""
        from app.worker.tasks.examples import example_task

        with patch("app.worker.tasks.examples.time.sleep"):
            # Use apply() which runs the task synchronously and returns an EagerResult
            result = example_task.apply(args=["test message"])

        assert result.successful()
        assert result.result["status"] == "completed"
        assert "test message" in result.result["message"]

    def test_example_task_retry_on_error(self):
        """Test example_task retries on error."""
        from celery.exceptions import Retry

        from app.worker.tasks.examples import example_task

        with patch("app.worker.tasks.examples.time.sleep", side_effect=Exception("Test error")):
            # When an exception is raised and retry is called, Celery raises Retry
            # Using apply() with throw=False captures the exception
            result = example_task.apply(args=["test message"], throw=False)

        # Task should have failed (retried)
        assert result.failed()


class TestLongRunningTask:
    """Tests for long_running_task."""

    def test_long_running_task_completes(self):
        """Test long_running_task completes with progress."""
        from app.worker.tasks.examples import long_running_task

        with patch("app.worker.tasks.examples.time.sleep"):
            result = long_running_task.apply(kwargs={"duration": 3})

        assert result.successful()
        assert result.result["status"] == "completed"
        assert result.result["duration"] == 3


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

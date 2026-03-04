"""Tests for the Celery agent run task."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.agent_job import AgentJobService


@pytest.mark.anyio
async def test_run_agent_task_publishes_events():
    """Test that the async inner function publishes events to Redis Stream."""
    mock_job_service = MagicMock(spec=AgentJobService)
    mock_job_service.publish_event = AsyncMock()
    mock_job_service.complete_job = AsyncMock()
    mock_job_service.is_cancellation_requested = AsyncMock(return_value=False)

    from app.worker.tasks.agent_run import _run_non_streaming

    mock_result = MagicMock()
    mock_result.output = "Hello from agent"
    mock_result.all_messages.return_value = []

    mock_agent = MagicMock()
    mock_agent.agent = MagicMock()
    mock_agent.agent.run = AsyncMock(return_value=mock_result)
    mock_agent.model_name = "test-model"

    mock_deps = MagicMock()

    with patch("app.db.session.get_db_context") as mock_db_ctx:
        mock_db = AsyncMock()
        mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.worker.tasks.agent_run._persist_result", new_callable=AsyncMock):
            await _run_non_streaming(
                assistant=mock_agent,
                agent_input="Hello",
                deps=mock_deps,
                model_history=[],
                usage_limits=MagicMock(),
                job_service=mock_job_service,
                job_id="job-1",
                conversation_id=str(uuid4()),
                user_message="Hello",
                assistant_message_id=None,
                tool_call_mapping={},
                thinking_content_buffer=[],
            )

    # Verify events were published
    event_calls = mock_job_service.publish_event.call_args_list
    event_types = [call[0][1] for call in event_calls]
    assert "model_request_start" in event_types
    assert "text_delta" in event_types
    assert "final_result" in event_types
    assert "complete" in event_types

    # Verify job was completed
    mock_job_service.complete_job.assert_called_once()


@pytest.mark.anyio
async def test_run_agent_task_handles_cancellation():
    """Test that cancellation is detected and handled."""
    mock_job_service = MagicMock(spec=AgentJobService)
    mock_job_service.publish_event = AsyncMock()
    mock_job_service.complete_job = AsyncMock()
    mock_job_service.is_cancellation_requested = AsyncMock(return_value=True)

    from app.worker.tasks.agent_run import _run_non_streaming
    from pydantic_ai.messages import ModelResponse, TextPart

    mock_result = MagicMock()
    mock_result.output = "partial"
    mock_msg = ModelResponse(parts=[TextPart(content="partial")])
    mock_result.all_messages.return_value = [mock_msg]

    mock_agent = MagicMock()
    mock_agent.agent = MagicMock()
    mock_agent.agent.run = AsyncMock(return_value=mock_result)
    mock_agent.model_name = "test-model"

    mock_deps = MagicMock()

    with patch("app.db.session.get_db_context") as mock_db_ctx:
        mock_db = AsyncMock()
        mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await _run_non_streaming(
            assistant=mock_agent,
            agent_input="Hello",
            deps=mock_deps,
            model_history=[],
            usage_limits=MagicMock(),
            job_service=mock_job_service,
            job_id="job-1",
            conversation_id=str(uuid4()),
            user_message="Hello",
            assistant_message_id=None,
            tool_call_mapping={},
            thinking_content_buffer=[],
        )

    # Verify cancelled event was published
    event_calls = mock_job_service.publish_event.call_args_list
    event_types = [call[0][1] for call in event_calls]
    assert "cancelled" in event_types

    # Verify job completed with CANCELLED status
    mock_job_service.complete_job.assert_called_once()
    complete_kwargs = mock_job_service.complete_job.call_args[1]
    assert complete_kwargs["status"] == "cancelled"


@pytest.mark.anyio
async def test_run_agent_task_handles_errors():
    """Test that errors are published and job is marked failed."""
    mock_job_service = MagicMock(spec=AgentJobService)
    mock_job_service.publish_event = AsyncMock()
    mock_job_service.complete_job = AsyncMock()

    from app.worker.tasks.agent_run import _run_agent_async

    with (
        patch("app.worker.tasks.agent_run._get_redis_client") as mock_get_redis,
        patch("app.worker.tasks.agent_run.AgentJobService", return_value=mock_job_service),
        patch("app.agents.providers.registry.get_provider", side_effect=ValueError("Unknown model")),
    ):
        mock_redis = MagicMock()
        mock_redis.connect = AsyncMock()
        mock_redis.close = AsyncMock()
        mock_get_redis.return_value = mock_redis

        await _run_agent_async(
            job_id="job-1",
            conversation_id="conv-1",
            user_id="user-1",
            user_email="test@test.com",
            user_message="Hello",
            model_name="bad-model",
            system_prompt="test",
            message_history=[],
            attachments=[],
        )

    # Verify error event was published
    event_calls = mock_job_service.publish_event.call_args_list
    event_types = [call[0][1] for call in event_calls]
    assert "error" in event_types

    # Verify job marked as failed
    mock_job_service.complete_job.assert_called_once()
    complete_kwargs = mock_job_service.complete_job.call_args[1]
    assert complete_kwargs["status"] == "failed"

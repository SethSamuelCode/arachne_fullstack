"""Celery task for running the PydanticAI agent in the background."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from celery import shared_task

from app.core.config import settings
from app.services.agent_job import AgentJobService, JobStatus

logger = logging.getLogger(__name__)


def _get_redis_client():
    """Create a new Redis client for the worker."""
    from app.clients.redis import RedisClient

    return RedisClient(settings.REDIS_URL)


def _get_conversation_service(db):
    """Get conversation service instance."""
    from app.services.conversation import ConversationService

    return ConversationService(db)


async def _run_agent_async(
    *,
    job_id: str,
    conversation_id: str,
    user_id: str,
    user_email: str,
    user_message: str,
    model_name: str,
    system_prompt: str,
    message_history: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
) -> None:
    """Async inner function that runs the agent and publishes events."""
    from app.agents.assistant import Deps, get_agent
    from app.agents.context_optimizer import optimize_context_window
    from app.agents.providers.registry import get_provider
    from app.agents.tools import get_tool_definitions
    from app.api.routes.v1.agent import build_multimodal_input, serialize_tool_content
    from app.core.utils import serialize_tool_result_for_db
    from app.db.session import get_db_context
    from app.schemas.attachment import AttachmentInMessage
    from app.schemas.conversation import MessageCreate, ToolCallComplete, ToolCallCreate
    from pydantic_ai import UsageLimits

    redis = _get_redis_client()
    await redis.connect()

    try:
        job_service = AgentJobService(redis)

        provider = get_provider(model_name)
        deps = Deps(user_id=user_id, user_name=user_email)

        # Build multimodal input if attachments present
        parsed_attachments = [AttachmentInMessage(**a) for a in attachments] if attachments else []
        agent_input = await build_multimodal_input(user_message, parsed_attachments, user_id)

        # Optimize context window
        tool_definitions = get_tool_definitions()
        optimized = await optimize_context_window(
            history=message_history,
            provider=provider,
            system_prompt=system_prompt,
            tool_definitions=tool_definitions,
            redis_client=redis,
        )
        model_history = optimized["history"]

        # Create the agent
        assistant = get_agent(
            system_prompt=optimized["system_prompt"],
            provider=provider,
            cached_prompt_name=optimized["cached_prompt_name"],
            skip_tool_registration=optimized["skip_tool_registration"],
        )

        assistant_message_id: UUID | None = None
        tool_call_mapping: dict[str, UUID] = {}
        thinking_content_buffer: list[str] = []

        usage_limits = UsageLimits(
            request_limit=settings.AGENT_MAX_REQUESTS,
            tool_calls_limit=settings.AGENT_MAX_TOOL_CALLS,
        )

        if not provider.supports_streaming:
            await _run_non_streaming(
                assistant=assistant,
                agent_input=agent_input,
                deps=deps,
                model_history=model_history,
                usage_limits=usage_limits,
                job_service=job_service,
                job_id=job_id,
                conversation_id=conversation_id,
                user_message=user_message,
                assistant_message_id=assistant_message_id,
                tool_call_mapping=tool_call_mapping,
                thinking_content_buffer=thinking_content_buffer,
            )
        else:
            await _run_streaming(
                assistant=assistant,
                agent_input=agent_input,
                deps=deps,
                model_history=model_history,
                usage_limits=usage_limits,
                job_service=job_service,
                job_id=job_id,
                conversation_id=conversation_id,
                user_message=user_message,
                assistant_message_id=assistant_message_id,
                tool_call_mapping=tool_call_mapping,
                thinking_content_buffer=thinking_content_buffer,
            )

    except Exception as e:
        logger.exception(f"Agent run failed for job {job_id}: {e}")
        try:
            await job_service.publish_event(job_id, "error", {"message": str(e)})
            await job_service.complete_job(job_id, status=JobStatus.FAILED)
        except Exception:
            logger.exception("Failed to publish error event")
    finally:
        await redis.close()


async def _run_non_streaming(
    *,
    assistant,
    agent_input,
    deps,
    model_history,
    usage_limits,
    job_service: AgentJobService,
    job_id: str,
    conversation_id: str,
    user_message: str,
    assistant_message_id: UUID | None,
    tool_call_mapping: dict[str, UUID],
    thinking_content_buffer: list[str],
) -> None:
    """Non-streaming agent execution path."""
    from app.api.routes.v1.agent import serialize_tool_content
    from app.core.utils import serialize_tool_result_for_db
    from app.db.session import get_db_context
    from app.schemas.conversation import MessageCreate, ToolCallComplete, ToolCallCreate
    from pydantic_ai.messages import ModelRequest, ModelResponse, ThinkingPart, ToolCallPart, ToolReturnPart

    async with get_db_context() as agent_db:
        deps.db = agent_db
        result = await assistant.agent.run(
            agent_input,
            deps=deps,
            message_history=model_history,
            usage_limits=usage_limits,
        )

    await job_service.publish_event(job_id, "model_request_start", {})

    for message in result.all_messages():
        if await job_service.is_cancellation_requested(job_id):
            await _handle_cancellation(
                job_service, job_id, conversation_id, assistant_message_id, thinking_content_buffer
            )
            return

        if isinstance(message, ModelResponse):
            for part in message.parts:
                if isinstance(part, ThinkingPart) and part.content:
                    thinking_content_buffer.append(part.content)
                    if settings.AGENT_STREAM_THINKING:
                        await job_service.publish_event(
                            job_id, "thinking_delta", {"index": 0, "content": part.content}
                        )
                elif isinstance(part, ToolCallPart):
                    args = part.args if isinstance(part.args, dict) else {}
                    await job_service.publish_event(job_id, "tool_call", {
                        "tool_name": part.tool_name,
                        "args": args,
                        "tool_call_id": part.tool_call_id,
                    })
                    assistant_message_id = await _persist_tool_call_start(
                        conversation_id, assistant_message_id, assistant,
                        part.tool_call_id, part.tool_name, args, tool_call_mapping,
                    )

        elif isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, ToolReturnPart):
                    content_parts = serialize_tool_content(part.content)
                    await job_service.publish_event(job_id, "tool_result", {
                        "tool_call_id": part.tool_call_id,
                        "content": content_parts,
                    })
                    await _persist_tool_call_result(
                        part.tool_call_id, part.content, tool_call_mapping
                    )

    # Publish final text
    await job_service.publish_event(job_id, "text_delta", {"index": 0, "content": result.output})
    await job_service.publish_event(job_id, "final_result", {"output": result.output})

    # Persist and complete
    await _persist_result(
        conversation_id, result.output, assistant_message_id,
        thinking_content_buffer, getattr(assistant, "model_name", None),
        user_message, job_service, job_id,
    )
    await job_service.publish_event(job_id, "complete", {"conversation_id": conversation_id})
    await job_service.complete_job(job_id, status=JobStatus.COMPLETED)


async def _run_streaming(
    *,
    assistant,
    agent_input,
    deps,
    model_history,
    usage_limits,
    job_service: AgentJobService,
    job_id: str,
    conversation_id: str,
    user_message: str,
    assistant_message_id: UUID | None,
    tool_call_mapping: dict[str, UUID],
    thinking_content_buffer: list[str],
) -> None:
    """Streaming agent execution path."""
    from app.api.routes.v1.agent import serialize_tool_content
    from app.core.utils import serialize_tool_result_for_db
    from app.db.session import get_db_context
    from app.repositories.conversation import update_message_content
    from app.schemas.conversation import MessageCreate, ToolCallComplete, ToolCallCreate
    from pydantic_ai import (
        Agent,
        FinalResultEvent,
        FunctionToolCallEvent,
        FunctionToolResultEvent,
        PartDeltaEvent,
        PartStartEvent,
        TextPartDelta,
        ThinkingPartDelta,
        ToolCallPartDelta,
    )
    from pydantic_ai.messages import TextPart, ThinkingPart

    async with get_db_context() as agent_db:
        deps.db = agent_db

        async with assistant.agent.iter(
            agent_input,
            deps=deps,
            message_history=model_history,
            usage_limits=usage_limits,
        ) as agent_run:
            async for node in agent_run:
                # Check cancellation at each node
                if await job_service.is_cancellation_requested(job_id):
                    await _handle_cancellation(
                        job_service, job_id, conversation_id,
                        assistant_message_id, thinking_content_buffer,
                    )
                    return

                if Agent.is_model_request_node(node):
                    await job_service.publish_event(job_id, "model_request_start", {})

                    async with node.stream(agent_run.ctx) as request_stream:
                        async for event in request_stream:
                            if isinstance(event, PartStartEvent):
                                if isinstance(event.part, TextPart) and event.part.content:
                                    await job_service.publish_event(
                                        job_id, "text_delta",
                                        {"index": event.index, "content": event.part.content},
                                    )
                                elif isinstance(event.part, ThinkingPart) and event.part.content:
                                    thinking_content_buffer.append(event.part.content)
                                    if settings.AGENT_STREAM_THINKING:
                                        await job_service.publish_event(
                                            job_id, "thinking_delta",
                                            {"index": event.index, "content": event.part.content},
                                        )

                            elif isinstance(event, PartDeltaEvent):
                                if isinstance(event.delta, TextPartDelta):
                                    await job_service.publish_event(
                                        job_id, "text_delta",
                                        {"index": event.index, "content": event.delta.content_delta},
                                    )
                                elif isinstance(event.delta, ThinkingPartDelta) and event.delta.content_delta:
                                    thinking_content_buffer.append(event.delta.content_delta)
                                    if settings.AGENT_STREAM_THINKING:
                                        await job_service.publish_event(
                                            job_id, "thinking_delta",
                                            {"index": event.index, "content": event.delta.content_delta},
                                        )
                                elif isinstance(event.delta, ToolCallPartDelta):
                                    await job_service.publish_event(
                                        job_id, "tool_call_delta",
                                        {"index": event.index, "args_delta": event.delta.args_delta},
                                    )

                            elif isinstance(event, FinalResultEvent):
                                await job_service.publish_event(
                                    job_id, "final_result_start", {"tool_name": event.tool_name},
                                )

                elif Agent.is_call_tools_node(node):
                    await job_service.publish_event(job_id, "call_tools_start", {})

                    async with node.stream(agent_run.ctx) as handle_stream:
                        async for event in handle_stream:
                            if isinstance(event, FunctionToolCallEvent):
                                await job_service.publish_event(job_id, "tool_call", {
                                    "tool_name": event.part.tool_name,
                                    "args": event.part.args,
                                    "tool_call_id": event.part.tool_call_id,
                                })
                                assistant_message_id = await _persist_tool_call_start(
                                    conversation_id, assistant_message_id, assistant,
                                    event.part.tool_call_id, event.part.tool_name,
                                    event.part.args if isinstance(event.part.args, dict) else {},
                                    tool_call_mapping,
                                )

                            elif isinstance(event, FunctionToolResultEvent):
                                content_parts = serialize_tool_content(event.result.content)
                                await job_service.publish_event(job_id, "tool_result", {
                                    "tool_call_id": event.tool_call_id,
                                    "content": content_parts,
                                })
                                await _persist_tool_call_result(
                                    event.tool_call_id, event.result.content, tool_call_mapping
                                )

                elif Agent.is_end_node(node) and agent_run.result is not None:
                    await job_service.publish_event(
                        job_id, "final_result", {"output": agent_run.result.output},
                    )

            # Persist final result
            if agent_run.result:
                await _persist_result(
                    conversation_id, agent_run.result.output, assistant_message_id,
                    thinking_content_buffer, getattr(assistant, "model_name", None),
                    user_message, job_service, job_id,
                )
            elif assistant_message_id is not None:
                try:
                    async with get_db_context() as db:
                        await update_message_content(
                            db, assistant_message_id, "(Tool execution interrupted)",
                        )
                except Exception as e:
                    logger.warning(f"Failed to update interrupted message: {e}")

    # Publish complete and finalize
    await job_service.publish_event(job_id, "complete", {"conversation_id": conversation_id})
    await job_service.complete_job(job_id, status=JobStatus.COMPLETED)


async def _persist_tool_call_start(
    conversation_id: str,
    assistant_message_id: UUID | None,
    assistant,
    tool_call_id: str,
    tool_name: str,
    args: dict,
    tool_call_mapping: dict[str, UUID],
) -> UUID:
    """Persist tool call start to DB. Creates assistant message if needed. Returns assistant_message_id."""
    from app.db.session import get_db_context
    from app.schemas.conversation import MessageCreate, ToolCallCreate

    try:
        if assistant_message_id is None:
            async with get_db_context() as db:
                conv_svc = _get_conversation_service(db)
                assistant_msg = await conv_svc.add_message(
                    UUID(conversation_id),
                    MessageCreate(
                        role="assistant",
                        content="",
                        model_name=getattr(assistant, "model_name", None),
                    ),
                )
                assistant_message_id = assistant_msg.id

        async with get_db_context() as db:
            conv_svc = _get_conversation_service(db)
            tc = await conv_svc.start_tool_call(
                assistant_message_id,
                ToolCallCreate(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    args=args,
                    started_at=datetime.now(UTC),
                ),
            )
            tool_call_mapping[tool_call_id] = tc.id
    except Exception as e:
        logger.warning(f"Failed to persist tool call start: {e}")

    return assistant_message_id


async def _persist_tool_call_result(
    tool_call_id: str,
    content: Any,
    tool_call_mapping: dict[str, UUID],
) -> None:
    """Persist tool call result to DB."""
    from app.core.utils import serialize_tool_result_for_db
    from app.db.session import get_db_context
    from app.schemas.conversation import ToolCallComplete

    if tool_call_id not in tool_call_mapping:
        return

    try:
        db_tc_id = tool_call_mapping[tool_call_id]
        result_text = serialize_tool_result_for_db(content)
        is_error = isinstance(content, dict) and content.get("error") is True

        async with get_db_context() as db:
            conv_svc = _get_conversation_service(db)
            await conv_svc.complete_tool_call(
                db_tc_id,
                ToolCallComplete(
                    result=result_text,
                    completed_at=datetime.now(UTC),
                    success=not is_error,
                ),
            )
    except Exception as e:
        logger.warning(f"Failed to persist tool result: {e}")


async def _handle_cancellation(
    job_service: AgentJobService,
    job_id: str,
    conversation_id: str,
    assistant_message_id: UUID | None,
    thinking_content_buffer: list[str],
) -> None:
    """Handle a cancellation request: persist partial results and notify."""
    logger.info(f"Cancellation requested for job {job_id}")

    if assistant_message_id is not None:
        try:
            from app.db.session import get_db_context
            from app.repositories.conversation import update_message_content

            async with get_db_context() as db:
                partial_thinking = "".join(thinking_content_buffer) if thinking_content_buffer else None
                await update_message_content(
                    db, assistant_message_id, "(Cancelled by user)",
                    thinking_content=partial_thinking,
                )
        except Exception as e:
            logger.warning(f"Failed to persist partial result on cancel: {e}")

    await job_service.publish_event(job_id, "cancelled", {"conversation_id": conversation_id})
    await job_service.complete_job(job_id, status=JobStatus.CANCELLED)


async def _persist_result(
    conversation_id: str,
    output: str,
    assistant_message_id: UUID | None,
    thinking_content_buffer: list[str],
    model_name: str | None,
    user_message: str,
    job_service: AgentJobService,
    job_id: str,
) -> None:
    """Persist the assistant response and generate title."""
    from app.db.session import get_db_context
    from app.schemas.conversation import MessageCreate

    final_thinking = "".join(thinking_content_buffer) if thinking_content_buffer else None

    try:
        async with get_db_context() as db:
            conv_svc = _get_conversation_service(db)
            if assistant_message_id is not None:
                from app.repositories.conversation import update_message_content

                await update_message_content(
                    db, assistant_message_id, output, thinking_content=final_thinking,
                )
            else:
                await conv_svc.add_message(
                    UUID(conversation_id),
                    MessageCreate(
                        role="assistant",
                        content=output,
                        thinking_content=final_thinking,
                        model_name=model_name,
                    ),
                )
    except Exception as e:
        logger.warning(f"Failed to persist assistant response: {e}")

    # Generate title
    try:
        async with get_db_context() as db:
            conv_svc = _get_conversation_service(db)
            title = await conv_svc.generate_and_set_title(
                UUID(conversation_id), user_message, output,
            )
            if title:
                await job_service.publish_event(job_id, "conversation_updated", {
                    "conversation_id": conversation_id,
                    "title": title,
                })
    except Exception as e:
        logger.warning(f"Failed to generate conversation title: {e}")


@shared_task(bind=True, name="agent.run", acks_late=True, max_retries=0)
def run_agent_task(
    self,
    job_id: str,
    conversation_id: str,
    user_id: str,
    user_email: str,
    user_message: str,
    model_name: str,
    system_prompt: str,
    message_history: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
) -> dict[str, str]:
    """Celery task wrapper — runs the async agent loop."""
    asyncio.run(
        _run_agent_async(
            job_id=job_id,
            conversation_id=conversation_id,
            user_id=user_id,
            user_email=user_email,
            user_message=user_message,
            model_name=model_name,
            system_prompt=system_prompt,
            message_history=message_history,
            attachments=attachments,
        )
    )
    return {"job_id": job_id, "status": "completed"}

import logging
from typing import Annotated, Any, Literal, TypeVar
from uuid import UUID, uuid4

from pydantic import Field
from pydantic_ai import Agent, BinaryContent, RunContext, ToolReturn
from tavily import TavilyClient

from app.agents.providers.registry import DEFAULT_MODEL_ID, get_provider
from app.agents.tools.academic_search import (
    list_arxiv_categories_impl,
    search_arxiv_impl,
    search_openalex_impl,
    search_semantic_scholar_bulk_impl,
    search_semantic_scholar_impl,
)
from app.agents.tools.datetime_tool import get_current_datetime
from app.agents.tools.decorators import safe_tool
from app.agents.tools.extract_webpage import extract_url
from app.agents.tools.s3_image import s3_fetch_image_impl
from app.core.config import settings
from app.schemas.assistant import Deps
from app.schemas.plan import PlanCreate, PlanRead, PlanTaskCreate, PlanTaskUpdate, PlanUpdate
from app.schemas.spawn_agent_deps import SpawnAgentDeps

# Type alias for image generation model selection
ImageModelName = Literal[
    "gemini-3-pro-image-preview",
    "imagen-4.0-generate-001",
    "imagen-4.0-ultra-generate-001",
    "imagen-4.0-fast-generate-001",
]

TDeps = TypeVar("TDeps", bound=Deps | SpawnAgentDeps)

def _stringify(output: Any) -> str:
    """Convert various output types to a string representation."""
    if isinstance(output, str):
        return output
    elif isinstance(output, dict) or hasattr(output, "__str__"):
        return str(output)
    else:
        return repr(output)

def register_tools(agent: Agent[TDeps, str]) -> None:
    """Register tools to the given agent."""

    @agent.tool
    @safe_tool
    async def search_web(
        ctx: RunContext[TDeps],
        query: Annotated[str, Field(description="Search query string. Be specific and include relevant keywords.")],
        max_results: Annotated[int, Field(description="Maximum number of results to return. Higher values provide more context but increase latency.")] = 5,
    ) -> str | dict[str, Any]:
        """
        <tool_def>
            <intent>
                Search the web for current information, news, or general queries using Tavily.
            </intent>

            <constraints>
                <rule>Use for real-time information needs (news, current events, recent data).</rule>
                <rule>Do NOT use for static knowledge already in your training data.</rule>
                <rule>Prefer extract_webpage if you already have a specific URL.</rule>
            </constraints>

            <error_handling>
                <error code="InvalidAPIKey">Tavily API key is missing or invalid.</error>
                <error code="RateLimitExceeded">Too many requests, wait and retry.</error>
                <error code="NetworkError">Connection issue, retry after a moment.</error>
            </error_handling>

            <returns>
                Formatted search results separated by "---", each containing title, URL, and content snippet.
                Returns "No search results found." if no matches.
                On error: dict with 'error' key and details.
            </returns>
        </tool_def>
        """
        client = TavilyClient(api_key=settings.TAVILY_API_KEY)
        response = client.search(query=query, search_depth="basic", max_results=max_results)
        results = []
        for r in response.get("results", []):
            title = r.get("title", "")
            url = r.get("url", "")
            snippet = r.get("content", "") or ""
            results.append(f"**{title}**\nURL: {url}\nContent: {snippet}\n")
        return "\n---\n".join(results) if results else "No search results found."

    @agent.tool
    async def current_datetime(ctx: RunContext[TDeps]) -> str:
        """
        <tool_def>
            <intent>
                Get the current date and time in ISO format with timezone.
            </intent>

            <constraints>
                <rule>Use when temporal context is needed for calculations or comparisons.</rule>
                <rule>Do NOT use repeatedly in the same conversation—cache the result.</rule>
            </constraints>

            <returns>
                ISO 8601 formatted datetime string with timezone (e.g., "2026-01-26T14:30:00+00:00").
            </returns>
        </tool_def>
        """
        return get_current_datetime()

    @agent.tool
    async def spawn_agent(
        ctx: RunContext[TDeps],
        user_input: Annotated[str, Field(
            description="The specific instructions or question for the sub-agent. Must be fully self-contained as sub-agents have no conversation history."
        )],
        system_prompt: Annotated[str | None, Field(
            description="Define the sub-agent's role and expertise (e.g., 'You are a Python security expert'). Defaults to generic assistant."
        )] = None,
        model_name: Annotated[str | None, Field(
            description="Model ID to use. Options: 'gemini-2.5-flash-lite' (fast/cheap), "
                        "'gemini-2.5-flash' (default, standard tasks), "
                        "'gemini-2.5-pro' (complex reasoning), "
                        "'gemini-3-flash-preview' (fast with reasoning), "
                        "'gemini-3-pro-preview' (max reasoning), "
                        "'gemini-3.1-pro-preview' (improved Gemini 3 Pro), "
                        "'glm-5' (Vertex AI). Use stronger models only when needed."
        )] = None,
    ) -> str:
        """
        <tool_def>
            <intent>
                Delegate a sub-task to a new agent with a fresh context window.
                The sub-agent has the same tools available as you do.
            </intent>

            <logic>
                <step>Determine if task requires isolated reasoning or a stronger model.</step>
                <step>Ensure user_input is fully self-contained (sub-agents have no history).</step>
                <step>Select model based on task complexity.</step>
            </logic>

            <model_guide>
                <model name="gemini-2.5-flash-lite">Simple lookups, formatting, low latency.</model>
                <model name="gemini-2.5-flash">Standard tasks, summarization, general Q&amp;A.</model>
                <model name="gemini-2.5-pro">Complex reasoning, coding, creative writing.</model>
                <model name="gemini-3-flash-preview">High speed with moderate reasoning.</model>
                <model name="gemini-3-pro-preview">MAX REASONING. Architecture, security analysis, very hard problems.</model>
            </model_guide>

            <constraints>
                <rule>Max recursion depth is 10.</rule>
                <rule>Do NOT use for simple arithmetic or basic lookups.</rule>
                <rule>Do NOT spawn agents recursively for trivial sub-tasks.</rule>
            </constraints>

            <returns>
                The sub-agent's final text response as a string.
                On depth limit: "Error: spawn depth limit reached ({depth})."
            </returns>
        </tool_def>
        """
        import logging

        from app.core.cache_manager import get_subagent_cached_content

        logger = logging.getLogger(__name__)

        spawn_depth: int = getattr(ctx.deps, "spawn_depth", 0)
        spawn_max_depth: int = getattr(ctx.deps, "spawn_max_depth", 10)
        if spawn_depth > 0 and spawn_depth >= spawn_max_depth:
            return f"Error: spawn depth limit reached ({spawn_max_depth})."

        # Default system prompt for sub-agents
        DEFAULT_SUBAGENT_PROMPT = "You are a helpful AI assistant."
        effective_system_prompt = (
            system_prompt if system_prompt is not None else DEFAULT_SUBAGENT_PROMPT
        )
        effective_model = model_name if model_name is not None else DEFAULT_MODEL_ID

        # Try to get cached content for default sub-agent prompt
        cached_content_name: str | None = None
        skip_tool_registration = False

        # Only use cache if using the default prompt (cached prompts match)
        if effective_system_prompt == DEFAULT_SUBAGENT_PROMPT:
            cached_content_name = await get_subagent_cached_content(
                model_name=str(effective_model)
            )
            if cached_content_name:
                skip_tool_registration = True
                logger.debug(f"Sub-agent using cached content: {cached_content_name}")

        child_deps = SpawnAgentDeps(
            user_id=ctx.deps.user_id if hasattr(ctx.deps, "user_id") else None,
            user_name=ctx.deps.user_name if hasattr(ctx.deps, "user_name") else None,
            metadata=ctx.deps.metadata if hasattr(ctx.deps, "metadata") else {},
            system_prompt=effective_system_prompt,
            model_name=effective_model,
            spawn_depth=spawn_depth + 1,
            spawn_max_depth=spawn_max_depth,
            cached_content_name=cached_content_name,
            skip_tool_registration=skip_tool_registration,
        )

        # Delegate sub-agent model creation to the registry provider
        sub_provider = get_provider(str(child_deps.model_name))
        sub_model = sub_provider.create_pydantic_model(
            using_cached_tools=skip_tool_registration,
            cached_content_name=cached_content_name,
        )

        # Build agent kwargs - omit system_prompt if using cached content
        agent_kwargs: dict[str, Any] = {
            "deps_type": SpawnAgentDeps,
            "model": sub_model,
        }
        if not skip_tool_registration:
            agent_kwargs["system_prompt"] = child_deps.system_prompt or DEFAULT_SUBAGENT_PROMPT

        sub_agent = Agent(**agent_kwargs)

        # Only register tools if not using cached content
        if not skip_tool_registration:
            register_tools(sub_agent)
        else:
            logger.debug("Skipping sub-agent tool registration (tools in cache)")

        result = await sub_agent.run(user_input, deps=child_deps)
        return _stringify(result.output)

    @agent.tool
    async def create_plan(
        ctx: RunContext[TDeps],
        plan: Annotated[PlanCreate, Field(
            description="The plan object with name, description, optional notes, and initial tasks."
        )],
    ) -> str:
        """
        <tool_def>
            <intent>
                Create a new structured plan with a list of tasks.
                Plans are user-scoped—only the creating user can access them.
            </intent>

            <constraints>
                <rule>Plans require a name and description.</rule>
                <rule>Tasks can be added at creation or later via add_task_to_plan.</rule>
                <rule>User ID is required (auto-provided from context).</rule>
            </constraints>

            <returns>
                On success: The UUID of the created plan (string).
                On error: "Error: ..." message describing the failure.
            </returns>
        </tool_def>
        """
        from app.db.session import get_db_context
        from app.services.plan import PlanService

        logger = logging.getLogger(__name__)

        if not ctx.deps.user_id:
            return "Error: User ID is required to create a plan."

        try:
            user_uuid = UUID(ctx.deps.user_id)
            async with get_db_context() as db:
                plan_service = PlanService(db)
                created_plan = await plan_service.create_plan(user_uuid, plan)
                return str(created_plan.id)
        except Exception as e:
            logger.exception("Error creating plan")
            return f"Error creating plan: {e}"

    @agent.tool
    async def get_plan(
        ctx: RunContext[TDeps],
        plan_id: Annotated[str, Field(description="The UUID of the plan to retrieve.")],
    ) -> PlanRead | str:
        """
        <tool_def>
            <intent>
                Retrieve a plan by its ID, including all tasks and status information.
            </intent>

            <constraints>
                <rule>You can only access your own plans.</rule>
                <rule>Returns error message if plan not found or unauthorized.</rule>
            </constraints>

            <returns>
                On success: PlanRead object with id, name, description, notes, is_completed, tasks[], timestamps.
                On error: "Plan not found: {id}" or "Invalid plan ID format: {id}" or "Error: ...".
            </returns>
        </tool_def>
        """
        from app.core.exceptions import NotFoundError
        from app.db.session import get_db_context
        from app.services.plan import PlanService

        logger = logging.getLogger(__name__)

        if not ctx.deps.user_id:
            return "Error: User ID is required to get a plan."

        try:
            user_uuid = UUID(ctx.deps.user_id)
            plan_uuid = UUID(plan_id)
            async with get_db_context() as db:
                plan_service = PlanService(db)
                plan = await plan_service.get_plan(plan_uuid, user_uuid)
                return plan
        except NotFoundError:
            return f"Plan not found: {plan_id}"
        except ValueError:
            return f"Invalid plan ID format: {plan_id}"
        except Exception as e:
            logger.exception("Error getting plan")
            return f"Error getting plan: {e}"

    @agent.tool
    async def update_plan(
        ctx: RunContext[TDeps],
        plan_id: Annotated[str, Field(description="The UUID of the plan to update.")],
        plan_data: Annotated[PlanUpdate, Field(
            description="Partial update data. Only include fields you want to change (name, description, notes, is_completed)."
        )],
    ) -> str:
        """
        <tool_def>
            <intent>
                Update an existing plan with partial update semantics.
                Only fields explicitly provided will be updated.
            </intent>

            <constraints>
                <rule>This tool updates the PLAN itself, NOT tasks.</rule>
                <rule>To update tasks, use update_task.</rule>
                <rule>To add tasks, use add_task_to_plan.</rule>
                <rule>To remove tasks, use remove_task_from_plan.</rule>
            </constraints>

            <returns>
                On success: "Plan {plan_id} updated successfully."
                On error: "Plan not found: {id}" or "Invalid plan ID format: {id}" or "Error: ...".
            </returns>
        </tool_def>
        """
        from app.core.exceptions import NotFoundError
        from app.db.session import get_db_context
        from app.services.plan import PlanService

        logger = logging.getLogger(__name__)

        if not ctx.deps.user_id:
            return "Error: User ID is required to update a plan."

        try:
            user_uuid = UUID(ctx.deps.user_id)
            plan_uuid = UUID(plan_id)
            async with get_db_context() as db:
                plan_service = PlanService(db)
                await plan_service.update_plan(plan_uuid, user_uuid, plan_data)
                return f"Plan {plan_id} updated successfully."
        except NotFoundError:
            return f"Plan not found: {plan_id}"
        except ValueError:
            return f"Invalid plan ID format: {plan_id}"
        except Exception as e:
            logger.exception("Error updating plan")
            return f"Error updating plan: {e}"

    @agent.tool
    async def delete_plan(
        ctx: RunContext[TDeps],
        plan_id: Annotated[str, Field(description="The UUID of the plan to delete.")],
    ) -> str:
        """
        <tool_def>
            <intent>
                Permanently delete a plan and all its tasks.
            </intent>

            <constraints>
                <rule>You can only delete your own plans.</rule>
                <rule>This action is IRREVERSIBLE.</rule>
            </constraints>

            <returns>
                On success: "Plan {plan_id} deleted successfully."
                On error: "Plan not found: {id}" or "Invalid plan ID format: {id}" or "Error: ...".
            </returns>
        </tool_def>
        """
        from app.core.exceptions import NotFoundError
        from app.db.session import get_db_context
        from app.services.plan import PlanService

        logger = logging.getLogger(__name__)

        if not ctx.deps.user_id:
            return "Error: User ID is required to delete a plan."

        try:
            user_uuid = UUID(ctx.deps.user_id)
            plan_uuid = UUID(plan_id)
            async with get_db_context() as db:
                plan_service = PlanService(db)
                await plan_service.delete_plan(plan_uuid, user_uuid)
                return f"Plan {plan_id} deleted successfully."
        except NotFoundError:
            return f"Plan not found: {plan_id}"
        except ValueError:
            return f"Invalid plan ID format: {plan_id}"
        except Exception as e:
            logger.exception("Error deleting plan")
            return f"Error deleting plan: {e}"

    @agent.tool
    async def get_all_plans(
        ctx: RunContext[TDeps],
    ) -> list | str:
        """
        <tool_def>
            <intent>
                Retrieve a summary of all your plans with IDs, names, descriptions,
                completion status, and task counts.
            </intent>

            <constraints>
                <rule>Only your own plans are returned.</rule>
                <rule>Use get_plan for full details of a specific plan.</rule>
            </constraints>

            <returns>
                On success: List of dicts with {id, name, description, is_completed, task_count, completed_task_count}.
                Empty list if no plans exist.
                On error: "Error listing plans: ...".
            </returns>
        </tool_def>
        """
        from app.db.session import get_db_context
        from app.services.plan import PlanService

        logger = logging.getLogger(__name__)

        if not ctx.deps.user_id:
            return "Error: User ID is required to list plans."

        try:
            user_uuid = UUID(ctx.deps.user_id)
            async with get_db_context() as db:
                plan_service = PlanService(db)
                summaries = await plan_service.get_all_plan_summaries(user_uuid)
                return [
                    {
                        "id": str(s.id),
                        "name": s.name,
                        "description": s.description,
                        "is_completed": s.is_completed,
                        "task_count": s.task_count,
                        "completed_task_count": s.completed_task_count,
                    }
                    for s in summaries
                ]
        except Exception as e:
            logger.exception("Error listing plans")
            return f"Error listing plans: {e}"

    @agent.tool
    async def add_task_to_plan(
        ctx: RunContext[TDeps],
        plan_id: Annotated[str, Field(description="The UUID of the plan to add the task to.")],
        task: Annotated[PlanTaskCreate, Field(
            description="The task to add with description, optional notes, status ('pending'/'in_progress'/'completed'), and optional position."
        )],
    ) -> str:
        """
        <tool_def>
            <intent>
                Add a new task to an existing plan.
                If position is not specified, the task is appended at the end.
            </intent>

            <constraints>
                <rule>Plan must exist and belong to you.</rule>
                <rule>Task description is required.</rule>
            </constraints>

            <returns>
                On success: "Task {task_id} added to plan {plan_id}."
                On error: "Plan not found: {id}" or "Invalid plan ID format: {id}" or "Error: ...".
            </returns>
        </tool_def>
        """
        from app.core.exceptions import NotFoundError
        from app.db.session import get_db_context
        from app.services.plan import PlanService

        logger = logging.getLogger(__name__)

        if not ctx.deps.user_id:
            return "Error: User ID is required to add a task."

        try:
            user_uuid = UUID(ctx.deps.user_id)
            plan_uuid = UUID(plan_id)
            async with get_db_context() as db:
                plan_service = PlanService(db)
                created_task = await plan_service.add_task(plan_uuid, user_uuid, task)
                return f"Task {created_task.id} added to plan {plan_id}."
        except NotFoundError:
            return f"Plan not found: {plan_id}"
        except ValueError:
            return f"Invalid plan ID format: {plan_id}"
        except Exception as e:
            logger.exception("Error adding task to plan")
            return f"Error adding task: {e}"

    @agent.tool
    async def update_task(
        ctx: RunContext[TDeps],
        task_id: Annotated[str, Field(description="The UUID of the task to update.")],
        task_update: Annotated[PlanTaskUpdate, Field(
            description="Partial update with fields: description, notes, status, is_completed, position."
        )],
    ) -> str:
        """
        <tool_def>
            <intent>
                Update an existing task's properties (description, notes, status, completion state).
            </intent>

            <constraints>
                <rule>Task must exist and belong to one of your plans.</rule>
                <rule>Only provided fields are updated (partial update semantics).</rule>
            </constraints>

            <returns>
                On success: "Task {task_id} updated: status={status}, completed={is_completed}".
                On error: "Task not found or unauthorized: {id}" or "Invalid task ID format: {id}" or "Error: ...".
            </returns>
        </tool_def>
        """
        from app.core.exceptions import NotFoundError
        from app.db.session import get_db_context
        from app.services.plan import PlanService

        logger = logging.getLogger(__name__)

        if not ctx.deps.user_id:
            return "Error: User ID is required to update a task."

        try:
            user_uuid = UUID(ctx.deps.user_id)
            task_uuid = UUID(task_id)
            async with get_db_context() as db:
                plan_service = PlanService(db)
                updated_task = await plan_service.update_task(task_uuid, user_uuid, task_update)
                return (
                    f"Task {updated_task.id} updated: "
                    f"status={updated_task.status}, completed={updated_task.is_completed}"
                )
        except NotFoundError:
            return f"Task not found or unauthorized: {task_id}"
        except ValueError:
            return f"Invalid task ID format: {task_id}"
        except Exception as e:
            logger.exception("Error updating task")
            return f"Error updating task: {e}"

    @agent.tool
    async def remove_task_from_plan(
        ctx: RunContext[TDeps],
        task_id: Annotated[str, Field(description="The UUID of the task to remove.")],
    ) -> str:
        """
        <tool_def>
            <intent>
                Remove a task from its plan. The task's plan is determined automatically.
            </intent>

            <constraints>
                <rule>Task must exist and belong to one of your plans.</rule>
                <rule>This action is IRREVERSIBLE.</rule>
            </constraints>

            <returns>
                On success: "Task {task_id} removed successfully."
                On error: "Task not found: {id}" or "Invalid task ID format: {id}" or "Error: ...".
            </returns>
        </tool_def>
        """
        from app.core.exceptions import NotFoundError
        from app.db.session import get_db_context
        from app.services.plan import PlanService

        logger = logging.getLogger(__name__)

        if not ctx.deps.user_id:
            return "Error: User ID is required to remove a task."

        try:
            user_uuid = UUID(ctx.deps.user_id)
            task_uuid = UUID(task_id)
            async with get_db_context() as db:
                plan_service = PlanService(db)
                await plan_service.remove_task(task_uuid, user_uuid)
                return f"Task {task_id} removed successfully."
        except NotFoundError:
            return f"Task not found: {task_id}"
        except ValueError:
            return f"Invalid task ID format: {task_id}"
        except Exception as e:
            logger.exception("Error removing task")
            return f"Error removing task: {e}"

    @agent.tool
    @safe_tool
    async def s3_list_objects(ctx: RunContext[TDeps]) -> list[str] | dict[str, Any]:
        """
        <tool_def>
            <intent>
                List all objects in your S3 storage. Use to discover available files
                or verify existence before download/overwrite operations.
            </intent>

            <constraints>
                <rule>Returns relative paths (user prefix stripped).</rule>
                <rule>Call this BEFORE s3_read_string_content if unsure of exact filename.</rule>
            </constraints>

            <error_handling>
                <error code="ClientError">S3 connection or permission issue.</error>
                <error code="EndpointConnectionError">S3 service unavailable.</error>
            </error_handling>

            <returns>
                On success: List of object keys (strings) relative to your user prefix.
                Empty list if no files exist.
                On error: dict with 'error' key and details.
            </returns>
        </tool_def>
        """
        from app.services.s3 import get_s3_service

        s3 = get_s3_service()
        user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
        all_objects = s3.list_objs(prefix=user_prefix) if user_prefix else s3.list_objs()
        # Strip user prefix from results
        return [
            obj[len(user_prefix) :] if obj.startswith(user_prefix) else obj for obj in all_objects
        ]

    @agent.tool
    @safe_tool
    async def s3_upload_file(
        ctx: RunContext[TDeps],
        file_name: Annotated[str, Field(description="Absolute or relative path to the local file to upload.")],
        object_name: Annotated[str, Field(description="The key (name) to assign to the object in your storage.")],
    ) -> str | dict[str, Any]:
        """
        <tool_def>
            <intent>
                Upload a local file from the server's filesystem to your S3 storage.
                Use when a file exists on disk and needs to be persisted.
            </intent>

            <constraints>
                <rule>Local file must exist on the server filesystem.</rule>
                <rule>For string content, prefer s3_upload_string_content instead.</rule>
            </constraints>

            <error_handling>
                <error code="FileNotFoundError">Local file does not exist.</error>
                <error code="ClientError">S3 upload failed (permission denied, connection issue).</error>
            </error_handling>

            <returns>
                On success: "Successfully uploaded {file_name} to {object_name}".
                On error: dict with 'error' key and details.
            </returns>
        </tool_def>
        """
        from app.services.s3 import get_s3_service

        s3 = get_s3_service()
        user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
        full_key = f"{user_prefix}{object_name}"
        s3.upload_file(file_name, full_key)
        return f"Successfully uploaded {file_name} to {object_name}"

    @agent.tool
    @safe_tool
    async def s3_download_file(
        ctx: RunContext[TDeps],
        object_name: Annotated[str, Field(description="The key (name) of the object in your storage to download.")],
        file_name: Annotated[str, Field(description="The local path where the file should be saved.")],
    ) -> str | dict[str, Any]:
        """
        <tool_def>
            <intent>
                Download a file from S3 to the server's local filesystem.
                Use when other tools need the file on disk.
            </intent>

            <constraints>
                <rule>For text content reading, prefer s3_read_string_content instead.</rule>
                <rule>Verify file exists first with s3_list_objects if unsure.</rule>
            </constraints>

            <error_handling>
                <error code="NoSuchKey">The file does not exist in storage.</error>
                <error code="ClientError">S3 connection or permission issue.</error>
                <error code="PermissionError">Cannot write to local path.</error>
            </error_handling>

            <returns>
                On success: "Successfully downloaded {object_name} to {file_name}".
                On error: dict with 'error' key and details.
            </returns>
        </tool_def>
        """
        from app.services.s3 import get_s3_service

        s3 = get_s3_service()
        user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
        full_key = f"{user_prefix}{object_name}"
        s3.download_file(full_key, file_name)
        return f"Successfully downloaded {object_name} to {file_name}"

    @agent.tool
    @safe_tool
    async def s3_upload_string_content(
        ctx: RunContext[TDeps],
        content: Annotated[str, Field(description="The string content to be written to the file.")],
        object_name: Annotated[str, Field(description="The key (name) to assign to the object in your storage.")],
    ) -> str | dict[str, Any]:
        """
        <tool_def>
            <intent>
                Upload text/string content directly to S3 without creating a local file.
                Ideal for saving reports, logs, generated text, or configuration.
            </intent>

            <constraints>
                <rule>Content is UTF-8 encoded before upload.</rule>
                <rule>For binary data, use s3_upload_file instead.</rule>
            </constraints>

            <error_handling>
                <error code="ClientError">S3 upload failed (permission denied, connection issue).</error>
            </error_handling>

            <returns>
                On success: "Successfully uploaded content to {object_name}".
                On error: dict with 'error' key and details.
            </returns>
        </tool_def>
        """
        from app.services.s3 import get_s3_service

        s3 = get_s3_service()
        user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
        full_key = f"{user_prefix}{object_name}"
        s3.upload_obj(content.encode("utf-8"), full_key)
        return f"Successfully uploaded content to {object_name}"

    @agent.tool
    @safe_tool
    async def s3_read_string_content(
        ctx: RunContext[TDeps],
        object_name: Annotated[str, Field(description="The key (name) of the object in your storage to read.")],
    ) -> str | dict[str, Any]:
        """
        <tool_def>
            <intent>
                Read a text file from S3 directly into a string.
                Ideal for logs, config files, notes, and other text content.
            </intent>

            <constraints>
                <rule>File must be valid UTF-8 text.</rule>
                <rule>For binary files, use s3_download_file instead.</rule>
                <rule>Call s3_list_objects first if unsure of exact filename.</rule>
            </constraints>

            <error_handling>
                <error code="NoSuchKey">File does not exist. Use s3_list_objects to see available files.</error>
                <error code="UnicodeDecodeError">File is not valid UTF-8 (may be binary).</error>
                <error code="ClientError">S3 connection or permission issue.</error>
            </error_handling>

            <returns>
                On success: The file contents as a UTF-8 decoded string.
                On error: dict with 'error' key and details.
            </returns>
        </tool_def>
        """
        from app.services.s3 import get_s3_service

        s3 = get_s3_service()
        user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
        full_key = f"{user_prefix}{object_name}"
        content = s3.download_obj(full_key)
        return content.decode("utf-8")

    @agent.tool
    @safe_tool
    async def s3_delete_object(
        ctx: RunContext[TDeps],
        object_name: Annotated[str, Field(description="The key (name) of the object to delete.")],
    ) -> str | dict[str, Any]:
        """
        <tool_def>
            <intent>
                Delete an object from your S3 storage.
            </intent>

            <constraints>
                <rule>This action is PERMANENT and IRREVERSIBLE.</rule>
                <rule>Verify correct file before deletion.</rule>
            </constraints>

            <error_handling>
                <error code="NoSuchKey">The file does not exist in storage.</error>
                <error code="ClientError">S3 connection or permission issue.</error>
            </error_handling>

            <returns>
                On success: "Successfully deleted object {object_name}".
                On error: dict with 'error' key and details.
            </returns>
        </tool_def>
        """
        from app.services.s3 import get_s3_service

        s3 = get_s3_service()
        user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
        full_key = f"{user_prefix}{object_name}"
        s3.delete_obj(full_key)
        return f"Successfully deleted object {object_name}"

    @agent.tool
    @safe_tool
    async def s3_generate_presigned_download_url(
        ctx: RunContext[TDeps],
        object_name: Annotated[str, Field(description="The key (name) of the object in your storage.")],
        expiration: Annotated[int, Field(description="Validity duration in seconds.")] = 3600,
    ) -> str | dict[str, Any]:
        """
        <tool_def>
            <intent>
                Generate a temporary public URL to access a private S3 object.
                Use to share files with users or external systems.
            </intent>

            <constraints>
                <rule>URL works even if object doesn't exist (error on access).</rule>
                <rule>Default expiration is 1 hour (3600 seconds).</rule>
            </constraints>

            <error_handling>
                <error code="ClientError">S3 connection or permission issue.</error>
            </error_handling>

            <returns>
                On success: HTTPS presigned URL string (valid for {expiration} seconds).
                On error: dict with 'error' key and details.
            </returns>
        </tool_def>
        """
        from app.services.s3 import get_s3_service

        s3 = get_s3_service()
        user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
        full_key = f"{user_prefix}{object_name}"
        return s3.generate_presigned_download_url(full_key, expiration)

    @agent.tool
    @safe_tool
    async def s3_generate_presigned_upload_post_url(
        ctx: RunContext[TDeps],
        object_name: Annotated[str, Field(description="The key (name) for the object to be uploaded.")],
        expiration: Annotated[int, Field(description="Validity duration in seconds.")] = 3600,
    ) -> str | dict[str, Any]:
        """
        <tool_def>
            <intent>
                Generate a presigned POST URL for client-side file uploads directly to S3.
                Returns URL and form fields required for authentication.
            </intent>

            <constraints>
                <rule>Returned 'fields' MUST be included in the POST form data.</rule>
                <rule>Default expiration is 1 hour (3600 seconds).</rule>
            </constraints>

            <error_handling>
                <error code="ClientError">S3 connection or permission issue.</error>
            </error_handling>

            <returns>
                On success: dict with 'url' (string) and 'fields' (dict of form fields).
                On error: dict with 'error' key and details.
            </returns>
        </tool_def>
        """
        from app.services.s3 import get_s3_service

        s3 = get_s3_service()
        user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
        full_key = f"{user_prefix}{object_name}"
        return s3.generate_presigned_post(full_key, expiration)

    @agent.tool
    @safe_tool
    async def s3_copy_file(
        ctx: RunContext[TDeps],
        source_object_name: Annotated[str, Field(description="The key (name) of the existing object to copy.")],
        dest_object_name: Annotated[str, Field(description="The key (name) for the new copy.")],
    ) -> str | dict[str, Any]:
        """
        <tool_def>
            <intent>
                Copy a file within S3 storage. Use for duplication, renaming (copy + delete), or backups.
            </intent>

            <constraints>
                <rule>Source file must exist.</rule>
                <rule>To rename, copy then delete the source.</rule>
            </constraints>

            <error_handling>
                <error code="NoSuchKey">The source file does not exist in storage.</error>
                <error code="ClientError">S3 connection or permission issue.</error>
            </error_handling>

            <returns>
                On success: "Successfully copied {source_object_name} to {dest_object_name}".
                On error: dict with 'error' key and details.
            </returns>
        </tool_def>
        """
        from app.services.s3 import get_s3_service

        s3 = get_s3_service()
        user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
        source_key = f"{user_prefix}{source_object_name}"
        dest_key = f"{user_prefix}{dest_object_name}"
        s3.copy_file(source_key, dest_key)
        return f"Successfully copied {source_object_name} to {dest_object_name}"

    @agent.tool
    @safe_tool
    async def python_execute_code(
        ctx: RunContext[TDeps],
        code: Annotated[str, Field(description="The Python code to execute. Must be valid Python 3.13 syntax.")],
        timeout: Annotated[int, Field(description="Maximum execution time in seconds. Use higher values for long-running tasks.")] = 600,
    ) -> dict[str, Any]:
        """
        <tool_def>
            <intent>
                Execute Python code in an ephemeral Docker container for data analysis,
                scraping, calculations, or any Python task.
            </intent>

            <environment>
                <persistence>Ephemeral - filesystem resets after each call.</persistence>
                <internet>Enabled - can fetch URLs, APIs, etc.</internet>
                <python_version>3.13</python_version>
                <storage_api>
                    Use `storage_client` module for persistent file storage:
                    ```python
                    from storage_client import StorageClient
                    client = StorageClient()
                    client.put("data/output.csv", content)
                    content = client.get_text("data/input.txt")
                    files = client.list(prefix="data/")
                    client.delete("data/temp.txt")
                    ```
                </storage_api>
                <libs category="Web/HTTP">requests, httpx, aiohttp</libs>
                <libs category="Scraping">beautifulsoup4, lxml, html5lib, cssselect</libs>
                <libs category="Data Science">pandas, numpy, scipy, scikit-learn, statsmodels, sympy, networkx</libs>
                <libs category="Visualization">matplotlib, seaborn, plotly, imageio</libs>
                <libs category="Documents">pypdf, python-docx, python-pptx, openpyxl, xlrd, ebooklib, reportlab, weasyprint</libs>
                <libs category="Text/NLP">nltk, textblob, markdown, regex, html2text, inscriptis, unidecode, ftfy, chardet</libs>
                <libs category="Finance">yfinance, fredapi</libs>
                <libs category="Databases">psycopg2-binary, pymysql, pymongo, redis</libs>
                <libs category="APIs">pyjwt, authlib, cryptography, ecdsa, graphql-core, grpcio, protobuf</libs>
                <libs category="Geo">geopy, shapely</libs>
                <libs category="Image">opencv-python-headless, pytesseract, Pillow, qrcode, python-barcode, pyzbar</libs>
                <libs category="Date/Time">python-dateutil, pytz, arrow, pendulum</libs>
                <libs category="Data Formats">pyyaml, toml, xmltodict, defusedxml, jsonschema</libs>
                <libs category="Network">paramiko, dnspython, websockets</libs>
                <libs category="Archives">py7zr</libs>
                <libs category="Media">mutagen, pydub, av</libs>
                <libs category="Validation">pydantic, marshmallow, email-validator, phonenumbers</libs>
                <libs category="Utilities">tqdm, cachetools, diskcache, joblib, faker, loguru, colorama</libs>
            </environment>

            <constraints>
                <rule>Default timeout is 600s (10 min). Increase for long tasks.</rule>
                <rule>Storage is user-scoped; cannot access other users' data.</rule>
            </constraints>

            <error_handling>
                <error code="TimeoutError">Code execution exceeded timeout limit.</error>
                <error code="RuntimeError">Docker container failed to start.</error>
                <error code="DockerException">Docker service unavailable.</error>
            </error_handling>

            <returns>
                dict with keys:
                - 'stdout': Standard output from execution (string).
                - 'stderr': Standard error from execution (string).
                - 'exit_code': Process exit code (0 = success).
                - 'timed_out': Boolean indicating timeout.
            </returns>
        </tool_def>
        """
        from app.api.routes.v1.storage_proxy import create_sandbox_token
        from app.services.python import get_python_executor

        python_executor = get_python_executor()
        user_id = ctx.deps.user_id if ctx.deps.user_id else None

        # Generate a short-lived storage token for secure S3 access
        storage_token = None
        if user_id:
            storage_token, _ = create_sandbox_token(user_id)

        result = await python_executor.execute_code(
            code, timeout, user_id=user_id, storage_token=storage_token
        )
        return result

    @agent.tool
    @safe_tool
    async def extract_webpage(
        ctx: RunContext[TDeps],
        url: Annotated[str, Field(description="The full URL to fetch (e.g., 'https://docs.python.org/3/').")],
        extract_text: Annotated[bool, Field(
            description="True: Returns parsed readable text (best for reasoning). False: Returns raw HTML (for layout analysis)."
        )] = True,
        max_length: Annotated[int, Field(description="Maximum characters to return. Content is truncated if longer.")] = 20000,
    ) -> dict[str, Any]:
        """
        <tool_def>
            <intent>
                Fetch and extract content from a specific webpage URL.
                Returns parsed text or raw HTML with title and metadata.
            </intent>

            <selector>
                <case condition="Don't have a specific URL">Use search_web first to find URLs.</case>
                <case condition="Have a specific URL">Use this tool directly.</case>
            </selector>

            <constraints>
                <rule>Prefer search_web if you don't have a specific URL.</rule>
                <rule>Use extract_text=False only when HTML structure analysis is needed.</rule>
            </constraints>

            <error_handling>
                <error code="HTTPError">Failed to fetch URL (404, 500, etc.).</error>
                <error code="ConnectionError">Network issue or URL unreachable.</error>
                <error code="Timeout">Request took too long.</error>
            </error_handling>

            <returns>
                dict with keys:
                - 'url': The fetched URL.
                - 'title': Page title (if found).
                - 'content': Extracted text or raw HTML (based on extract_text param).
                - 'content_type': MIME type of the response.
            </returns>
        </tool_def>
        """

        response = await extract_url(
            url=url,
            extract_text=extract_text,
            max_length=max_length,
        )
        return response.model_dump()

    @agent.tool
    async def s3_fetch_image(
        ctx: RunContext[TDeps],
        object_name: Annotated[str, Field(
            description="The key (name) of the image in storage (e.g., 'photos/receipt.png'). Do NOT include 'users/<id>/' prefix."
        )],
    ) -> ToolReturn:
        """
        <tool_def>
            <intent>
                Fetch an image from S3 storage and load it into context for visual analysis.
                Use when user asks to look at, analyze, describe, or extract from an image.
            </intent>

            <selector>
                <case condition="User wants visual analysis of stored image">Use this tool.</case>
                <case condition="Non-image file (text, CSV, JSON)">Use s3_read_string_content instead.</case>
                <case condition="Image already attached to message">Already in context, no tool needed.</case>
                <case condition="Don't know exact filename">Call s3_list_objects first.</case>
            </selector>

            <workflow>
                <step>If filename unknown, call s3_list_objects first.</step>
                <step>Call this tool with the image filename.</step>
                <step>Analyze the returned image and respond.</step>
            </workflow>

            <constraints>
                <rule>Supported formats: PNG, JPEG, WebP, HEIC, HEIF.</rule>
                <rule>Maximum size: 20MB per image.</rule>
            </constraints>

            <returns>
                ToolReturn with:
                - return_value: Confirmation message with image path.
                - content: The binary image data loaded into your visual context.
                - metadata: {success, object_name, media_type, size_bytes}.
                On error: ToolReturn with error message and success=False.
            </returns>
        </tool_def>
        """
        return await s3_fetch_image_impl(ctx, object_name)

    @agent.tool
    async def generate_image(
        ctx: RunContext[TDeps],
        prompt: Annotated[str, Field(
            description="Detailed description of the image to generate. Be specific about subject, style, lighting, composition, colors, and mood."
        )],
        model: Annotated[ImageModelName, Field(
            description="Model to use for generation. See model_guide for selection criteria."
        )] = "imagen-4.0-generate-001",
        aspect_ratio: Annotated[str, Field(
            description="Image dimensions ratio. Options: '1:1' (square), '16:9'/'4:3'/'3:2' (landscape), '9:16'/'3:4'/'2:3' (portrait), '21:9' (ultra-wide, Gemini only)."
        )] = "1:1",
        image_size: Annotated[str, Field(
            description="Resolution: '1K' (fastest), '2K' (balanced), '4K' (highest, Gemini only)."
        )] = "2K",
        number_of_images: Annotated[int, Field(
            description="Number of images to generate, 1-4 (Imagen models only)."
        )] = 1,
        negative_prompt: Annotated[str | None, Field(
            description="What to avoid in the image (Imagen only). Example: 'blurry, low quality, distorted, watermark'."
        )] = None,
        filename: Annotated[str | None, Field(
            description="Custom filename without extension. Defaults to auto-generated UUID. Saved as PNG."
        )] = None,
    ) -> ToolReturn:
        """
        <tool_def>
            <intent>
                Generate images from text descriptions using Google's Gemini or Imagen models.
                Images are saved to S3 and loaded into context for immediate inspection.
            </intent>

            <model_guide>
                <model name="gemini-3-pro-image-preview">
                    Best for iterative refinement, conversational edits, and 4K output.
                    Supports back-and-forth editing. Generates 1 image per call.
                </model>
                <model name="imagen-4.0-generate-001">
                    Standard Imagen 4. Great balance of quality and speed for photorealism.
                    Supports 1-4 images per call.
                </model>
                <model name="imagen-4.0-ultra-generate-001">
                    Highest quality Imagen. Best for professional product photos, portraits,
                    and detailed scenes. Slower but superior results. Supports 1-4 images.
                </model>
                <model name="imagen-4.0-fast-generate-001">
                    Fastest Imagen 4. Use for quick iterations or drafts.
                    Supports 1-4 images per call.
                </model>
            </model_guide>

            <constraints>
                <rule>number_of_images only applies to Imagen models (1-4).</rule>
                <rule>negative_prompt only applies to Imagen models.</rule>
                <rule>4K resolution only available with Gemini model.</rule>
                <rule>Ultra-wide 21:9 aspect ratio only available with Gemini.</rule>
            </constraints>

            <error_handling>
                <error code="SafetyFilter">Generation blocked by safety filters. Modify prompt and retry.</error>
            </error_handling>

            <returns>
                ToolReturn with:
                - return_value: Success message with S3 paths and presigned URLs (valid 1 hour).
                - content: Generated image(s) loaded into visual context for immediate inspection.
                - metadata: {success, model, prompt, s3_keys[], urls[], aspect_ratio, image_size, rai_reasons}.
                On failure: ToolReturn with error message, success=False, and rai_reasons if filtered.
            </returns>
        </tool_def>
        """
        from google import genai
        from google.genai import types

        from app.services.s3 import get_s3_service

        # Initialize Google GenAI client
        client = genai.Client(api_key=settings.GOOGLE_API_KEY)

        user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
        s3 = get_s3_service()

        generated_images: list[tuple[bytes, str]] = []  # (image_bytes, s3_key)
        rai_reasons: list[str] = []

        if model in ("imagen-4.0-generate-001", "imagen-4.0-ultra-generate-001", "imagen-4.0-fast-generate-001"):
            # Imagen 4 image generation (standard, ultra, or fast)
            # Note: API only supports BLOCK_LOW_AND_ABOVE for safety_filter_level
            # and ALLOW_ADULT for person_generation (BLOCK_NONE/ALLOW_ALL rejected)
            config = types.GenerateImagesConfig(
                number_of_images=min(max(number_of_images, 1), 4),  # Clamp to 1-4
                aspect_ratio=aspect_ratio,
                negative_prompt=negative_prompt,
                safety_filter_level=types.SafetyFilterLevel.BLOCK_LOW_AND_ABOVE,
                person_generation=types.PersonGeneration.ALLOW_ADULT,
                include_rai_reason=True,
                include_safety_attributes=True,
                output_mime_type="image/png",
            )

            # Add image_size if supported (not all aspect ratios support all sizes)
            if image_size in ("1K", "2K"):
                config.image_size = image_size

            response = await client.aio.models.generate_images(
                model=model,  # Use the selected Imagen model directly
                prompt=prompt,
                config=config,
            )

            # Process generated images
            if response.generated_images:
                for i, gen_img in enumerate(response.generated_images):
                    if gen_img.image and gen_img.image.image_bytes:
                        img_filename = filename or uuid4().hex
                        if number_of_images > 1:
                            img_filename = f"{img_filename}_{i + 1}"
                        s3_key = f"{user_prefix}generated/{img_filename}.png"

                        s3.upload_obj(gen_img.image.image_bytes, s3_key)
                        generated_images.append((gen_img.image.image_bytes, s3_key))

                    # Collect any RAI reasons
                    if hasattr(gen_img, "rai_filtered_reason") and gen_img.rai_filtered_reason:
                        rai_reasons.append(gen_img.rai_filtered_reason)

        else:
            # Gemini image generation with disabled safety filters
            safety_settings = [
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                    threshold=types.HarmBlockThreshold.OFF,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    threshold=types.HarmBlockThreshold.OFF,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                    threshold=types.HarmBlockThreshold.OFF,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                    threshold=types.HarmBlockThreshold.OFF,
                ),
            ]

            # Note: output_mime_type is not supported for Gemini API
            # Images are returned as JPEG by default
            image_config = types.ImageConfig(
                aspect_ratio=aspect_ratio,
            )
            # Add image_size for Gemini (supports up to 4K)
            if image_size in ("1K", "2K", "4K"):
                image_config.image_size = image_size

            config = types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=image_config,
                safety_settings=safety_settings,
            )

            response = await client.aio.models.generate_content(
                model=settings.GEMINI_IMAGE_MODEL,
                contents=[prompt],
                config=config,
            )

            # Process response parts for images
            # Note: Gemini returns images as JPEG
            if response.candidates and response.candidates[0].content:
                for part in response.candidates[0].content.parts:
                    if part.inline_data and part.inline_data.data:
                        img_filename = filename or uuid4().hex
                        # Determine extension from MIME type (defaults to jpg for Gemini)
                        mime_type = part.inline_data.mime_type or "image/jpeg"
                        extension = "png" if mime_type == "image/png" else "jpg"
                        s3_key = f"{user_prefix}generated/{img_filename}.{extension}"

                        s3.upload_obj(part.inline_data.data, s3_key)
                        generated_images.append((part.inline_data.data, s3_key))

            # Check for block reasons
            if response.candidates:
                for candidate in response.candidates:
                    if hasattr(candidate, "finish_reason") and candidate.finish_reason:
                        finish_reason = str(candidate.finish_reason)
                        if "SAFETY" in finish_reason or "BLOCK" in finish_reason:
                            rai_reasons.append(f"Generation blocked: {finish_reason}")

        # Handle case where no images were generated
        if not generated_images:
            error_msg = "No images were generated."
            if rai_reasons:
                error_msg += f" Rejection reasons: {'; '.join(rai_reasons)}. Consider rephrasing your prompt."
            return ToolReturn(
                return_value=error_msg,
                content=[error_msg],
                metadata={"success": False, "rai_reasons": rai_reasons},
            )

        # Build response with presigned URLs and inline images
        urls = []
        content_parts: list[str | BinaryContent] = [
            f"Generated {len(generated_images)} image(s) for prompt: '{prompt[:100]}{'...' if len(prompt) > 100 else ''}'"
        ]

        for img_bytes, s3_key in generated_images:
            presigned_url = s3.generate_presigned_download_url(s3_key, expiration=3600)
            urls.append(presigned_url)
            # Add binary content for LLM to see the image
            content_parts.append(BinaryContent(data=img_bytes, media_type="image/png"))

        # Strip user prefix from display keys
        display_keys = [
            key[len(user_prefix) :] if key.startswith(user_prefix) else key
            for _, key in generated_images
        ]

        return_msg = f"Successfully generated {len(generated_images)} image(s). "
        return_msg += f"Saved to: {', '.join(display_keys)}. "
        return_msg += f"Download URLs (valid 1 hour): {', '.join(urls)}"

        if rai_reasons:
            return_msg += f" Note - some images may have been filtered: {'; '.join(rai_reasons)}"

        return ToolReturn(
            return_value=return_msg,
            content=content_parts,
            metadata={
                "success": True,
                "model": model,
                "prompt": prompt,
                "s3_keys": display_keys,
                "urls": urls,
                "aspect_ratio": aspect_ratio,
                "image_size": image_size,
                "rai_reasons": rai_reasons if rai_reasons else None,
            },
        )

    # ==========================================================================
    # Academic Search Tools
    # ==========================================================================

    @agent.tool
    async def search_openalex(
        ctx: RunContext[TDeps],
        query: Annotated[str, Field(description="Search terms. Natural language queries work well.")],
        search_field: Annotated[
            Literal["all", "title", "abstract", "fulltext", "title_and_abstract"],
            Field(description="Which fields to search: 'all' (broadest), 'title', 'abstract', 'fulltext', 'title_and_abstract'.")
        ] = "all",
        year_from: Annotated[int | None, Field(description="Minimum publication year (inclusive).")] = None,
        year_to: Annotated[int | None, Field(description="Maximum publication year (inclusive).")] = None,
        min_citations: Annotated[int | None, Field(description="Only papers with at least this many citations.")] = None,
        open_access_only: Annotated[bool, Field(description="If True, only return papers with free full text.")] = False,
        oa_status: Annotated[
            Literal["gold", "green", "hybrid", "bronze", "closed"] | None,
            Field(description="Filter by OA status: 'gold' (OA journal), 'green' (repository), 'hybrid', 'bronze' (free on publisher), 'closed'.")
        ] = None,
        publication_type: Annotated[str | None, Field(description="Filter by type: 'article', 'book', 'dataset', etc.")] = None,
        institution_id: Annotated[str | None, Field(description="OpenAlex institution ID (e.g., 'I27837315' for MIT).")] = None,
        author_id: Annotated[str | None, Field(description="OpenAlex author ID (e.g., 'A5023888391').")] = None,
        concept_id: Annotated[str | None, Field(description="Research concept ID (e.g., 'C41008148' for AI).")] = None,
        language: Annotated[str | None, Field(description="ISO 639-1 language code (e.g., 'en', 'zh', 'de').")] = None,
        sort_by: Annotated[
            Literal["relevance", "cited_by_count", "publication_date", "display_name"],
            Field(description="Sort by: 'relevance', 'cited_by_count', 'publication_date', 'display_name'.")
        ] = "relevance",
        sort_order: Annotated[Literal["asc", "desc"], Field(description="Sort order: 'asc' or 'desc'.")] = "desc",
        page: Annotated[int, Field(description="Page number (1-indexed).")] = 1,
        per_page: Annotated[int, Field(description="Results per page, 1-200.")] = 25,
        include_abstract: Annotated[bool, Field(description="Include paper abstracts.")] = True,
        include_authors: Annotated[bool, Field(description="Include author information.")] = True,
    ) -> dict[str, Any]:
        """
        <tool_def>
            <intent>
                Search OpenAlex academic database (250M+ scholarly works) for papers with
                comprehensive metadata including citations, open access status, and affiliations.
            </intent>

            <selector>
                <case condition="Large-scale search across disciplines">Use this tool.</case>
                <case condition="Need citation metrics and OA info">Use this tool.</case>
                <case condition="Filter by institution, author, or concept">Use this tool.</case>
                <case condition="Need AI-generated summaries/TLDR">Use search_semantic_scholar instead.</case>
                <case condition="Need preprints not yet indexed">Use search_arxiv instead.</case>
                <case condition="Need paper embeddings">Use search_semantic_scholar instead.</case>
            </selector>

            <constraints>
                <rule>Results per page max is 200.</rule>
                <rule>Use page parameter for pagination (1-indexed).</rule>
            </constraints>

            <error_handling>
                <error code="Timeout">OpenAlex may be slow during peak times.</error>
                <error code="InvalidFilter">Check parameter values match allowed options.</error>
            </error_handling>

            <returns>
                dict with:
                - 'results': List of papers with title, authors, abstract, doi, citations, oa_url, etc.
                - 'meta': {count, page, per_page, total_pages}.
            </returns>
        </tool_def>
        """
        return await search_openalex_impl(
            query,
            search_field=search_field,
            year_from=year_from,
            year_to=year_to,
            min_citations=min_citations,
            open_access_only=open_access_only,
            oa_status=oa_status,
            publication_type=publication_type,
            institution_id=institution_id,
            author_id=author_id,
            concept_id=concept_id,
            language=language,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            per_page=per_page,
            include_abstract=include_abstract,
            include_authors=include_authors,
        )

    @agent.tool
    async def search_semantic_scholar(
        ctx: RunContext[TDeps],
        query: Annotated[str, Field(description="Plain-text search query. No special syntax supported.")],
        year: Annotated[str | None, Field(description="Year or range: '2020', '2016-2020', '2010-' (onwards), '-2015' (before).")] = None,
        venue: Annotated[str | None, Field(description="Comma-separated venue names (e.g., 'Nature,Science,ICML').")] = None,
        fields_of_study: Annotated[list[str] | None, Field(
            description="List of fields: 'Computer Science', 'Medicine', 'Physics', 'Biology', 'Chemistry', 'Mathematics', etc."
        )] = None,
        publication_types: Annotated[list[str] | None, Field(
            description="List of types: 'JournalArticle', 'Conference', 'Review', 'Book', 'Dataset', 'ClinicalTrial'."
        )] = None,
        open_access_only: Annotated[bool, Field(description="If True, only return papers with free PDFs.")] = False,
        min_citation_count: Annotated[int | None, Field(description="Minimum number of citations required.")] = None,
        offset: Annotated[int, Field(description="Starting index (0-based) for pagination.")] = 0,
        limit: Annotated[int, Field(description="Number of results (1-100).")] = 20,
        include_abstract: Annotated[bool, Field(description="Include full paper abstracts.")] = True,
        include_tldr: Annotated[bool, Field(description="Include AI-generated TLDR summaries (RECOMMENDED).")] = True,
        include_authors: Annotated[bool, Field(description="Include author names and IDs.")] = True,
        include_venue: Annotated[bool, Field(description="Include publication venue info.")] = True,
        include_embedding: Annotated[bool, Field(description="Include SPECTER v2 paper embeddings.")] = False,
    ) -> dict[str, Any]:
        """
        <tool_def>
            <intent>
                Search Semantic Scholar for papers with AI-enhanced features including
                TLDR summaries, influential citation tracking, and paper embeddings.
            </intent>

            <selector>
                <case condition="Need AI-generated paper summaries/TLDR">Use this tool.</case>
                <case condition="Want influential citation tracking">Use this tool.</case>
                <case condition="CS/AI papers (excellent coverage)">Use this tool.</case>
                <case condition="Need paper embeddings for similarity">Use this tool.</case>
                <case condition="Need boolean query syntax">Use search_semantic_scholar_bulk instead.</case>
                <case condition="Need &gt;1000 results">Use search_semantic_scholar_bulk instead.</case>
                <case condition="Need institution filtering">Use search_openalex instead.</case>
                <case condition="Need very recent preprints">Use search_arxiv instead.</case>
            </selector>

            <constraints>
                <rule>Max 100 results per request via limit parameter.</rule>
                <rule>Use offset for pagination.</rule>
                <rule>TLDR summaries highly recommended for quick paper understanding.</rule>
            </constraints>

            <error_handling>
                <error code="RateLimit">429 error - wait and retry. Consider API key.</error>
                <error code="NoResults">Try broader terms or fewer filters.</error>
            </error_handling>

            <returns>
                dict with:
                - 'total': Total number of matching papers.
                - 'offset': Current offset for pagination.
                - 'data': List of papers with paperId, title, abstract, tldr, authors, venue, citations, etc.
            </returns>
        </tool_def>
        """
        return await search_semantic_scholar_impl(
            query,
            year=year,
            venue=venue,
            fields_of_study=fields_of_study,
            publication_types=publication_types,
            open_access_only=open_access_only,
            min_citation_count=min_citation_count,
            offset=offset,
            limit=limit,
            include_abstract=include_abstract,
            include_tldr=include_tldr,
            include_authors=include_authors,
            include_venue=include_venue,
            include_embedding=include_embedding,
        )

    @agent.tool
    async def search_semantic_scholar_bulk(
        ctx: RunContext[TDeps],
        query: Annotated[str, Field(
            description="Boolean query string. Supports: AND, OR ('|'), NOT ('-'), phrases ('\"exact\"'), wildcards ('neuro*'), fuzzy ('word~2')."
        )],
        year: Annotated[str | None, Field(description="Year or range filter (same as relevance search).")] = None,
        venue: Annotated[str | None, Field(description="Comma-separated venue names.")] = None,
        fields_of_study: Annotated[list[str] | None, Field(description="List of fields to filter by.")] = None,
        publication_types: Annotated[list[str] | None, Field(description="List of publication types.")] = None,
        open_access_only: Annotated[bool, Field(description="Only papers with free PDFs.")] = False,
        min_citation_count: Annotated[int | None, Field(description="Minimum citation count.")] = None,
        sort_by: Annotated[
            Literal["paperId", "publicationDate", "citationCount"],
            Field(description="Sort by: 'paperId' (stable), 'publicationDate', 'citationCount'.")
        ] = "paperId",
        sort_order: Annotated[Literal["asc", "desc"], Field(description="Sort order.")] = "asc",
        token: Annotated[str | None, Field(description="Continuation token from previous response for pagination.")] = None,
        include_abstract: Annotated[bool, Field(description="Include paper abstracts.")] = True,
        include_tldr: Annotated[bool, Field(description="Include TLDR summaries (adds latency).")] = False,
    ) -> dict[str, Any]:
        """
        <tool_def>
            <intent>
                Bulk search Semantic Scholar with boolean query support and pagination tokens.
                Can access up to 10 million results for systematic reviews and dataset building.
            </intent>

            <selector>
                <case condition="Need boolean operators (AND, OR, NOT)">Use this tool.</case>
                <case condition="Need &gt;1000 results">Use this tool.</case>
                <case condition="Building datasets or systematic reviews">Use this tool.</case>
                <case condition="Need exact phrase matching or prefix search">Use this tool.</case>
                <case condition="Simple search with quick TLDR">Use search_semantic_scholar instead.</case>
                <case condition="Need paper embeddings">Use search_semantic_scholar instead.</case>
            </selector>

            <workflow>
                <step>First call: Don't pass token.</step>
                <step>Check response for token field.</step>
                <step>If token is not None, call again with that token.</step>
                <step>Repeat until token is None.</step>
            </workflow>

            <constraints>
                <rule>Boolean syntax: AND implicit, OR '|', NOT '-', phrases '\"\"', wildcards '*', fuzzy '~2'.</rule>
                <rule>TLDR adds latency in bulk mode.</rule>
            </constraints>

            <returns>
                dict with:
                - 'token': Continuation token for next page (None when exhausted).
                - 'data': List of papers with paperId, title, abstract, tldr, authors, venue, citations.
            </returns>
        </tool_def>
        """
        return await search_semantic_scholar_bulk_impl(
            query,
            year=year,
            venue=venue,
            fields_of_study=fields_of_study,
            publication_types=publication_types,
            open_access_only=open_access_only,
            min_citation_count=min_citation_count,
            sort_by=sort_by,
            sort_order=sort_order,
            token=token,
            include_abstract=include_abstract,
            include_tldr=include_tldr,
        )

    @agent.tool
    async def search_arxiv(
        ctx: RunContext[TDeps],
        query: Annotated[str | None, Field(
            description="Search terms. Can use inline prefixes like 'ti:quantum AND au:smith'."
        )] = None,
        id_list: Annotated[list[str] | None, Field(
            description="List of specific arXiv IDs (e.g., ['2301.00001', 'cs/0001001'])."
        )] = None,
        search_field: Annotated[
            Literal["all", "title", "abstract", "author", "category", "comment", "journal_ref"],
            Field(description="Limit search to: 'all', 'title', 'abstract', 'author', 'category', 'comment', 'journal_ref'.")
        ] = "all",
        categories: Annotated[list[str] | None, Field(
            description="Filter by arXiv category codes (e.g., ['cs.AI', 'cs.LG']). Use list_arxiv_categories for valid codes."
        )] = None,
        submitted_after: Annotated[str | None, Field(description="Only papers after this date (YYYYMMDD format).")] = None,
        submitted_before: Annotated[str | None, Field(description="Only papers before this date (YYYYMMDD format).")] = None,
        sort_by: Annotated[
            Literal["relevance", "lastUpdatedDate", "submittedDate"],
            Field(description="Sort by: 'relevance', 'lastUpdatedDate', 'submittedDate'.")
        ] = "relevance",
        sort_order: Annotated[
            Literal["ascending", "descending"],
            Field(description="Sort order: 'ascending' or 'descending'.")
        ] = "descending",
        start: Annotated[int, Field(description="Starting index for pagination (0-based).")] = 0,
        max_results: Annotated[int, Field(description="Number of results (max 2000 per request).")] = 20,
    ) -> dict[str, Any]:
        """
        <tool_def>
            <intent>
                Search arXiv preprint repository for cutting-edge scientific papers.
                Papers available immediately upon submission, often months before peer review.
                Always free full PDFs.
            </intent>

            <selector>
                <case condition="Cutting-edge research before peer review">Use this tool.</case>
                <case condition="Physics, math, CS, stats, quant papers">Use this tool.</case>
                <case condition="Need immediate free PDF access">Use this tool.</case>
                <case condition="Looking for specific arXiv IDs">Use this tool.</case>
                <case condition="Track recent submissions in a field">Use this tool.</case>
                <case condition="Need AI summaries/TLDR">Use search_semantic_scholar instead.</case>
                <case condition="Need citation counts">Use search_openalex or search_semantic_scholar.</case>
                <case condition="Biology, medicine, social science">Limited coverage—try other tools.</case>
            </selector>

            <constraints>
                <rule>Max 2000 results per request.</rule>
                <rule>3-second delays between requests (automatic).</rule>
                <rule>Query too broad errors at 30000 total results.</rule>
                <rule>Use list_arxiv_categories to find valid category codes.</rule>
            </constraints>

            <error_handling>
                <error code="QueryTooBroad">arXiv limits to 30000 results total.</error>
                <error code="InvalidCategory">Use list_arxiv_categories to check valid codes.</error>
            </error_handling>

            <returns>
                dict with:
                - 'total_results': Total matching papers.
                - 'start_index': Current offset.
                - 'entries': List with arxiv_id, title, summary, authors[], categories[], published, pdf_url.
            </returns>
        </tool_def>
        """
        return await search_arxiv_impl(
            query,
            id_list=id_list,
            search_field=search_field,
            categories=categories,
            submitted_after=submitted_after,
            submitted_before=submitted_before,
            sort_by=sort_by,
            sort_order=sort_order,
            start=start,
            max_results=max_results,
        )

    @agent.tool
    async def list_arxiv_categories(ctx: RunContext[TDeps]) -> dict[str, Any]:
        """
        <tool_def>
            <intent>
                List all valid arXiv category codes with names and groups.
                Use to discover correct category codes for filtering search_arxiv.
            </intent>

            <selector>
                <case condition="Need correct category code for a research area">Use this tool.</case>
                <case condition="Want to see all categories in a discipline">Use this tool.</case>
                <case condition="Unsure which category code to use">Use this tool first.</case>
            </selector>

            <constraints>
                <rule>Returns categories grouped by discipline.</rule>
                <rule>Common groups: Computer Science (cs.*), Statistics (stat.*), Mathematics (math.*), Physics, etc.</rule>
            </constraints>

            <returns>
                dict with discipline groups as keys, each containing:
                - List of {code, name} objects for categories in that group.
                Example: {'Computer Science': [{'code': 'cs.AI', 'name': 'Artificial Intelligence'}, ...]}.
            </returns>
        </tool_def>
        """
        return list_arxiv_categories_impl()

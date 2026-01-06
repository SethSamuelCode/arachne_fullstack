from app.agents.tools.datetime_tool import get_current_datetime
from pydantic_ai import Agent, RunContext
from dataclasses import dataclass
from app.core.config import settings
from tavily import TavilyClient
from typing import TypeVar
from app.schemas.assistant import Deps
from app.schemas.spawn_agent_deps import SpawnAgentDeps
from app.schemas.models import GeminiModelName
from typing import Any
from pydantic_ai.models.google import GoogleModel
from app.schemas import DEFAULT_GEMINI_MODEL
from app.schemas.planning import Plan

TDeps = TypeVar("TDeps", bound=Deps | SpawnAgentDeps)

def _stringify(output: Any) -> str:
    """Convert various output types to a string representation."""
    if isinstance(output, str):
        return output
    elif isinstance(output, dict):
        return str(output)
    elif hasattr(output, "__str__"):
        return str(output)
    else:
        return repr(output)

def register_tools(agent: Agent[TDeps, str]) -> None:
    """Register tools to the given agent."""
    
    @agent.tool
    async def search_web(ctx: RunContext[TDeps], query: str, max_results: int = 5) -> str:
        """
        Search the web for information.

        Args:
            query: Search query string
            max_results: Maximum number of results to return

        Returns:
            WebSearchResponse with search results

        Raises:
            ValueError: If Tavily API key is not configured
            Exception: If search fails
        """
        client = TavilyClient(api_key=settings.TAVILY_API_KEY)
        response = client.search(query=query, search_depth="basic", max_results=max_results)
        results = []
        for r in response.get("results", []):
            title = r.get("title", "")
            url = r.get("url", "")
            snippet = (r.get("content", "") or "")
            results.append(f"**{title}**\nURL: {url}\nContent: {snippet}\n")
        return "\n---\n".join(results) if results else "No search results found."

    @agent.tool
    async def current_datetime(ctx: RunContext[TDeps]) -> str:
        """Get the current date and time.

        Use this tool when you need to know the current date or time.
        """
        return get_current_datetime()


    @agent.tool
    async def spawn_agent(
            ctx: RunContext[TDeps],
            user_input: str,
            system_prompt: str | None = None,
            model_name: GeminiModelName | None = None,
        ) -> str:
            """Delegate a sub-task to a new agent with a fresh context window the new agent has the same tools available as you do.

            Use this tool to:
            1. Isolate complex reasoning steps to prevent context pollution.
            2. Overcome context window limits by offloading work.
            3. Switch to a stronger model for difficult tasks.

            ARGS:
            - user_input: The specific instructions or question for the sub-agent. Be explicit and self-contained.
            - system_prompt: Define the sub-agent's role (e.g., "You are a Python expert"). Defaults to "You are a helpful AI assistant."
            - model_name: Select based on task difficulty:
                * 'gemini-2.5-flash-lite': Simple lookups, formatting, low latency.
                * 'gemini-2.5-flash': Standard tasks, summarization.
                * 'gemini-2.5-pro': Complex reasoning, coding, creative writing.
                * 'gemini-3-flash-preview': High speed, moderate reasoning.
                * 'gemini-3-pro-preview': MAX REASONING. Use for architecture, security analysis, or very hard problems.

            RETURNS:
            The sub-agent's final text response.
            """

            
            spawn_depth: int = getattr(ctx.deps, 'spawn_depth', 0)
            spawn_max_depth: int = getattr(ctx.deps, 'spawn_max_depth', 10)
            if spawn_depth >0:
                if spawn_depth >= spawn_max_depth:
                    return f"Error: spawn depth limit reached ({spawn_max_depth})."


            child_deps = SpawnAgentDeps(
                user_id=ctx.deps.user_id if hasattr(ctx.deps, 'user_id') else None,
                user_name=ctx.deps.user_name if hasattr(ctx.deps, 'user_name') else None,
                metadata=ctx.deps.metadata if hasattr(ctx.deps, 'metadata') else {},
                system_prompt=system_prompt if system_prompt is not None else "you are a helpful AI assistant.",
                model_name=model_name if model_name is not None else DEFAULT_GEMINI_MODEL,
                spawn_depth=spawn_depth + 1,
                spawn_max_depth=spawn_max_depth,
            )

            sub_model = GoogleModel(child_deps.model_name.value)
            sub_agent = Agent(
                deps_type=SpawnAgentDeps,
                model=sub_model,
                system_prompt=child_deps.system_prompt or "You are a helpful AI assistant.",
            )

            register_tools(sub_agent)

            result = await sub_agent.run(user_input, deps=child_deps)
            return _stringify(result.output)
            
    @agent.tool
    async def create_plan(
        ctx: RunContext[TDeps],
        plan: Plan
    ) -> str:
        """Create a new plan.

        Use this tool to create a structured plan with a list of tasks.
        
        Args:
            plan: The plan object containing the name and list of tasks (steps).

        Returns:
            The ID of the created plan.
        """
        from app.agents.tools.plan_service import get_plan_service
        plan_service = get_plan_service()
        plan_id = plan_service.create_plan(plan)
        return plan_id

    @agent.tool
    async def get_plan(
        ctx: RunContext[TDeps],
        plan_id: str
    ) -> Plan | str:
        """Retrieve a plan by its ID.

        Use this tool to fetch the details of an existing plan, including its tasks and status.

        Args:
            plan_id: The unique identifier of the plan to retrieve.

        Returns:
            The Plan object if found, or an error message.
        """
        from app.agents.tools.plan_service import get_plan_service
        plan_service = get_plan_service()
        plan = plan_service.get_plan(plan_id)
        return plan
    
    @agent.tool
    async def update_plan(
        ctx: RunContext[TDeps],
        plan_id: str,
        plan_data: Plan
    ) -> str:
        """Update an existing plan.

        Use this tool to modify a plan's details, such as marking tasks as completed, adding new tasks, or changing the plan name.

        Args:
            plan_id: The unique identifier of the plan to update.
            plan_data: The updated plan object.

        Returns:
            A confirmation message indicating the result of the update.
        """
        from app.agents.tools.plan_service import get_plan_service
        plan_service = get_plan_service()
        result = plan_service.update_plan(plan_id, plan_data)
        return result
    
    @agent.tool
    async def delete_plan(
        ctx: RunContext[TDeps],
        plan_id: str
    ) -> str:
        """Delete a plan.

        Use this tool to remove a plan when it is no longer needed.

        Args:
            plan_id: The unique identifier of the plan to delete.

        Returns:
            A confirmation message indicating the result of the deletion.
        """
        from app.agents.tools.plan_service import get_plan_service
        plan_service = get_plan_service()
        result = plan_service.delete_plan(plan_id)
        return result
    
    @agent.tool
    async def get_all_plans(
        ctx: RunContext[TDeps],
    ) -> list:
        """Retrieve a summary of all plans.

        Use this tool to get a list of all existing plans with their IDs, names, and descriptions.

        Returns:
            A list of tuples containing plan ID, name, and description.
        """
        from app.agents.tools.plan_service import get_plan_service
        plan_service = get_plan_service()
        result = plan_service.get_all_plans()
        return result

    @agent.tool
    async def s3_list_objects(ctx: RunContext[TDeps]) -> list[str]:
        """List all objects currently stored in the S3 bucket.

        Use this tool to see what files are available or to verify if a file exists before performing operations like download or overwrite.

        RETURNS:
            A list of strings, where each string is the key (name) of an object in the bucket.
        """
        from app.services.s3 import get_s3_service
        s3 = get_s3_service()
        return s3.list_objs()

    @agent.tool
    async def s3_upload_file(ctx: RunContext[TDeps], file_name: str, object_name: str) -> str:
        """Upload a local file from the server's filesystem to the S3 bucket.

        Use this tool when you have a file on disk (e.g., generated by another tool) and need to persist it to S3.

        ARGS:
            file_name: The absolute or relative path to the local file to upload.
            object_name: The key (name) to assign to the object in S3.

        RETURNS:
            A success message string.
        """
        from app.services.s3 import get_s3_service
        s3 = get_s3_service()
        s3.upload_file(file_name, object_name)
        return f"Successfully uploaded {file_name} to {object_name}"

    @agent.tool
    async def s3_download_file(ctx: RunContext[TDeps], object_name: str, file_name: str) -> str:
        """Download a file from the S3 bucket to the server's local filesystem.

        Use this tool to retrieve a file from S3 so it can be processed or read by other tools that utilize the local filesystem.

        ARGS:
            object_name: The key (name) of the object in S3 to download.
            file_name: The local path where the file should be saved.

        RETURNS:
            A success message string.
        """
        from app.services.s3 import get_s3_service
        s3 = get_s3_service()
        s3.download_file(object_name, file_name)
        return f"Successfully downloaded {object_name} to {file_name}"

    @agent.tool
    async def s3_upload_string_content(ctx: RunContext[TDeps], content: str, object_name: str) -> str:
        """Upload a string directly as a file to the S3 bucket, without creating a local file first.

        Use this tool to save text data, reports, or logs directly to S3.

        ARGS:
            content: The string content to be written to the file.
            object_name: The key (name) to assign to the object in S3.

        RETURNS:
            A success message string.
        """
        from app.services.s3 import get_s3_service
        s3 = get_s3_service()
        s3.upload_obj(content.encode('utf-8'), object_name)
        return f"Successfully uploaded content to {object_name}"

    @agent.tool
    async def s3_read_string_content(ctx: RunContext[TDeps], object_name: str) -> str:
        """Read the content of a file from S3 directly into a string.

        Use this tool to read text files (logs, config, notes) from S3 without saving them to disk.

        ARGS:
            object_name: The key (name) of the object in S3 to read.

        RETURNS:
            The UTF-8 decoded content of the file.
        """
        from app.services.s3 import get_s3_service
        s3 = get_s3_service()
        content = s3.download_obj(object_name)
        return content.decode('utf-8')

    @agent.tool
    async def s3_delete_object(ctx: RunContext[TDeps], object_name: str) -> str:
        """Delete an object from the S3 bucket.

        Use this tool to remove files that are no longer needed. Warning: This action is permanent.

        ARGS:
            object_name: The key (name) of the object to delete.

        RETURNS:
            A success message string.
        """
        from app.services.s3 import get_s3_service
        s3 = get_s3_service()
        s3.delete_obj(object_name)
        return f"Successfully deleted object {object_name}"

    @agent.tool
    async def s3_generate_presigned_download_url(ctx: RunContext[TDeps], object_name: str, expiration: int = 3600) -> str:
        """Generate a temporary public URL to access a private S3 object.

        Use this tool when you need to share a file link with a user or an external system.

        ARGS:
            object_name: The key (name) of the object in S3.
            expiration: Validity duration in seconds (default: 3600).

        RETURNS:
            A string containing the presigned URL.
        """
        from app.services.s3 import get_s3_service
        s3 = get_s3_service()
        return s3.generate_presigned_download_url(object_name, expiration)
    
    @agent.tool
    async def s3_generate_presigned_upload_post_url(ctx: RunContext[TDeps], object_name: str, expiration: int = 3600) -> str:
        """Generate a presigned POST URL and fields for uploading a file to S3.

        Use this tool when you need to enable a client/user to upload a file directly to S3 via a POST request.
        The returned dictionary contains the 'url' and specific 'fields' that MUST be included in the form data of the POST request.

        ARGS:
            object_name: The key (name) of the object in S3.
            expiration: Validity duration in seconds (default: 3600).

        RETURNS:
            A dictionary (as a string) with keys 'url' (the upload endpoint) and 'fields' (a dictionary of form fields required for authentication).
        """
        from app.services.s3 import get_s3_service
        s3 = get_s3_service()
        return s3.generate_presigned_post(object_name, expiration)

    @agent.tool
    async def s3_copy_file(ctx: RunContext[TDeps], source_object_name: str, dest_object_name: str) -> str:
        """Copy a file from one location to another within the S3 bucket.

        Use this tool to duplicate files, rename them (copy + delete), or create backups.

        ARGS:
            source_object_name: The key (name) of the existing object.
            dest_object_name: The key (name) for the new copy.

        RETURNS:
            A success message string.
        """
        from app.services.s3 import get_s3_service
        s3 = get_s3_service()
        s3.copy_file(source_object_name, dest_object_name)
        return f"Successfully copied {source_object_name} to {dest_object_name}"
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
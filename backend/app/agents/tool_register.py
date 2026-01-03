from app.agents.tools.datetime_tool import get_current_datetime
from pydantic_ai import Agent
from dataclasses import dataclass
from app.core.config import settings
from tavily import TavilyClient
from pydantic_ai import RunContext
from app.schemas.assistant import Deps

def register_tools(agent: Agent[Deps,str]) -> None:
    """Register tools to the given agent."""
    
    @agent.tool
    async def search_web(ctx: RunContext[Deps], query: str, max_results: int = 5) -> str:
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
    async def current_datetime(ctx: RunContext[Deps]) -> str:
        """Get the current date and time.

        Use this tool when you need to know the current date or time.
        """
        return get_current_datetime()
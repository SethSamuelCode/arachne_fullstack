from typing import Any, Literal, TypeVar
from uuid import uuid4

from google.genai.types import HarmBlockThreshold, HarmCategory, ThinkingLevel
from pydantic_ai import Agent, BinaryContent, RunContext, ToolReturn
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from tavily import TavilyClient

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
from app.schemas import DEFAULT_GEMINI_MODEL
from app.schemas.assistant import Deps
from app.schemas.models import GeminiModelName
from app.schemas.planning import Plan
from app.schemas.spawn_agent_deps import SpawnAgentDeps

# Type alias for image generation model selection
ImageModelName = Literal[
    "gemini-3-pro-image-preview",
    "imagen-4.0-generate-001",
    "imagen-4.0-ultra-generate-001",
    "imagen-4.0-fast-generate-001",
]

TDeps = TypeVar("TDeps", bound=Deps | SpawnAgentDeps)

# Safety settings with all filters disabled for maximum permissiveness
PERMISSIVE_SAFETY_SETTINGS: list[dict[str, Any]] = [
    {"category": HarmCategory.HARM_CATEGORY_HARASSMENT, "threshold": HarmBlockThreshold.OFF},
    {"category": HarmCategory.HARM_CATEGORY_HATE_SPEECH, "threshold": HarmBlockThreshold.OFF},
    {"category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, "threshold": HarmBlockThreshold.OFF},
    {"category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, "threshold": HarmBlockThreshold.OFF},
    {"category": HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY, "threshold": HarmBlockThreshold.OFF},
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
        ctx: RunContext[TDeps], query: str, max_results: int = 5
    ) -> str | dict[str, Any]:
        """Search the web for information using Tavily.

        Use this tool to search the web for current information, news, or general queries.

        ARGS:
            query: Search query string.
            max_results: Maximum number of results to return (default: 5).

        RETURNS:
            Formatted search results with titles, URLs, and content snippets.

        ERRORS:
            Returns {"error": True, "message": "...", "code": "..."} on failure:
            - InvalidAPIKey: Tavily API key is missing or invalid.
            - RateLimitExceeded: Too many requests, wait and retry.
            - NetworkError: Connection issue, retry after a moment.
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

        spawn_depth: int = getattr(ctx.deps, "spawn_depth", 0)
        spawn_max_depth: int = getattr(ctx.deps, "spawn_max_depth", 10)
        if spawn_depth > 0 and spawn_depth >= spawn_max_depth:
            return f"Error: spawn depth limit reached ({spawn_max_depth})."

        child_deps = SpawnAgentDeps(
            user_id=ctx.deps.user_id if hasattr(ctx.deps, "user_id") else None,
            user_name=ctx.deps.user_name if hasattr(ctx.deps, "user_name") else None,
            metadata=ctx.deps.metadata if hasattr(ctx.deps, "metadata") else {},
            system_prompt=system_prompt
            if system_prompt is not None
            else "you are a helpful AI assistant.",
            model_name=model_name if model_name is not None else DEFAULT_GEMINI_MODEL,
            spawn_depth=spawn_depth + 1,
            spawn_max_depth=spawn_max_depth,
        )

        # Model settings with safety filters disabled and thinking enabled
        model_settings = GoogleModelSettings(
            google_safety_settings=PERMISSIVE_SAFETY_SETTINGS,
            google_thinking_config={
                "thinking_level": ThinkingLevel.HIGH,
            },
        )

        sub_model = GoogleModel(child_deps.model_name.value, settings=model_settings)
        sub_agent = Agent(
            deps_type=SpawnAgentDeps,
            model=sub_model,
            system_prompt=child_deps.system_prompt or "You are a helpful AI assistant.",
        )

        register_tools(sub_agent)

        result = await sub_agent.run(user_input, deps=child_deps)
        return _stringify(result.output)

    @agent.tool
    async def create_plan(ctx: RunContext[TDeps], plan: Plan) -> str:
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
    async def get_plan(ctx: RunContext[TDeps], plan_id: str) -> Plan | str:
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
    async def update_plan(ctx: RunContext[TDeps], plan_id: str, plan_data: Plan) -> str:
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
    async def delete_plan(ctx: RunContext[TDeps], plan_id: str) -> str:
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
    @safe_tool
    async def s3_list_objects(ctx: RunContext[TDeps]) -> list[str] | dict[str, Any]:
        """List all objects currently stored in your S3 storage.

        Use this tool to see what files are available or to verify if a file exists
        before performing operations like download or overwrite.

        RETURNS:
            A list of strings, where each string is the key (name) of an object in your storage.
            Note: File paths are relative to your storage space.

        ERRORS:
            Returns {"error": True, "message": "...", "code": "..."} on failure:
            - ClientError: S3 connection or permission issue.
            - EndpointConnectionError: S3 service unavailable.
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
        ctx: RunContext[TDeps], file_name: str, object_name: str
    ) -> str | dict[str, Any]:
        """Upload a local file from the server's filesystem to your S3 storage.

        Use this tool when you have a file on disk (e.g., generated by another tool)
        and need to persist it to S3.

        ARGS:
            file_name: The absolute or relative path to the local file to upload.
            object_name: The key (name) to assign to the object in your storage.

        RETURNS:
            A success message string.

        ERRORS:
            Returns {"error": True, "message": "...", "code": "..."} on failure:
            - FileNotFoundError: Local file does not exist.
            - ClientError: S3 upload failed (permission denied, connection issue).
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
        ctx: RunContext[TDeps], object_name: str, file_name: str
    ) -> str | dict[str, Any]:
        """Download a file from your S3 storage to the server's local filesystem.

        Use this tool to retrieve a file from S3 so it can be processed or read by
        other tools that utilize the local filesystem.

        ARGS:
            object_name: The key (name) of the object in your storage to download.
            file_name: The local path where the file should be saved.

        RETURNS:
            A success message string.

        ERRORS:
            Returns {"error": True, "message": "...", "code": "..."} on failure:
            - NoSuchKey: The file does not exist in storage.
            - ClientError: S3 connection or permission issue.
            - PermissionError: Cannot write to local path.
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
        ctx: RunContext[TDeps], content: str, object_name: str
    ) -> str | dict[str, Any]:
        """Upload a string directly as a file to your S3 storage.

        Use this tool to save text data, reports, or logs directly to S3 without
        creating a local file first.

        ARGS:
            content: The string content to be written to the file.
            object_name: The key (name) to assign to the object in your storage.

        RETURNS:
            A success message string.

        ERRORS:
            Returns {"error": True, "message": "...", "code": "..."} on failure:
            - ClientError: S3 upload failed (permission denied, connection issue).
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
        ctx: RunContext[TDeps], object_name: str
    ) -> str | dict[str, Any]:
        """Read the content of a file from your S3 storage directly into a string.

        Use this tool to read text files (logs, config, notes) from S3 without
        saving them to disk.

        ARGS:
            object_name: The key (name) of the object in your storage to read.

        RETURNS:
            The UTF-8 decoded content of the file.

        ERRORS:
            Returns {"error": True, "message": "...", "code": "..."} on failure:
            - NoSuchKey: The file does not exist in storage. Use s3_list_objects to see available files.
            - UnicodeDecodeError: The file is not valid UTF-8 text (may be binary).
            - ClientError: S3 connection or permission issue.
        """
        from app.services.s3 import get_s3_service

        s3 = get_s3_service()
        user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
        full_key = f"{user_prefix}{object_name}"
        content = s3.download_obj(full_key)
        return content.decode("utf-8")

    @agent.tool
    @safe_tool
    async def s3_delete_object(ctx: RunContext[TDeps], object_name: str) -> str | dict[str, Any]:
        """Delete an object from your S3 storage.

        Use this tool to remove files that are no longer needed.
        Warning: This action is permanent.

        ARGS:
            object_name: The key (name) of the object to delete.

        RETURNS:
            A success message string.

        ERRORS:
            Returns {"error": True, "message": "...", "code": "..."} on failure:
            - NoSuchKey: The file does not exist in storage.
            - ClientError: S3 connection or permission issue.
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
        ctx: RunContext[TDeps], object_name: str, expiration: int = 3600
    ) -> str | dict[str, Any]:
        """Generate a temporary public URL to access a private S3 object.

        Use this tool when you need to share a file link with a user or an external system.
        Note: The URL will work even if the object doesn't exist (error occurs on access).

        ARGS:
            object_name: The key (name) of the object in your storage.
            expiration: Validity duration in seconds (default: 3600).

        RETURNS:
            A string containing the presigned URL.

        ERRORS:
            Returns {"error": True, "message": "...", "code": "..."} on failure:
            - ClientError: S3 connection or permission issue.
        """
        from app.services.s3 import get_s3_service

        s3 = get_s3_service()
        user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
        full_key = f"{user_prefix}{object_name}"
        return s3.generate_presigned_download_url(full_key, expiration)

    @agent.tool
    @safe_tool
    async def s3_generate_presigned_upload_post_url(
        ctx: RunContext[TDeps], object_name: str, expiration: int = 3600
    ) -> str | dict[str, Any]:
        """Generate a presigned POST URL and fields for uploading a file to your S3 storage.

        Use this tool when you need to enable a client/user to upload a file directly
        to S3 via a POST request. The returned dictionary contains the 'url' and
        specific 'fields' that MUST be included in the form data of the POST request.

        ARGS:
            object_name: The key (name) of the object in your storage.
            expiration: Validity duration in seconds (default: 3600).

        RETURNS:
            A dictionary (as a string) with keys 'url' (the upload endpoint) and
            'fields' (a dictionary of form fields required for authentication).

        ERRORS:
            Returns {"error": True, "message": "...", "code": "..."} on failure:
            - ClientError: S3 connection or permission issue.
        """
        from app.services.s3 import get_s3_service

        s3 = get_s3_service()
        user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
        full_key = f"{user_prefix}{object_name}"
        return s3.generate_presigned_post(full_key, expiration)

    @agent.tool
    @safe_tool
    async def s3_copy_file(
        ctx: RunContext[TDeps], source_object_name: str, dest_object_name: str
    ) -> str | dict[str, Any]:
        """Copy a file from one location to another within your S3 storage.

        Use this tool to duplicate files, rename them (copy + delete), or create backups.

        ARGS:
            source_object_name: The key (name) of the existing object.
            dest_object_name: The key (name) for the new copy.

        RETURNS:
            A success message string.

        ERRORS:
            Returns {"error": True, "message": "...", "code": "..."} on failure:
            - NoSuchKey: The source file does not exist in storage.
            - ClientError: S3 connection or permission issue.
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
        ctx: RunContext[TDeps], code: str, timeout: int = 600
    ) -> dict[str, Any]:
        """Execute Python code in an ephemeral Docker container.

        Use this tool to run Python scripts for data analysis, scraping, or complex calculations.

        Environment & Storage:
        - Internet access: Enabled.
        - Persistence: Ephemeral (reset after each call).
        - S3 Storage: You can store persistent data in your S3 storage using `boto3`.
          Environment variables are pre-configured: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `AWS_ENDPOINT_URL`, `S3_BUCKET`, and `S3_USER_PREFIX`.
          IMPORTANT: Always prefix your S3 keys with `S3_USER_PREFIX` to store files in your personal storage.
          Example:
          ```python
          import boto3, os
          s3 = boto3.client("s3")
          prefix = os.environ.get("S3_USER_PREFIX", "")
          s3.put_object(Bucket=os.environ["S3_BUCKET"], Key=f"{prefix}my_data.txt", Body="content")
          ```

        Available Libraries:
            * Web/HTTP: requests, httpx, aiohttp
            * Scraping: beautifulsoup4, lxml, html5lib, cssselect
            * Data Science: pandas, numpy, scipy, scikit-learn, statsmodels, sympy, networkx
            * Visualization: matplotlib, seaborn, plotly, imageio
            * Documents: pypdf, python-docx, python-pptx, openpyxl, xlrd, ebooklib, reportlab, weasyprint
            * Text/NLP: nltk, textblob, markdown, regex, html2text, inscriptis, unidecode, ftfy, chardet
            * Finance: yfinance (stock data), fredapi (economic data)
            * Databases: psycopg2-binary (PostgreSQL), pymysql (MySQL), pymongo (MongoDB), redis
            * APIs: pyjwt, authlib, cryptography, ecdsa, graphql-core, grpcio, protobuf
            * Geo: geopy, shapely
            * Image: opencv-python-headless, pytesseract (OCR), Pillow, qrcode, python-barcode, pyzbar
            * Date/Time: python-dateutil, pytz, arrow, pendulum
            * Data Formats: pyyaml, toml, xmltodict, defusedxml, jsonschema
            * Network: paramiko (SSH), dnspython, websockets
            * Cloud: boto3 (AWS)
            * Archives: py7zr
            * Media: mutagen, pydub, av (video)
            * Validation: pydantic, marshmallow, email-validator, phonenumbers
            * Fuzzy Matching: fuzzywuzzy, python-Levenshtein
            * Search: whoosh
            * Utilities: tqdm, cachetools, diskcache, joblib, faker, loguru, colorama

        ERRORS:
            Returns {"error": True, "message": "...", "code": "..."} on failure:
            - RuntimeError: Docker container failed to start or execute.
            - TimeoutError: Code execution exceeded timeout limit.
            - DockerException: Docker service unavailable.
        """
        from app.services.python import get_python_executor

        python_executor = get_python_executor()
        user_id = ctx.deps.user_id if ctx.deps.user_id else None
        result = await python_executor.execute_code(code, timeout, user_id=user_id)
        return result

    @agent.tool
    @safe_tool
    async def extract_webpage(
        ctx: RunContext[TDeps],
        url: str,
        extract_text: bool = True,
        max_length: int = 20000,
    ) -> dict[str, Any]:
        """Fetch and extract content from a webpage.

        Use this tool to read the content of a specific URL.
        - Prefer `search_web` first if you don't have a specific URL.
        - Use this to read documentation, articles, or reference material found via search.

        ARGS:
            url: The full URL to fetch (e.g. "https://docs.python.org/3/").
            extract_text:
                - True (Default): Returns parsed, readable text. Best for reasoning and summarization.
                - False: Returns raw HTML. Use only if layout/structure analysis is required.
            max_length: Maximum characters to return (def: 20000). Content is truncated if longer.

        RETURNS:
            Dict containing 'content', 'title', and metadata.

        ERRORS:
            Returns {"error": True, "message": "...", "code": "..."} on failure:
            - HTTPError: Failed to fetch URL (404, 500, etc.).
            - ConnectionError: Network issue or URL unreachable.
            - Timeout: Request took too long.
        """

        response = await extract_url(
            url=url,
            extract_text=extract_text,
            max_length=max_length,
        )
        return response.model_dump()

    @agent.tool
    async def s3_fetch_image(ctx: RunContext[TDeps], object_name: str) -> ToolReturn:
        """Fetch an image from S3 storage and load it for visual analysis.

        Use this tool when the user asks you to look at, analyze, describe, read,
        extract information from, or understand an image stored in their S3 storage.

        WHEN TO USE:
        - User says "look at", "analyze", "describe", "read", "extract from",
          "what's in", "explain", or "understand" an image/photo/screenshot/picture
        - User references a file with image extension (.png, .jpg, .jpeg, .webp,
          .heic, .heif) and wants visual analysis
        - User asks about contents of an image file they've uploaded

        WHEN NOT TO USE:
        - For non-image files (text, CSV, JSON, etc.) — use s3_read_string_content instead
        - When the user has already attached images to the current message (they're
          already in your context)
        - For listing files — use s3_list_objects first if you don't know the exact filename

        WORKFLOW:
        1. If user doesn't provide exact filename, call s3_list_objects first to find it
        2. Call this tool with the image filename
        3. Analyze the returned image and respond to user's question

        SUPPORTED FORMATS:
        PNG (.png), JPEG (.jpg, .jpeg), WebP (.webp), HEIC (.heic), HEIF (.heif)

        SIZE LIMIT: Maximum 20MB per image

        ARGS:
            object_name: The key (name) of the image in the user's storage
                         (e.g., 'photos/receipt.png', 'screenshots/error.jpg').
                         Do NOT include 'users/<id>/' prefix — it's added automatically.

        RETURNS:
            The image loaded into your context for visual analysis. You can then
            describe, analyze, or extract information from the image.
        """
        return await s3_fetch_image_impl(ctx, object_name)

    @agent.tool
    async def generate_image(
        ctx: RunContext[TDeps],
        prompt: str,
        model: ImageModelName = "imagen-4.0-generate-001",
        aspect_ratio: str = "1:1",
        image_size: str = "2K",
        number_of_images: int = 1,
        negative_prompt: str | None = None,
        filename: str | None = None,
    ) -> ToolReturn:
        """Generate images using Google's Gemini or Imagen models.

        Use this tool to create images from text descriptions. You have full control
        over model selection and generation parameters.

        MODEL SELECTION GUIDE:
        - `gemini-3-pro-image-preview`: Best for iterative refinement, conversational
          edits, and when you need 4K output. Supports back-and-forth image editing.
          Generates 1 image per call.
        - `imagen-4.0-generate-001`: Standard Imagen 4. Great balance of quality and
          speed for photorealistic images. Supports 1-4 images per call.
        - `imagen-4.0-ultra-generate-001`: Highest quality Imagen model. Best for
          professional-grade product photos, portraits, and detailed scenes where
          quality is paramount. Slower but superior results. Supports 1-4 images.
        - `imagen-4.0-fast-generate-001`: Fastest Imagen 4 variant. Use for quick
          iterations, drafts, or when speed matters more than maximum quality.
          Supports 1-4 images per call.

        ASPECT RATIOS:
        - Square: "1:1" (default, good for profile pics, icons)
        - Landscape: "16:9" (widescreen), "4:3" (standard), "3:2" (photo)
        - Portrait: "9:16" (mobile/stories), "3:4", "2:3"
        - Ultra-wide: "21:9" (cinematic, Gemini only)

        IMAGE SIZES:
        - "1K": Fastest generation, smaller file size
        - "2K": Good balance of quality and speed (default)
        - "4K": Highest quality (Gemini only, slower)

        ARGS:
            prompt: Detailed description of the image to generate. Be specific about
                    subject, style, lighting, composition, colors, and mood.
            model: Model to use (see guide above). Options:
                   "gemini-3-pro-image-preview", "imagen-4.0-generate-001",
                   "imagen-4.0-ultra-generate-001", "imagen-4.0-fast-generate-001"
            aspect_ratio: Image dimensions ratio (default: "1:1").
            image_size: Resolution - "1K", "2K", or "4K" (default: "2K").
            number_of_images: How many images to generate, 1-4 (Imagen only, default: 1).
            negative_prompt: What to avoid in the image (Imagen only).
                             Example: "blurry, low quality, distorted, watermark"
            filename: Custom filename without extension (default: auto-generated UUID).
                      Images are saved as PNG.

        RETURNS:
            Generated image(s) saved to S3 with presigned download URLs. The images
            are also loaded into your context for immediate visual inspection.

        ERRORS:
            If generation is blocked by safety filters, returns the rejection reason
            so you can modify your prompt and retry.
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
        query: str,
        search_field: Literal["all", "title", "abstract", "fulltext", "title_and_abstract"] = "all",
        year_from: int | None = None,
        year_to: int | None = None,
        min_citations: int | None = None,
        open_access_only: bool = False,
        oa_status: Literal["gold", "green", "hybrid", "bronze", "closed"] | None = None,
        publication_type: str | None = None,
        institution_id: str | None = None,
        author_id: str | None = None,
        concept_id: str | None = None,
        language: str | None = None,
        sort_by: Literal["relevance", "cited_by_count", "publication_date", "display_name"] = "relevance",
        sort_order: Literal["asc", "desc"] = "desc",
        page: int = 1,
        per_page: int = 25,
        include_abstract: bool = True,
        include_authors: bool = True,
    ) -> dict[str, Any]:
        """Search OpenAlex academic database for scholarly works.

        OpenAlex is an open catalog of 250M+ scholarly works, authors, venues, and
        institutions. It provides comprehensive metadata including citations, open
        access status, and institutional affiliations.

        WHEN TO USE:
        - Large-scale academic searches across all disciplines
        - Need citation metrics and open access information
        - Want to filter by institution, author, or concept
        - Need structured metadata (DOIs, ORCIDs, publication dates)
        - Looking for open access versions of papers
        - Searching by specific journal, conference, or publisher

        WHEN NOT TO USE:
        - Need AI-generated paper summaries (use search_semantic_scholar)
        - Looking for preprints not yet indexed (use search_arxiv)
        - Need paper embeddings for similarity search

        SEARCH FIELD OPTIONS:
        - "all": Search title, abstract, and fulltext (default, broadest)
        - "title": Search only paper titles (precise)
        - "abstract": Search only abstracts
        - "fulltext": Search full paper text (subset of works)
        - "title_and_abstract": Search both title and abstract

        OPEN ACCESS STATUS:
        - "gold": Published in an OA journal
        - "green": Free copy in a repository
        - "hybrid": OA in a subscription journal
        - "bronze": Free to read on publisher site
        - "closed": No free version available

        SORTING OPTIONS:
        - "relevance": Best match for search terms (default)
        - "cited_by_count": Most cited papers first
        - "publication_date": Newest or oldest papers
        - "display_name": Alphabetical by title

        ARGS:
            query: Search terms. Natural language queries work well.
            search_field: Which fields to search (default: "all").
            year_from: Minimum publication year (inclusive), e.g., 2020.
            year_to: Maximum publication year (inclusive), e.g., 2024.
            min_citations: Only return papers with at least this many citations.
            open_access_only: If True, only return papers with free full text.
            oa_status: Filter by specific OA status.
            publication_type: Filter by type - "article", "book", "dataset", etc.
            institution_id: Filter by institution OpenAlex ID (e.g., "I27837315" for MIT).
            author_id: Filter by author OpenAlex ID (e.g., "A5023888391").
            concept_id: Filter by research concept ID (e.g., "C41008148" for AI).
            language: Filter by ISO 639-1 language code (e.g., "en", "zh", "de").
            sort_by: How to sort results.
            sort_order: "desc" for descending, "asc" for ascending.
            page: Page number (1-indexed). First page = 1.
            per_page: Results per page, 1-200 (default: 25).
            include_abstract: Include paper abstracts in results.
            include_authors: Include author information.

        RETURNS:
            Dictionary with total_count, page, per_page, and results list containing
            papers with id, doi, title, publication_year, cited_by_count, is_oa,
            oa_status, pdf_url, abstract, authors, and source_name.

        ERRORS:
            - API timeout: OpenAlex may be slow during peak times
            - Invalid filter: Check parameter values match allowed options
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
        query: str,
        year: str | None = None,
        venue: str | None = None,
        fields_of_study: list[str] | None = None,
        publication_types: list[str] | None = None,
        open_access_only: bool = False,
        min_citation_count: int | None = None,
        offset: int = 0,
        limit: int = 20,
        include_abstract: bool = True,
        include_tldr: bool = True,
        include_authors: bool = True,
        include_venue: bool = True,
        include_embedding: bool = False,
    ) -> dict[str, Any]:
        """Search Semantic Scholar for academic papers with AI-enhanced features.

        Semantic Scholar provides AI-powered paper search with unique features like
        TLDR summaries (AI-generated paper summaries), influential citation tracking,
        and paper embeddings for similarity search.

        WHEN TO USE:
        - Need AI-generated paper summaries (TLDR) for quick understanding
        - Want to identify influential citations (not just citation count)
        - Looking for CS/AI papers (excellent coverage)
        - Need paper embeddings for building similarity features
        - Want to filter by specific publication types or venues

        WHEN NOT TO USE:
        - Need boolean query syntax (use search_semantic_scholar_bulk)
        - Want more than 1000 results (use bulk search)
        - Need institution/affiliation filtering (use search_openalex)
        - Looking for very recent preprints (use search_arxiv)

        YEAR FILTER FORMATS:
        - Single year: "2020"
        - Range: "2016-2020"
        - From year onwards: "2010-" (2010 to present)
        - Up to year: "-2015" (papers before 2015)

        FIELDS OF STUDY (common values):
        "Computer Science", "Medicine", "Physics", "Biology", "Chemistry",
        "Mathematics", "Engineering", "Psychology", "Economics"

        PUBLICATION TYPES:
        "JournalArticle", "Conference", "Review", "Book", "Dataset", "ClinicalTrial"

        ARGS:
            query: Plain-text search query. No special syntax supported.
            year: Year or range. Examples: "2020", "2016-2020", "2010-", "-2015".
            venue: Comma-separated venue names (e.g., "Nature,Science,ICML").
            fields_of_study: List of fields like ["Computer Science", "Medicine"].
            publication_types: List of types like ["JournalArticle", "Conference"].
            open_access_only: If True, only return papers with free PDFs.
            min_citation_count: Minimum number of citations required.
            offset: Starting index (0-based) for pagination.
            limit: Number of results (1-100, default: 20).
            include_abstract: Include full paper abstracts.
            include_tldr: Include AI-generated TLDR summaries (RECOMMENDED).
            include_authors: Include author names and IDs.
            include_venue: Include publication venue info.
            include_embedding: Include SPECTER v2 paper embeddings.

        RETURNS:
            Dictionary with total, offset, next_offset, and data list containing
            papers with paper_id, title, abstract, year, citation_count,
            influential_citation_count, is_open_access, open_access_pdf, tldr,
            authors, venue, fields_of_study, publication_types, and external_ids.

        ERRORS:
            - Rate limit (429): Wait and retry. Consider adding API key.
            - No results: Try broader search terms or fewer filters.
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
        query: str,
        year: str | None = None,
        venue: str | None = None,
        fields_of_study: list[str] | None = None,
        publication_types: list[str] | None = None,
        open_access_only: bool = False,
        min_citation_count: int | None = None,
        sort_by: Literal["paperId", "publicationDate", "citationCount"] = "paperId",
        sort_order: Literal["asc", "desc"] = "asc",
        token: str | None = None,
        include_abstract: bool = True,
        include_tldr: bool = False,
    ) -> dict[str, Any]:
        """Bulk search Semantic Scholar with boolean query support and pagination.

        This endpoint supports boolean query syntax and can access up to 10 million
        results through pagination tokens. Use this for systematic reviews, dataset
        building, or when you need precise query control.

        WHEN TO USE:
        - Need boolean query operators (AND, OR, NOT)
        - Want to retrieve more than 1000 results
        - Building datasets or doing systematic literature reviews
        - Need exact phrase matching or prefix search
        - Want to sort by citation count or publication date

        WHEN NOT TO USE:
        - Simple searches (use search_semantic_scholar instead)
        - Need quick results with TLDR summaries (bulk is slower)
        - Need paper embeddings (not available in bulk)

        BOOLEAN QUERY SYNTAX:
        - AND: "machine AND learning" or "machine learning" (implicit)
        - OR: "machine | learning" (either term)
        - NOT: "-excluded_term" (prefix with minus)
        - Phrase: '"exact phrase"' (wrap in double quotes)
        - Prefix: "neuro*" (matches neuroscience, neural, etc.)
        - Grouping: "(neural | deep) AND learning"
        - Fuzzy: "word~2" (edit distance of 2)

        SORTING OPTIONS:
        - "paperId": Default, stable ordering for pagination
        - "publicationDate": Newest or oldest first
        - "citationCount": Most or least cited first

        ARGS:
            query: Boolean query string. Supports AND, OR, NOT, phrases, wildcards.
            year: Year or range filter (same as relevance search).
            venue: Comma-separated venue names.
            fields_of_study: List of fields to filter by.
            publication_types: List of publication types.
            open_access_only: Only papers with free PDFs.
            min_citation_count: Minimum citation count.
            sort_by: Sort field - "paperId", "publicationDate", or "citationCount".
            sort_order: "asc" or "desc".
            token: Continuation token from previous response for pagination.
            include_abstract: Include paper abstracts.
            include_tldr: Include TLDR summaries (adds latency).

        RETURNS:
            Dictionary with total, token (for next page), and data list.
            When token is None, there are no more results.

        PAGINATION:
            1. First call: Don't pass token
            2. Check response for token field
            3. If token is not None, call again with that token
            4. Repeat until token is None
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
        query: str | None = None,
        id_list: list[str] | None = None,
        search_field: Literal["all", "title", "abstract", "author", "category", "comment", "journal_ref"] = "all",
        categories: list[str] | None = None,
        submitted_after: str | None = None,
        submitted_before: str | None = None,
        sort_by: Literal["relevance", "lastUpdatedDate", "submittedDate"] = "relevance",
        sort_order: Literal["ascending", "descending"] = "descending",
        start: int = 0,
        max_results: int = 20,
    ) -> dict[str, Any]:
        """Search arXiv preprint repository for scientific papers.

        arXiv is a free, open-access repository of preprints in physics, mathematics,
        computer science, quantitative biology, quantitative finance, statistics,
        electrical engineering, and economics. Papers are available immediately upon
        submission, often months before peer-reviewed publication.

        WHEN TO USE:
        - Finding cutting-edge research before peer review
        - Physics, mathematics, CS, statistics, or quantitative papers
        - Need immediate access to full PDFs (always free)
        - Looking for specific arXiv IDs
        - Want to track recent submissions in a field
        - Need papers by exact arXiv category

        WHEN NOT TO USE:
        - Need AI summaries (use search_semantic_scholar)
        - Need citation counts (use search_openalex or search_semantic_scholar)
        - Looking for biology, medicine, or social science (limited coverage)
        - Need institution or author affiliation filters

        SEARCH FIELD OPTIONS:
        - "all": Search all fields (default)
        - "title": Paper titles only
        - "abstract": Abstracts only
        - "author": Author names
        - "category": Category codes
        - "comment": Author comments
        - "journal_ref": Journal references

        COMMON CATEGORY CODES:
        Computer Science: cs.AI, cs.CL (NLP), cs.CV, cs.LG (ML), cs.NE, cs.RO
        Statistics: stat.ML, stat.TH, stat.ME
        Physics: quant-ph, hep-th, cond-mat.*, astro-ph.*
        Math: math.OC (optimization), math.PR (probability)

        Use list_arxiv_categories to see all valid category codes.

        DATE FORMAT:
        Use YYYYMMDD (e.g., "20230101") for date filters.

        ARGS:
            query: Search terms. Can use inline field prefixes like "ti:quantum AND au:smith".
            id_list: List of specific arXiv IDs (e.g., ["2301.00001", "cs/0001001"]).
            search_field: Limit search to specific field.
            categories: Filter by arXiv category codes (e.g., ["cs.AI", "cs.LG"]).
            submitted_after: Only papers submitted after this date (YYYYMMDD).
            submitted_before: Only papers submitted before this date (YYYYMMDD).
            sort_by: Sort by "relevance", "lastUpdatedDate", or "submittedDate".
            sort_order: "ascending" or "descending".
            start: Starting index for pagination (0-based).
            max_results: Number of results (max 2000 per request).

        RETURNS:
            Dictionary with total_results, start_index, items_per_page, and entries
            list containing papers with id, title, summary, authors, published,
            updated, categories, primary_category, pdf_url, abs_url, doi,
            journal_ref, and comment.

        RATE LIMITING:
            arXiv requires 3-second delays between requests (automatic).

        ERRORS:
            - Query too broad: arXiv limits to 30000 results total
            - Invalid category: Use list_arxiv_categories to check valid codes
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
        """List all arXiv category codes with their names and groups.

        Use this tool to discover valid arXiv category codes for filtering searches.
        arXiv uses a hierarchical category system organized by research discipline.

        WHEN TO USE:
        - Need to find the correct category code for a research area
        - Want to see all categories in a discipline (e.g., all CS categories)
        - Unsure which category code to use in search_arxiv

        RETURNS:
            Dictionary with:
            - categories: Dict mapping code to {"name": ..., "group": ...}
            - by_group: Dict mapping group name to list of {"code": ..., "name": ...}

        CATEGORY GROUPS:
        - Computer Science (cs.*): 40+ categories including AI, ML, NLP, CV
        - Statistics (stat.*): ML, methodology, theory, applications
        - Mathematics (math.*): 30+ categories including optimization, probability
        - Physics: Multiple archives (physics.*, quant-ph, hep-*, cond-mat.*)
        - Quantitative Biology (q-bio.*): Genomics, neuroscience, etc.
        - Quantitative Finance (q-fin.*): Pricing, risk management, etc.
        - Electrical Engineering (eess.*): Signal processing, image/video, audio
        - Economics (econ.*): Econometrics, general economics, theory

        EXAMPLES:
            # Get all categories
            categories = list_arxiv_categories()

            # Use in search
            search_arxiv("neural network", categories=["cs.LG", "cs.NE", "stat.ML"])
        """
        return list_arxiv_categories_impl()

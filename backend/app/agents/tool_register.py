from typing import Any, Literal, TypeVar
from uuid import uuid4

from google.genai.types import HarmBlockThreshold, HarmCategory
from pydantic_ai import Agent, BinaryContent, RunContext, ToolReturn
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from tavily import TavilyClient

from app.agents.tools.datetime_tool import get_current_datetime
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

        # Model settings with safety filters disabled
        model_settings = GoogleModelSettings(
            google_safety_settings=PERMISSIVE_SAFETY_SETTINGS,
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
    async def s3_list_objects(ctx: RunContext[TDeps]) -> list[str]:
        """List all objects currently stored in your S3 storage.

        Use this tool to see what files are available or to verify if a file exists before performing operations like download or overwrite.

        RETURNS:
            A list of strings, where each string is the key (name) of an object in your storage.
            Note: File paths are relative to your storage space.
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
    async def s3_upload_file(ctx: RunContext[TDeps], file_name: str, object_name: str) -> str:
        """Upload a local file from the server's filesystem to your S3 storage.

        Use this tool when you have a file on disk (e.g., generated by another tool) and need to persist it to S3.

        ARGS:
            file_name: The absolute or relative path to the local file to upload.
            object_name: The key (name) to assign to the object in your storage.

        RETURNS:
            A success message string.
        """
        from app.services.s3 import get_s3_service

        s3 = get_s3_service()
        user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
        full_key = f"{user_prefix}{object_name}"
        s3.upload_file(file_name, full_key)
        return f"Successfully uploaded {file_name} to {object_name}"

    @agent.tool
    async def s3_download_file(ctx: RunContext[TDeps], object_name: str, file_name: str) -> str:
        """Download a file from your S3 storage to the server's local filesystem.

        Use this tool to retrieve a file from S3 so it can be processed or read by other tools that utilize the local filesystem.

        ARGS:
            object_name: The key (name) of the object in your storage to download.
            file_name: The local path where the file should be saved.

        RETURNS:
            A success message string.
        """
        from app.services.s3 import get_s3_service

        s3 = get_s3_service()
        user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
        full_key = f"{user_prefix}{object_name}"
        s3.download_file(full_key, file_name)
        return f"Successfully downloaded {object_name} to {file_name}"

    @agent.tool
    async def s3_upload_string_content(
        ctx: RunContext[TDeps], content: str, object_name: str
    ) -> str:
        """Upload a string directly as a file to your S3 storage, without creating a local file first.

        Use this tool to save text data, reports, or logs directly to S3.

        ARGS:
            content: The string content to be written to the file.
            object_name: The key (name) to assign to the object in your storage.

        RETURNS:
            A success message string.
        """
        from app.services.s3 import get_s3_service

        s3 = get_s3_service()
        user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
        full_key = f"{user_prefix}{object_name}"
        s3.upload_obj(content.encode("utf-8"), full_key)
        return f"Successfully uploaded content to {object_name}"

    @agent.tool
    async def s3_read_string_content(ctx: RunContext[TDeps], object_name: str) -> str:
        """Read the content of a file from your S3 storage directly into a string.

        Use this tool to read text files (logs, config, notes) from S3 without saving them to disk.

        ARGS:
            object_name: The key (name) of the object in your storage to read.

        RETURNS:
            The UTF-8 decoded content of the file.
        """
        from app.services.s3 import get_s3_service

        s3 = get_s3_service()
        user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
        full_key = f"{user_prefix}{object_name}"
        content = s3.download_obj(full_key)
        return content.decode("utf-8")

    @agent.tool
    async def s3_delete_object(ctx: RunContext[TDeps], object_name: str) -> str:
        """Delete an object from your S3 storage.

        Use this tool to remove files that are no longer needed. Warning: This action is permanent.

        ARGS:
            object_name: The key (name) of the object to delete.

        RETURNS:
            A success message string.
        """
        from app.services.s3 import get_s3_service

        s3 = get_s3_service()
        user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
        full_key = f"{user_prefix}{object_name}"
        s3.delete_obj(full_key)
        return f"Successfully deleted object {object_name}"

    @agent.tool
    async def s3_generate_presigned_download_url(
        ctx: RunContext[TDeps], object_name: str, expiration: int = 3600
    ) -> str:
        """Generate a temporary public URL to access a private S3 object.

        Use this tool when you need to share a file link with a user or an external system.

        ARGS:
            object_name: The key (name) of the object in your storage.
            expiration: Validity duration in seconds (default: 3600).

        RETURNS:
            A string containing the presigned URL.
        """
        from app.services.s3 import get_s3_service

        s3 = get_s3_service()
        user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
        full_key = f"{user_prefix}{object_name}"
        return s3.generate_presigned_download_url(full_key, expiration)

    @agent.tool
    async def s3_generate_presigned_upload_post_url(
        ctx: RunContext[TDeps], object_name: str, expiration: int = 3600
    ) -> str:
        """Generate a presigned POST URL and fields for uploading a file to your S3 storage.

        Use this tool when you need to enable a client/user to upload a file directly to S3 via a POST request.
        The returned dictionary contains the 'url' and specific 'fields' that MUST be included in the form data of the POST request.

        ARGS:
            object_name: The key (name) of the object in your storage.
            expiration: Validity duration in seconds (default: 3600).

        RETURNS:
            A dictionary (as a string) with keys 'url' (the upload endpoint) and 'fields' (a dictionary of form fields required for authentication).
        """
        from app.services.s3 import get_s3_service

        s3 = get_s3_service()
        user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
        full_key = f"{user_prefix}{object_name}"
        return s3.generate_presigned_post(full_key, expiration)

    @agent.tool
    async def s3_copy_file(
        ctx: RunContext[TDeps], source_object_name: str, dest_object_name: str
    ) -> str:
        """Copy a file from one location to another within your S3 storage.

        Use this tool to duplicate files, rename them (copy + delete), or create backups.

        ARGS:
            source_object_name: The key (name) of the existing object.
            dest_object_name: The key (name) for the new copy.

        RETURNS:
            A success message string.
        """
        from app.services.s3 import get_s3_service

        s3 = get_s3_service()
        user_prefix = f"users/{ctx.deps.user_id}/" if ctx.deps.user_id else ""
        source_key = f"{user_prefix}{source_object_name}"
        dest_key = f"{user_prefix}{dest_object_name}"
        s3.copy_file(source_key, dest_key)
        return f"Successfully copied {source_object_name} to {dest_object_name}"

    @agent.tool
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
        """
        from app.services.python import get_python_executor

        python_executor = get_python_executor()
        user_id = ctx.deps.user_id if ctx.deps.user_id else None
        result = await python_executor.execute_code(code, timeout, user_id=user_id)
        return result

    @agent.tool
    async def extract_webpage(
        ctx: RunContext[TDeps],
        url: str,
        extract_text: bool = True,
        max_length: int = 20000,
    ) -> dict[str, Any]:
        """Fetch and extract content from a webpage.

        Use this tool to read the content of a specific URL.
        - Prefer `search_web` first if you don't have a specific URL.
        - Use this to read documentation libraries, articles, or reference material found via search.

        ARGS:
            url: The full URL to fetch (e.g. "https://docs.python.org/3/").
            extract_text:
                - True (Default): Returns parsed, readable text. Best for reasoning and summarization.
                - False: Returns raw HTML. Use only if layout/structure analysis is required.
            max_length: Maximum characters to return (def: 10000). Content is truncated if longer.

        RETURNS:
            Dict containing 'content', 'title', and metadata.
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

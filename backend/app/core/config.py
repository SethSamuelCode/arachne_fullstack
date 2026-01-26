"""Application configuration using Pydantic BaseSettings."""
# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals

from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import computed_field, field_validator, ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict


def _sanitize_env_string(value: str) -> str:
    """Sanitize an environment variable string value.

    Removes whitespace, quotes, and control characters to prevent issues with:
    - Trailing carriage returns (\\r) or newlines (\\n) from Windows line endings
    - Accidental quotes around values in env files or Azure Portal
    - Leading/trailing whitespace from copy-paste errors

    Args:
        value: The raw string value from environment variable.

    Returns:
        Cleaned string with quotes, whitespace, and control characters removed.
    """
    # Strip whitespace first
    value = value.strip()
    # Remove surrounding quotes (both single and double)
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        value = value[1:-1].strip()
    # Remove any remaining control characters (CR, LF, TAB)
    value = value.replace("\r", "").replace("\n", "").replace("\t", "")
    return value


def _sanitize_pem_key(value: str) -> str:
    """Sanitize a PEM key environment variable.

    PEM keys require actual newlines between header, content, and footer.
    This function handles:
    - Escaped \\n literals (from .env files) → real newlines
    - Surrounding quotes from copy-paste
    - Trailing whitespace

    Args:
        value: The raw PEM key string from environment variable.

    Returns:
        Properly formatted PEM key with real newlines.
    """
    # Strip whitespace first
    value = value.strip()
    # Remove surrounding quotes (both single and double)
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        value = value[1:-1].strip()
    # Convert escaped \n to actual newlines (common in .env files)
    value = value.replace("\\n", "\n")
    # Remove carriage returns (Windows line endings)
    value = value.replace("\r", "")
    return value


def find_env_file() -> Path | None:
    """Find .env file in current or parent directories."""
    current = Path.cwd()
    for path in [current, current.parent]:
        env_file = path / ".env"
        if env_file.exists():
            return env_file
    return None


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=find_env_file(),
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
    )

    # === Project ===
    PROJECT_NAME: str = "arachne_fullstack"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = False
    ENVIRONMENT: Literal["development", "local", "staging", "production"] = "local"

    # === Logfire ===
    LOGFIRE_TOKEN: str | None = None
    LOGFIRE_SERVICE_NAME: str = "arachne_fullstack"
    LOGFIRE_ENVIRONMENT: str = "development"

    # === Database (PostgreSQL async) ===
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = "arachne_fullstack"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL(self) -> str:
        """Build async PostgreSQL connection URL."""
        return (
            f"postgresql+asyncpg://{quote_plus(self.POSTGRES_USER)}:{quote_plus(self.POSTGRES_PASSWORD)}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL_SYNC(self) -> str:
        """Build sync PostgreSQL connection URL (for Alembic)."""
        return (
            f"postgresql://{quote_plus(self.POSTGRES_USER)}:{quote_plus(self.POSTGRES_PASSWORD)}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # Pool configuration
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30

    # === Auth (JWT with EdDSA/Ed25519) ===
    # Algorithm is auto-determined: EdDSA if keys present, HS256 fallback otherwise
    SECRET_KEY: str = "change-me-in-production-use-openssl-rand-hex-32"
    JWT_PRIVATE_KEY: str | None = None  # Ed25519 private key for signing tokens
    JWT_PUBLIC_KEY: str | None = None  # Ed25519 public key for verifying tokens
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 60 minutes
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # === Internal API (for trusted server-to-server communication) ===
    # Used by Next.js frontend to bypass CSRF for proxied requests
    INTERNAL_API_KEY: str | None = None

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str, info: ValidationInfo) -> str:
        """Validate and sanitize SECRET_KEY, ensuring it's secure in production."""
        # Sanitize first to handle copy-paste issues
        v = _sanitize_env_string(v)
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        # Get environment from values if available
        env = info.data.get("ENVIRONMENT", "local") if info.data else "local"
        if v == "change-me-in-production-use-openssl-rand-hex-32" and env == "production":
            raise ValueError(
                "SECRET_KEY must be changed in production! "
                "Generate a secure key with: openssl rand -hex 32"
            )
        return v

    @field_validator("INTERNAL_API_KEY")
    @classmethod
    def validate_internal_api_key(cls, v: str | None) -> str | None:
        """Sanitize INTERNAL_API_KEY if provided."""
        if v is None:
            return None
        return _sanitize_env_string(v)

    @field_validator("JWT_PRIVATE_KEY", "JWT_PUBLIC_KEY")
    @classmethod
    def validate_jwt_keys(cls, v: str | None, info: ValidationInfo) -> str | None:
        """Validate and sanitize JWT keys, ensuring they're set in production for EdDSA."""
        if v is None:
            env = info.data.get("ENVIRONMENT", "local") if info.data else "local"
            if env == "production":
                raise ValueError(
                    f"{info.field_name} must be set in production for EdDSA! "
                    "Generate Ed25519 keys with: openssl genpkey -algorithm Ed25519 -out private_key.pem && "
                    "openssl pkey -in private_key.pem -pubout -out public_key.pem"
                )
            return None
        # Use PEM-specific sanitizer that preserves/converts newlines
        return _sanitize_pem_key(v)

    # === Redis ===
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None
    REDIS_DB: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_URL(self) -> str:
        """Build Redis connection URL."""
        if self.REDIS_PASSWORD:
            return f"redis://:{quote_plus(self.REDIS_PASSWORD)}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # === Rate Limiting ===
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_PERIOD: int = 60  # seconds

    # === Celery ===
    @computed_field  # type: ignore[prop-decorator]
    @property
    def CELERY_BROKER_URL(self) -> str:
        return self.REDIS_URL

    @computed_field  # type: ignore[prop-decorator]
    @property
    def CELERY_RESULT_BACKEND(self) -> str:
        return self.REDIS_URL

    # === File Storage (S3/MinIO) ===
    S3_ENDPOINT: str | None = None
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_BUCKET: str = "arachne_fullstack"
    S3_REGION: str = "us-east-1"

    # Storage proxy URL for sandbox containers (auto-detected if not set)
    # Example: "http://host.docker.internal:8000/api/v1/storage"
    STORAGE_PROXY_URL: str | None = None

    # === AI Agent (pydantic_ai, openai) ===
    OPENAI_API_KEY: str = ""
    AI_MODEL: str = "gpt-4o-mini"
    AI_TEMPERATURE: float = 0.7
    AI_FRAMEWORK: str = "pydantic_ai"
    LLM_PROVIDER: str = "openai"

    # === Agent Execution Limits ===
    # These control how the agent can chain tool calls and iterate
    AGENT_MAX_REQUESTS: int = 100  # Max model requests per agent run
    AGENT_MAX_TOOL_CALLS: int = 200  # Max tool calls per agent run
    AGENT_OUTPUT_RETRIES: int = 50  # Retries for output validation (allows tool chaining)
    AGENT_TOOL_RETRIES: int = 3  # Retries for individual tool failures
    AGENT_STREAM_THINKING: bool = True  # Send thinking traces to client

    # === Image Generation (Google Gemini / Imagen) ===
    GOOGLE_API_KEY: str = ""
    GEMINI_IMAGE_MODEL: str = "gemini-3-pro-image-preview"
    IMAGEN_MODEL: str = "imagen-4.0-generate-001"
    IMAGE_GEN_DEFAULT_ASPECT_RATIO: str = "1:1"
    IMAGE_GEN_DEFAULT_SIZE: str = "2K"
    IMAGE_GEN_DEFAULT_COUNT: int = 1

    # === System Prompt Caching ===
    # Enable Gemini's CachedContent API for system prompts + tools (75% cost reduction)
    # Requires Redis for cache key storage
    # Caches system prompt AND tool definitions together per Gemini API requirement
    # (system_instruction, tools, and tool_config must all be cached together)
    ENABLE_SYSTEM_PROMPT_CACHING: bool = True
    # Cache TTL in seconds (default 15 minutes). Gemini cache gets +300s buffer.
    # Minimum 60 seconds (Gemini API constraint).
    GOOGLE_CACHE_TTL_SECONDS: int = 900

    # === Pinned Content Caching ===
    # Max percentage of model's token budget allowed for pinned content (files, images, etc.)
    # Budget = model_max_tokens * (MAX_PINNED_CONTEXT_PERCENT / 100)
    MAX_PINNED_CONTEXT_PERCENT: int = 40
    # Warning threshold - show warning when pinned content exceeds this percentage
    PINNED_CONTEXT_WARNING_PERCENT: int = 30
    # Maximum file size for individual pinned files (100MB - Gemini limit for media)
    MAX_PINNED_FILE_SIZE_MB: int = 100

    @field_validator("GOOGLE_CACHE_TTL_SECONDS")
    @classmethod
    def validate_cache_ttl_minimum(cls, v: int) -> int:
        """Validate cache TTL is at least 60 seconds (Gemini API minimum)."""
        if v < 60:
            msg = "GOOGLE_CACHE_TTL_SECONDS must be at least 60 seconds (Gemini API minimum)"
            raise ValueError(msg)
        return v

    @field_validator(
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "REDIS_PASSWORD",
        "TAVILY_API_KEY",
        "OPENALEX_API_KEY",
        "SEMANTIC_SCHOLAR_API_KEY",
        mode="before",
    )
    @classmethod
    def sanitize_sensitive_strings(cls, v: str | None) -> str | None:
        """Sanitize sensitive string fields to handle copy-paste issues."""
        if v is None or v == "":
            return v
        return _sanitize_env_string(v)

    # === CORS ===
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8080"]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: list[str] = ["*"]
    CORS_ALLOW_HEADERS: list[str] = ["*"]

    # === Proxy Configuration ===
    # Trusted hosts for ProxyHeadersMiddleware (comma-separated IPs or CIDRs)
    # Use "*" for local development, restrict in production to docker_gwbridge gateway
    # Find your gateway: docker network inspect docker_gwbridge --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}'
    TRUSTED_PROXY_HOSTS: str = "*"

    @field_validator("CORS_ORIGINS")
    @classmethod
    def validate_cors_origins(cls, v: list[str], info: ValidationInfo) -> list[str]:
        """Warn if CORS_ORIGINS is too permissive in production."""
        env = info.data.get("ENVIRONMENT", "local") if info.data else "local"
        if "*" in v and env == "production":
            raise ValueError(
                "CORS_ORIGINS cannot contain '*' in production! Specify explicit allowed origins."
            )
        return v

    # == Web Search (Tavily) ===
    TAVILY_API_KEY: str | None = None

    # === Academic Search APIs ===
    # OpenAlex: API key for premium rate limits (takes precedence over email)
    OPENALEX_API_KEY: str | None = None
    # OpenAlex: Email for "polite pool" (higher rate limits, no key required)
    OPENALEX_EMAIL: str | None = None
    # Semantic Scholar: Optional API key for higher rate limits (free tier available)
    SEMANTIC_SCHOLAR_API_KEY: str | None = None
    # arXiv: No authentication required

    # timezone: str = "UTC"
    TZ: str = "Pacific/Auckland"

    SYSTEM_PROMPT: str = "You are Arachne, an advanced AI assistant designed to help users by providing accurate and relevant information. You have access to a variety of tools and resources to assist you in answering questions and solving problems."

    PYTHON_SANDBOX_IMAGE: str = "python-sandbox:latest"
    SANDBOX_TIMEOUT_SECONDS: int = 600  # 10 minutes

settings = Settings()

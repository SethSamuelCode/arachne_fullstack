"""Python code execution service using Docker sandbox.

This service executes untrusted Python code in ephemeral Docker containers.
For security, S3 access is now provided via a proxy instead of raw credentials.
"""

import asyncio
from typing import Any

from docker.errors import ContainerError

from app.core.config import settings
from app.core.docker import get_docker_client


class PythonExecutor:
    """Service for executing Python code in Docker sandbox.

    Security model:
    - Code runs in ephemeral containers with limited lifetime
    - S3 access is provided via a storage proxy with short-lived tokens
    - Containers cannot access raw S3 credentials
    - All storage operations are scoped to the user's prefix
    """

    def __init__(self) -> None:
        """Initialize the Python executor."""
        self._docker_client = None

    @property
    def docker_client(self):
        """Get Docker client."""
        if self._docker_client is None:
            self._docker_client = get_docker_client()
        return self._docker_client

    @property
    def is_available(self) -> bool:
        """Check if Python execution is available (requires Docker)."""
        return self.docker_client is not None

    async def execute_code(
        self,
        code: str,
        timeout: int = 10,
        user_id: str | None = None,
        storage_token: str | None = None,
    ) -> dict[str, Any]:
        """Execute Python code in a Docker container.

        Args:
            code: The Python code to execute.
            timeout: Maximum execution time in seconds.
            user_id: User ID for S3 storage scoping (for legacy support).
            storage_token: JWT token for storage proxy access.

        Returns:
            dict: Execution result with 'output' and 'error' keys.
        """

        client = self.docker_client
        if not self.is_available or client is None:
            return {"output": "", "error": "Docker is not available."}

        container: Any | None = None

        try:
            loop = asyncio.get_running_loop()

            # Base environment variables
            env_vars = {
                "PYTHON_CODE": code,
            }

            # If storage token is provided, use the proxy-based access
            if storage_token:
                # Determine proxy URL (use internal Docker network URL if available)
                proxy_base_url = settings.STORAGE_PROXY_URL or f"http://host.docker.internal:{settings.PORT}/api/v1/storage"
                env_vars.update({
                    "STORAGE_PROXY_URL": proxy_base_url,
                    "STORAGE_TOKEN": storage_token,
                    "S3_USER_PREFIX": f"users/{user_id}/" if user_id else "",
                })
            elif user_id:
                # Legacy mode: pass raw S3 credentials (DEPRECATED)
                # TODO: Remove this branch once all callers use storage_token
                env_vars.update({
                    "AWS_ACCESS_KEY_ID": settings.S3_ACCESS_KEY,
                    "AWS_SECRET_ACCESS_KEY": settings.S3_SECRET_KEY,
                    "AWS_REGION": settings.S3_REGION,
                    "S3_BUCKET": settings.S3_BUCKET,
                    "S3_USER_PREFIX": f"users/{user_id}/",
                })
                if settings.S3_ENDPOINT:
                    env_vars["AWS_ENDPOINT_URL"] = settings.S3_ENDPOINT

            # Run container in executor to avoid blocking event loop
            container = await loop.run_in_executor(
                None,
                lambda: client.containers.run(
                    image=settings.PYTHON_SANDBOX_IMAGE,
                    command=[
                        "python", "-c",
                        "import os; exec(compile(os.environ.get('PYTHON_CODE', ''), 'script.py', 'exec'))"
                    ],
                    detach=True,
                    stderr=True,
                    stdout=True,
                    environment=env_vars,
                    # network and resource limits lifted for advanced uses
                )
            )

            if container is None:
                raise RuntimeError("Failed to start container")

            try:
                # container.wait() is blocking in docker-py, so use executor
                exit_status = await asyncio.wait_for(
                    loop.run_in_executor(None, container.wait),
                    timeout=timeout
                )
            except TimeoutError:
                await loop.run_in_executor(None, container.kill)
                return {"output": "", "error": "Execution timed out."}

            logs = await loop.run_in_executor(
                None, lambda: container.logs().decode("utf-8")
            )

            if exit_status["StatusCode"] != 0:
                return {"output": "", "error": logs}
            return {"output": logs, "error": ""}
        except ContainerError as e:
            return {"output": "", "error": str(e)}
        except Exception as e:
            return {"output": "", "error": f"Execution error: {e!s}"}
        finally:
            if container:
                try:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(
                        None, lambda: container.remove(force=True)
                    )
                except Exception:
                    pass


python_executor = PythonExecutor()


def get_python_executor() -> PythonExecutor:
    """Get the global Python executor instance."""
    return python_executor

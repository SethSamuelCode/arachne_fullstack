"""Python code execution service using Docker sandbox."""

import asyncio
import os
import shutil
import tempfile
import time
import uuid
from typing import Any

from docker.errors import ContainerError

from app.core.config import settings
from app.core.docker import get_docker_client


class PythonExecutor:
    """Service for executing Python code in Docker sandbox."""

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
    
    async def execute_code(self, code: str, timeout: int = 10) -> dict[str, Any]:
        """Execute Python code in a Docker container.

        Args:
            code (str): The Python code to execute.

        Returns:
            dict: Execution result with 'output' and 'error' keys."""
        
        client = self.docker_client
        if not self.is_available or client is None:
            return {"output": "", "error": "Docker is not available."}

        # Create temp dir for code
        temp_dir = tempfile.mkdtemp()
        script_path = os.path.join(temp_dir, "script.py")
        
        try:
            with open(script_path, "w") as f:
                f.write(code)
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return {"output": "", "error": f"Failed to prepare code: {str(e)}"}

        container: Any | None = None

        try:
            loop = asyncio.get_running_loop()
            
            env_vars = {
                "AWS_ACCESS_KEY_ID": settings.S3_ACCESS_KEY,
                "AWS_SECRET_ACCESS_KEY": settings.S3_SECRET_KEY,
                "AWS_REGION": settings.S3_REGION,
                "S3_BUCKET": settings.S3_BUCKET,
            }
            if settings.S3_ENDPOINT:
                env_vars["AWS_ENDPOINT_URL"] = settings.S3_ENDPOINT

            # Run container in executor to avoid blocking event loop
            container = await loop.run_in_executor(
                None,
                lambda: client.containers.run(
                    image=settings.PYTHON_SANDBOX_IMAGE,
                    command="python /app/script.py",
                    detach=True,
                    volumes={temp_dir: {"bind": "/app", "mode": "ro"}},
                    stderr=True,
                    stdout=True,
                    environment=env_vars,
                    # network and resource limits lifted for advanced uses 
                )
            )
            
            if container is None:
                raise Exception("Failed to start container")

            try:
                # container.wait() is blocking in docker-py, so use executor
                exit_status = await asyncio.wait_for(
                    loop.run_in_executor(None, container.wait),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                await loop.run_in_executor(None, container.kill)
                return {"output": "", "error": "Execution timed out."}

            logs = await loop.run_in_executor(None, lambda: container.logs().decode("utf-8"))
            
            if exit_status["StatusCode"] != 0:
                return {"output": "", "error": logs}
            return {"output": logs, "error": ""}
        except ContainerError as e:
            return {"output": "", "error": str(e)}
        except Exception as e:
            return {"output": "", "error": f"Execution error: {str(e)}"}
        finally:
            if container:
                try:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, lambda: container.remove(force=True))
                except Exception:
                    pass
            shutil.rmtree(temp_dir, ignore_errors=True)

python_executor = PythonExecutor()

def get_python_executor() -> PythonExecutor:
    """Get the global Python executor instance."""
    return python_executor
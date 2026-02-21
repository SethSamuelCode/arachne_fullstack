"""
Docker client initialization and management.

Handles Docker client setup for Python sandbox execution.
"""

import docker
from docker import DockerClient

# Global Docker client instance
_docker_client: DockerClient | None = None


def get_docker_client() -> DockerClient | None:
    """
    Get or initialize the Docker client.

    Returns:
        DockerClient instance if Docker is available, None otherwise.
    """
    global _docker_client

    if _docker_client is not None:
        return _docker_client

    try:
        _docker_client = docker.from_env()
        return _docker_client
    except Exception:
        return None


def is_docker_available() -> bool:
    """Check if Docker is available."""
    return get_docker_client() is not None

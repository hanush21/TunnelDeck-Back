from __future__ import annotations

import docker
from docker import DockerClient


def create_docker_client(socket_path: str) -> DockerClient:
    base_url = f"unix://{socket_path}"
    client = docker.DockerClient(base_url=base_url)
    return client

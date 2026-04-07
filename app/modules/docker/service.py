from __future__ import annotations

from datetime import datetime
from typing import Any

from docker.errors import DockerException, NotFound
from fastapi import HTTPException, status

from app.core.config import Settings
from app.infrastructure.docker.client import create_docker_client
from app.modules.docker.schemas import ContainerSummaryResponse, PublishedPort


class DockerService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _build_ports(self, ports: dict[str, Any] | None) -> list[PublishedPort]:
        published_ports: list[PublishedPort] = []
        for container_port, host_bindings in (ports or {}).items():
            if not host_bindings:
                published_ports.append(PublishedPort(container_port=container_port))
                continue

            for binding in host_bindings:
                published_ports.append(
                    PublishedPort(
                        container_port=container_port,
                        host_ip=binding.get("HostIp"),
                        host_port=binding.get("HostPort"),
                    )
                )
        return published_ports

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None

        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _to_summary(self, container: Any) -> ContainerSummaryResponse:
        attrs = container.attrs or {}
        config = attrs.get("Config") or {}
        state = attrs.get("State") or {}
        network_settings = attrs.get("NetworkSettings") or {}

        return ContainerSummaryResponse(
            id=container.id,
            name=container.name,
            image=config.get("Image", ""),
            state=state.get("Status", "unknown"),
            status=container.status,
            published_ports=self._build_ports(network_settings.get("Ports")),
            labels=config.get("Labels") or {},
            networks=list((network_settings.get("Networks") or {}).keys()),
            created_at=self._parse_datetime(attrs.get("Created")),
            started_at=self._parse_datetime(state.get("StartedAt")),
        )

    def _client(self):
        try:
            client = create_docker_client(self.settings.DOCKER_SOCKET_PATH)
            client.ping()
            return client
        except DockerException as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Docker daemon unavailable",
            ) from exc

    def list_containers(self) -> list[ContainerSummaryResponse]:
        client = self._client()
        try:
            containers = client.containers.list(all=True)
            return [self._to_summary(container) for container in containers]
        finally:
            client.close()

    def get_container(self, container_id: str) -> ContainerSummaryResponse:
        client = self._client()
        try:
            container = client.containers.get(container_id)
            return self._to_summary(container)
        except NotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Container not found",
            ) from exc
        finally:
            client.close()

    def ensure_container_exists(self, container_name: str) -> None:
        client = self._client()
        try:
            client.containers.get(container_name)
        except NotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Container '{container_name}' does not exist",
            ) from exc
        finally:
            client.close()

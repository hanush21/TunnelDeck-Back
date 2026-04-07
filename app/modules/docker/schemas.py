from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PublishedPort(BaseModel):
    container_port: str
    host_ip: str | None = None
    host_port: str | None = None


class ContainerSummaryResponse(BaseModel):
    id: str
    name: str
    image: str
    state: str
    status: str
    published_ports: list[PublishedPort]
    labels: dict[str, str]
    networks: list[str]
    created_at: datetime | None = None
    started_at: datetime | None = None


class ContainerListResponse(BaseModel):
    items: list[ContainerSummaryResponse]

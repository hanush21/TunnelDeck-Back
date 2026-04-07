from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class CloudflaredHealthResponse(BaseModel):
    service_name: str
    status: str
    is_active: bool
    config_exists: bool
    platform_system: str | None = None
    os_name: str | None = None
    service_manager: str | None = None


class LivenessResponse(BaseModel):
    status: str
    timestamp: str


class ReadinessResponse(BaseModel):
    ready: bool
    status: str
    timestamp: str
    components: dict[str, Any]

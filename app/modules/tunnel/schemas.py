from __future__ import annotations

from pydantic import BaseModel


class CloudflaredHealthResponse(BaseModel):
    service_name: str
    status: str
    is_active: bool
    config_exists: bool
    platform_system: str | None = None
    os_name: str | None = None
    service_manager: str | None = None

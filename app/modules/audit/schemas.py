from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: int
    actor_email: str
    action: str
    resource_type: str
    resource_id: str | None
    success: bool
    details: dict | None
    error_message: str | None
    created_at: datetime


class AuditListResponse(BaseModel):
    entries: list[AuditLogResponse]

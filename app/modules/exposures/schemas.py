from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.infrastructure.tunnel.validator import validate_hostname


class ExposureBase(BaseModel):
    container_name: str = Field(min_length=1, max_length=255)
    hostname: str = Field(min_length=1, max_length=253)
    service_type: Literal["http", "https"]
    target_host: str = Field(min_length=1, max_length=255)
    target_port: int = Field(ge=1, le=65535)
    enabled: bool = True

    @field_validator("hostname")
    @classmethod
    def validate_hostname_field(cls, hostname: str) -> str:
        normalized = hostname.strip().lower()
        validate_hostname(normalized)
        return normalized

    @field_validator("target_host")
    @classmethod
    def validate_target_host(cls, target_host: str) -> str:
        normalized = target_host.strip().lower()
        if "://" in normalized or "/" in normalized:
            raise ValueError("target_host must not include scheme or path")
        return normalized


class ExposureCreateRequest(ExposureBase):
    pass


class ExposureUpdateRequest(ExposureBase):
    pass


class ExposureResponse(BaseModel):
    id: int
    container_name: str
    hostname: str
    service_type: Literal["http", "https"]
    target_host: str
    target_port: int
    enabled: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


class ExposureListResponse(BaseModel):
    items: list[ExposureResponse]

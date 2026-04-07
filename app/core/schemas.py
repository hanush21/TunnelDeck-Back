from __future__ import annotations

from pydantic import BaseModel, Field


class PaginationMeta(BaseModel):
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)

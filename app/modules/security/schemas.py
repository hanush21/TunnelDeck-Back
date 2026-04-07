from __future__ import annotations

from pydantic import BaseModel, Field


class TotpVerifyRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class TotpVerifyResponse(BaseModel):
    valid: bool

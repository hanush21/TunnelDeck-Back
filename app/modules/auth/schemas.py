from __future__ import annotations

from pydantic import BaseModel


class AuthenticatedUser(BaseModel):
    uid: str
    email: str
    name: str | None = None


class AuthMeResponse(BaseModel):
    uid: str
    email: str
    name: str | None = None

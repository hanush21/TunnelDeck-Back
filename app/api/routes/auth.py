from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_admin_user
from app.modules.auth.schemas import AuthMeResponse, AuthenticatedUser

router = APIRouter()


@router.get("/me", response_model=AuthMeResponse)
def me(
    user: Annotated[AuthenticatedUser, Depends(get_current_admin_user)],
) -> AuthMeResponse:
    return AuthMeResponse(uid=user.uid, email=user.email, name=user.name)

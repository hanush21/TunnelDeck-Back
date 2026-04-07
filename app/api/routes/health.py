from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_admin_user, get_settings_dependency
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.tunnel.schemas import CloudflaredHealthResponse
from app.modules.tunnel.service import TunnelService

router = APIRouter()


def get_tunnel_service(
    settings=Depends(get_settings_dependency),
) -> TunnelService:
    return TunnelService(settings)


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health/cloudflared", response_model=CloudflaredHealthResponse)
def health_cloudflared(
    _: Annotated[AuthenticatedUser, Depends(get_current_admin_user)],
    tunnel_service: Annotated[TunnelService, Depends(get_tunnel_service)],
) -> CloudflaredHealthResponse:
    return CloudflaredHealthResponse(**tunnel_service.get_health())

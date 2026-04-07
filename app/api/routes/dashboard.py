from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes.containers import get_docker_service
from app.api.routes.health import get_tunnel_service
from app.core.dependencies import get_current_admin_user, get_db
from app.infrastructure.persistence.models import Exposure
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.docker.service import DockerService
from app.modules.tunnel.service import TunnelService

router = APIRouter()


@router.get("/summary")
def summary(
    _: Annotated[AuthenticatedUser, Depends(get_current_admin_user)],
    db: Annotated[Session, Depends(get_db)],
    docker_service: Annotated[DockerService, Depends(get_docker_service)],
    tunnel_service: Annotated[TunnelService, Depends(get_tunnel_service)],
) -> dict:
    total_exposures = db.scalar(select(func.count()).select_from(Exposure)) or 0
    enabled_exposures = (
        db.scalar(select(func.count()).select_from(Exposure).where(Exposure.enabled.is_(True))) or 0
    )

    containers = docker_service.list_containers()
    cloudflared = tunnel_service.get_health()

    return {
        "exposures": {
            "total": total_exposures,
            "enabled": enabled_exposures,
        },
        "containers": {
            "total": len(containers),
            "running": len([c for c in containers if c.state == "running"]),
        },
        "cloudflared": cloudflared,
    }

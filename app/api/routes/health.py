from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes.audit import get_audit_service
from app.api.routes.containers import get_docker_service
from app.core.dependencies import (
    get_current_admin_user,
    get_current_admin_with_totp,
    get_db,
    get_settings_dependency,
)
from app.infrastructure.persistence.database import get_engine
from app.modules.audit.service import AuditService
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.docker.service import DockerService
from app.modules.tunnel.schemas import (
    CloudflaredHealthResponse,
    LivenessResponse,
    ReadinessResponse,
)
from app.modules.tunnel.service import TunnelService

router = APIRouter()


def get_tunnel_service(
    settings=Depends(get_settings_dependency),
) -> TunnelService:
    return TunnelService(settings)


def _safe_audit_log(
    db: Session,
    audit_service: AuditService,
    *,
    actor_email: str,
    action: str,
    success: bool,
    details: dict | None = None,
    error_message: str | None = None,
) -> None:
    try:
        audit_service.log_operation(
            db,
            actor_email=actor_email,
            action=action,
            resource_type="tunnel",
            resource_id="cloudflared",
            success=success,
            details=details,
            error_message=error_message,
        )
        db.commit()
    except Exception:
        db.rollback()


@router.get("/health/live", response_model=LivenessResponse)
def health_live() -> LivenessResponse:
    return LivenessResponse(status="alive", timestamp=datetime.now(timezone.utc).isoformat())


@router.get("/health/ready", response_model=ReadinessResponse)
def health_ready(
    tunnel_service: Annotated[TunnelService, Depends(get_tunnel_service)],
    docker_service: Annotated[DockerService, Depends(get_docker_service)],
) -> ReadinessResponse:
    components: dict = {}
    ready = True

    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        components["database"] = {"ready": True, "status": "ok"}
    except Exception as exc:
        ready = False
        components["database"] = {"ready": False, "status": "error", "detail": str(exc)}

    try:
        docker_service.list_containers()
        components["docker"] = {"ready": True, "status": "ok"}
    except Exception as exc:
        components["docker"] = {"ready": False, "status": "degraded", "detail": str(exc)}

    cloudflared = tunnel_service.get_health()
    components["cloudflared"] = {
        "ready": cloudflared.get("is_active", False),
        "status": cloudflared.get("status"),
        "service_manager": cloudflared.get("service_manager"),
        "platform_system": cloudflared.get("platform_system"),
    }

    status_value = "ready" if ready else "not_ready"
    return ReadinessResponse(
        ready=ready,
        status=status_value,
        timestamp=datetime.now(timezone.utc).isoformat(),
        components=components,
    )


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/health/cloudflared", response_model=CloudflaredHealthResponse)
def health_cloudflared(
    _: Annotated[AuthenticatedUser, Depends(get_current_admin_user)],
    tunnel_service: Annotated[TunnelService, Depends(get_tunnel_service)],
) -> CloudflaredHealthResponse:
    return CloudflaredHealthResponse(**tunnel_service.get_health())


@router.post("/health/cloudflared/restart", response_model=CloudflaredHealthResponse)
def restart_cloudflared(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_admin_with_totp)],
    db: Annotated[Session, Depends(get_db)],
    tunnel_service: Annotated[TunnelService, Depends(get_tunnel_service)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> CloudflaredHealthResponse:
    try:
        health = tunnel_service.restart_cloudflared()
        audit_service.log_operation(
            db,
            actor_email=user.email,
            action="cloudflared.restart",
            resource_type="tunnel",
            resource_id="cloudflared",
            success=True,
            details={
                "request_id": getattr(request.state, "request_id", None),
                "status": health.get("status"),
                "service_manager": health.get("service_manager"),
            },
        )
        db.commit()
        return CloudflaredHealthResponse(**health)
    except HTTPException as exc:
        db.rollback()
        _safe_audit_log(
            db,
            audit_service,
            actor_email=user.email,
            action="cloudflared.restart",
            success=False,
            details={"request_id": getattr(request.state, "request_id", None)},
            error_message=str(exc.detail),
        )
        raise

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.api.routes.audit import get_audit_service
from app.api.routes.containers import get_docker_service
from app.api.routes.health import get_tunnel_service
from app.core.schemas import PaginationMeta
from app.core.dependencies import get_current_admin_user, get_current_admin_with_totp, get_db
from app.modules.audit.service import AuditService
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.docker.service import DockerService
from app.modules.exposures.schemas import (
    ExposureCreateRequest,
    ExposureListResponse,
    ExposureResponse,
    ExposureUpdateRequest,
)
from app.modules.exposures.service import ExposureService
from app.modules.tunnel.service import TunnelService

router = APIRouter()


def get_exposure_service(
    tunnel_service: Annotated[TunnelService, Depends(get_tunnel_service)],
    docker_service: Annotated[DockerService, Depends(get_docker_service)],
) -> ExposureService:
    return ExposureService(tunnel_service=tunnel_service, docker_service=docker_service)


def _safe_audit_log(
    db: Session,
    audit_service: AuditService,
    *,
    actor_email: str,
    action: str,
    resource_id: str | None,
    success: bool,
    details: dict | None = None,
    error_message: str | None = None,
) -> None:
    try:
        audit_service.log_operation(
            db,
            actor_email=actor_email,
            action=action,
            resource_type="exposure",
            resource_id=resource_id,
            success=success,
            details=details,
            error_message=error_message,
        )
        db.commit()
    except Exception:
        db.rollback()


@router.get("", response_model=ExposureListResponse)
def list_exposures(
    _: Annotated[AuthenticatedUser, Depends(get_current_admin_user)],
    db: Annotated[Session, Depends(get_db)],
    exposure_service: Annotated[ExposureService, Depends(get_exposure_service)],
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> ExposureListResponse:
    total = exposure_service.count_exposures(db)
    exposures = exposure_service.list_exposures(db, limit=limit, offset=offset)
    items = [ExposureResponse.model_validate(exposure, from_attributes=True) for exposure in exposures]
    return ExposureListResponse(
        meta=PaginationMeta(total=total, limit=limit, offset=offset),
        items=items,
    )


@router.post("", response_model=ExposureResponse, status_code=status.HTTP_201_CREATED)
def create_exposure(
    payload: ExposureCreateRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_admin_with_totp)],
    db: Annotated[Session, Depends(get_db)],
    exposure_service: Annotated[ExposureService, Depends(get_exposure_service)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> ExposureResponse:
    try:
        exposure = exposure_service.create_exposure(db, payload=payload, actor_email=user.email)
        audit_service.log_operation(
            db,
            actor_email=user.email,
            action="exposure.create",
            resource_type="exposure",
            resource_id=str(exposure.id),
            success=True,
            details={
                "hostname": exposure.hostname,
                "request_id": getattr(request.state, "request_id", None),
            },
        )
        db.commit()
        db.refresh(exposure)
        return ExposureResponse.model_validate(exposure, from_attributes=True)
    except HTTPException as exc:
        db.rollback()
        _safe_audit_log(
            db,
            audit_service,
            actor_email=user.email,
            action="exposure.create",
            resource_id=None,
            success=False,
            details={
                "hostname": payload.hostname,
                "request_id": getattr(request.state, "request_id", None),
            },
            error_message=str(exc.detail),
        )
        raise
    except Exception as exc:
        db.rollback()
        _safe_audit_log(
            db,
            audit_service,
            actor_email=user.email,
            action="exposure.create",
            resource_id=None,
            success=False,
            details={
                "hostname": payload.hostname,
                "request_id": getattr(request.state, "request_id", None),
            },
            error_message=str(exc),
        )
        raise HTTPException(status_code=500, detail="Failed to create exposure") from exc


@router.put("/{exposure_id}", response_model=ExposureResponse)
def update_exposure(
    exposure_id: int,
    payload: ExposureUpdateRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_admin_with_totp)],
    db: Annotated[Session, Depends(get_db)],
    exposure_service: Annotated[ExposureService, Depends(get_exposure_service)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> ExposureResponse:
    try:
        exposure = exposure_service.update_exposure(
            db,
            exposure_id=exposure_id,
            payload=payload,
            actor_email=user.email,
        )
        audit_service.log_operation(
            db,
            actor_email=user.email,
            action="exposure.update",
            resource_type="exposure",
            resource_id=str(exposure.id),
            success=True,
            details={
                "hostname": exposure.hostname,
                "request_id": getattr(request.state, "request_id", None),
            },
        )
        db.commit()
        db.refresh(exposure)
        return ExposureResponse.model_validate(exposure, from_attributes=True)
    except HTTPException as exc:
        db.rollback()
        _safe_audit_log(
            db,
            audit_service,
            actor_email=user.email,
            action="exposure.update",
            resource_id=str(exposure_id),
            success=False,
            details={
                "hostname": payload.hostname,
                "request_id": getattr(request.state, "request_id", None),
            },
            error_message=str(exc.detail),
        )
        raise
    except Exception as exc:
        db.rollback()
        _safe_audit_log(
            db,
            audit_service,
            actor_email=user.email,
            action="exposure.update",
            resource_id=str(exposure_id),
            success=False,
            details={
                "hostname": payload.hostname,
                "request_id": getattr(request.state, "request_id", None),
            },
            error_message=str(exc),
        )
        raise HTTPException(status_code=500, detail="Failed to update exposure") from exc


@router.delete(
    "/{exposure_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_exposure(
    exposure_id: int,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_current_admin_with_totp)],
    db: Annotated[Session, Depends(get_db)],
    exposure_service: Annotated[ExposureService, Depends(get_exposure_service)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> Response:
    try:
        exposure_service.delete_exposure(db, exposure_id=exposure_id, actor_email=user.email)
        audit_service.log_operation(
            db,
            actor_email=user.email,
            action="exposure.delete",
            resource_type="exposure",
            resource_id=str(exposure_id),
            success=True,
            details={
                "exposure_id": exposure_id,
                "request_id": getattr(request.state, "request_id", None),
            },
        )
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException as exc:
        db.rollback()
        _safe_audit_log(
            db,
            audit_service,
            actor_email=user.email,
            action="exposure.delete",
            resource_id=str(exposure_id),
            success=False,
            details={
                "exposure_id": exposure_id,
                "request_id": getattr(request.state, "request_id", None),
            },
            error_message=str(exc.detail),
        )
        raise
    except Exception as exc:
        db.rollback()
        _safe_audit_log(
            db,
            audit_service,
            actor_email=user.email,
            action="exposure.delete",
            resource_id=str(exposure_id),
            success=False,
            details={
                "exposure_id": exposure_id,
                "request_id": getattr(request.state, "request_id", None),
            },
            error_message=str(exc),
        )
        raise HTTPException(status_code=500, detail="Failed to delete exposure") from exc

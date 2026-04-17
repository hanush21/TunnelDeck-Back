from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.persistence.models import Exposure, ServiceType
from app.modules.docker.service import DockerService
from app.modules.exposures.schemas import ExposureCreateRequest, ExposureUpdateRequest
from app.modules.tunnel.service import TunnelService


class ExposureService:
    def __init__(self, tunnel_service: TunnelService, docker_service: DockerService) -> None:
        self.tunnel_service = tunnel_service
        self.docker_service = docker_service

    def count_exposures(self, db: Session) -> int:
        stmt = select(func.count()).select_from(Exposure)
        return int(db.scalar(stmt) or 0)

    def list_exposures(self, db: Session, *, limit: int = 100, offset: int = 0) -> list[Exposure]:
        stmt = (
            select(Exposure)
            .order_by(Exposure.created_at.desc(), Exposure.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(db.scalars(stmt).all())

    def _get_by_id(self, db: Session, exposure_id: int) -> Exposure:
        stmt = select(Exposure).where(Exposure.id == exposure_id)
        exposure = db.scalar(stmt)
        if exposure is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exposure not found")
        return exposure

    def _ensure_unique_hostname(self, db: Session, hostname: str, current_id: int | None = None) -> None:
        stmt = select(Exposure).where(Exposure.hostname == hostname)
        existing = db.scalar(stmt)
        if existing is not None and existing.id != current_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Hostname already exists",
            )

    def _sync_tunnel(self, db: Session, *, actor_email: str, reason: str) -> None:
        self.tunnel_service.import_external_config_entries(db, actor_email=actor_email)

        enabled_stmt = (
            select(Exposure)
            .where(Exposure.enabled.is_(True))
            .order_by(Exposure.hostname.asc())
        )
        enabled_exposures = list(db.scalars(enabled_stmt).all())
        self.tunnel_service.apply_exposure_config(
            db,
            exposures=enabled_exposures,
            actor_email=actor_email,
            reason=reason,
        )

    def create_exposure(
        self,
        db: Session,
        *,
        payload: ExposureCreateRequest,
        actor_email: str,
    ) -> Exposure:
        self._ensure_unique_hostname(db, payload.hostname)
        self.docker_service.ensure_container_exists(payload.container_name)

        exposure = Exposure(
            container_name=payload.container_name,
            hostname=payload.hostname,
            service_type=ServiceType(payload.service_type),
            target_host=payload.target_host,
            target_port=payload.target_port,
            enabled=payload.enabled,
            created_by=actor_email,
        )
        db.add(exposure)
        db.flush()

        self._sync_tunnel(db, actor_email=actor_email, reason="create_exposure")
        db.refresh(exposure)
        return exposure

    def update_exposure(
        self,
        db: Session,
        *,
        exposure_id: int,
        payload: ExposureUpdateRequest,
        actor_email: str,
    ) -> Exposure:
        exposure = self._get_by_id(db, exposure_id)
        self._ensure_unique_hostname(db, payload.hostname, current_id=exposure.id)
        self.docker_service.ensure_container_exists(payload.container_name)

        exposure.container_name = payload.container_name
        exposure.hostname = payload.hostname
        exposure.service_type = ServiceType(payload.service_type)
        exposure.target_host = payload.target_host
        exposure.target_port = payload.target_port
        exposure.enabled = payload.enabled

        db.add(exposure)
        db.flush()

        self._sync_tunnel(db, actor_email=actor_email, reason="update_exposure")
        db.refresh(exposure)
        return exposure

    def delete_exposure(self, db: Session, *, exposure_id: int, actor_email: str) -> None:
        exposure = self._get_by_id(db, exposure_id)
        db.delete(exposure)
        db.flush()

        self._sync_tunnel(db, actor_email=actor_email, reason="delete_exposure")

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import HTTPException, status
from filelock import FileLock, Timeout
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.infrastructure.persistence.models import ConfigBackup, Exposure
from app.infrastructure.tunnel.backup import BackupManager
from app.infrastructure.tunnel.systemd import CloudflaredSystemdController
from app.infrastructure.tunnel.validator import (
    TunnelValidationError,
    build_service_url,
    validate_ingress,
)
from app.infrastructure.tunnel.yaml_manager import YamlManager

logger = logging.getLogger("app.tunnel")


class TunnelService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.yaml_manager = YamlManager()
        self.backup_manager = BackupManager(
            settings.CLOUDFLARED_BACKUP_DIR,
            max_files=settings.CLOUDFLARED_BACKUP_MAX_FILES,
        )
        self.systemd = CloudflaredSystemdController(
            settings.CLOUDFLARED_SERVICE_NAME,
            control_mode=getattr(settings, "CLOUDFLARED_CONTROL_MODE", "auto"),
            docker_socket_path=getattr(settings, "DOCKER_SOCKET_PATH", "/var/run/docker.sock"),
            docker_container_name=getattr(settings, "CLOUDFLARED_DOCKER_CONTAINER_NAME", ""),
        )
        self.lock_path = Path(settings.TUNNEL_CONFIG_LOCK_PATH)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

    def get_health(self) -> dict:
        config_exists = Path(self.settings.CLOUDFLARED_CONFIG_PATH).exists()
        try:
            status = self.systemd.get_status()
        except Exception:
            status = "status_check_error"
        runtime = self.systemd.runtime_info()
        return {
            "service_name": self.settings.CLOUDFLARED_SERVICE_NAME,
            "status": status,
            "is_active": status == "active",
            "config_exists": config_exists,
            "platform_system": runtime.get("platform_system"),
            "os_name": runtime.get("os_name"),
            "service_manager": runtime.get("service_manager"),
        }

    def list_backups(self, db: Session, *, limit: int = 50) -> list[ConfigBackup]:
        stmt = (
            select(ConfigBackup)
            .order_by(desc(ConfigBackup.created_at), desc(ConfigBackup.id))
            .limit(limit)
        )
        return list(db.scalars(stmt).all())

    def restart_cloudflared(self) -> dict:
        try:
            with FileLock(
                str(self.lock_path),
                timeout=self.settings.TUNNEL_CONFIG_LOCK_TIMEOUT_SECONDS,
            ):
                self.systemd.restart()
                if not self.systemd.is_active():
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail={
                            "code": "cloudflared_unhealthy_after_restart",
                            "message": "cloudflared is not active after restart",
                        },
                    )
                return self.get_health()
        except Timeout as exc:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail={
                    "code": "tunnel_config_locked",
                    "message": "Tunnel config is currently locked by another operation",
                },
            ) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "cloudflared_restart_failed",
                    "message": "Failed to restart cloudflared service",
                    "details": {"reason": str(exc)},
                },
            ) from exc

    def restore_backup(
        self,
        db: Session,
        *,
        backup_id: int,
        actor_email: str,
        reason: str | None = None,
    ) -> ConfigBackup:
        backup_record = db.get(ConfigBackup, backup_id)
        if backup_record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "backup_not_found",
                    "message": f"Backup '{backup_id}' was not found",
                },
            )

        source_backup_path = Path(backup_record.file_path)
        if not source_backup_path.exists():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "backup_file_missing",
                    "message": "Backup file referenced by database does not exist",
                    "details": {"file_path": str(source_backup_path)},
                },
            )

        try:
            with FileLock(
                str(self.lock_path),
                timeout=self.settings.TUNNEL_CONFIG_LOCK_TIMEOUT_SECONDS,
            ):
                safety_backup_path = self.backup_manager.create_backup(self.settings.CLOUDFLARED_CONFIG_PATH)
                try:
                    self.backup_manager.restore_backup(
                        source_backup_path, self.settings.CLOUDFLARED_CONFIG_PATH
                    )
                    self.systemd.restart()
                    if not self.systemd.is_active():
                        raise RuntimeError("cloudflared service is not active after restore")
                except Exception as exc:
                    self.backup_manager.restore_backup(
                        safety_backup_path, self.settings.CLOUDFLARED_CONFIG_PATH
                    )
                    try:
                        self.systemd.restart()
                    except Exception:
                        pass
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail={
                            "code": "tunnel_restore_failed",
                            "message": "Failed to restore cloudflared backup; rollback executed",
                            "details": {"reason": str(exc)},
                        },
                    ) from exc

                rollback_record = ConfigBackup(
                    file_path=str(safety_backup_path),
                    reason=reason or f"manual_restore_from_backup_{backup_id}",
                    triggered_by=actor_email,
                )
                db.add(rollback_record)
                db.flush()
                return rollback_record
        except Timeout as exc:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail={
                    "code": "tunnel_config_locked",
                    "message": "Tunnel config is currently locked by another operation",
                },
            ) from exc
        except HTTPException:
            raise
        except FileNotFoundError as exc:
            logger.exception(
                {
                    "event": "cloudflared_config_missing",
                    "config_path": self.settings.CLOUDFLARED_CONFIG_PATH,
                    "error": str(exc),
                }
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": "cloudflared_config_missing",
                    "message": "Cloudflared config file not found",
                    "details": {"config_path": self.settings.CLOUDFLARED_CONFIG_PATH},
                },
            ) from exc

    def _build_ingress_from_exposures(self, exposures: list[Exposure]) -> list[dict]:
        ingress: list[dict] = []
        for exposure in exposures:
            service_url = build_service_url(
                exposure.service_type.value,
                exposure.target_host,
                exposure.target_port,
            )
            ingress.append(
                {
                    "hostname": exposure.hostname,
                    "service": service_url,
                }
            )

        ingress.append({"service": "http_status:404"})
        validate_ingress(ingress)
        return ingress

    def apply_exposure_config(
        self,
        db: Session,
        *,
        exposures: list[Exposure],
        actor_email: str,
        reason: str,
    ) -> None:
        try:
            with FileLock(
                str(self.lock_path),
                timeout=self.settings.TUNNEL_CONFIG_LOCK_TIMEOUT_SECONDS,
            ):
                current_config = self.yaml_manager.load(self.settings.CLOUDFLARED_CONFIG_PATH)
                ingress = self._build_ingress_from_exposures(exposures)

                updated_config = dict(current_config)
                updated_config["ingress"] = ingress

                backup_path = self.backup_manager.create_backup(self.settings.CLOUDFLARED_CONFIG_PATH)

                try:
                    self.yaml_manager.write(self.settings.CLOUDFLARED_CONFIG_PATH, updated_config)
                    self.systemd.restart()

                    if not self.systemd.is_active():
                        raise RuntimeError("cloudflared service is not active after restart")

                except Exception as exc:
                    self.backup_manager.restore_backup(
                        backup_path, self.settings.CLOUDFLARED_CONFIG_PATH
                    )
                    try:
                        self.systemd.restart()
                    except Exception:
                        pass
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail={
                            "code": "tunnel_apply_failed",
                            "message": "Failed to apply cloudflared config; rollback executed",
                            "details": {"reason": str(exc)},
                        },
                    ) from exc

                backup_record = ConfigBackup(
                    file_path=str(backup_path),
                    reason=reason,
                    triggered_by=actor_email,
                )
                db.add(backup_record)
                db.flush()
        except Timeout as exc:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail={
                    "code": "tunnel_config_locked",
                    "message": "Tunnel config is currently locked by another operation",
                },
            ) from exc
        except TunnelValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "invalid_tunnel_config",
                    "message": str(exc),
                },
            ) from exc
        except FileNotFoundError as exc:
            logger.exception(
                {
                    "event": "cloudflared_config_missing",
                    "config_path": self.settings.CLOUDFLARED_CONFIG_PATH,
                    "error": str(exc),
                }
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": "cloudflared_config_missing",
                    "message": "Cloudflared config file not found",
                    "details": {"config_path": self.settings.CLOUDFLARED_CONFIG_PATH},
                },
            ) from exc

from __future__ import annotations

from pathlib import Path

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


class TunnelService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.yaml_manager = YamlManager()
        self.backup_manager = BackupManager(settings.CLOUDFLARED_BACKUP_DIR)
        self.systemd = CloudflaredSystemdController(settings.CLOUDFLARED_SERVICE_NAME)

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
            current_config = self.yaml_manager.load(self.settings.CLOUDFLARED_CONFIG_PATH)
            ingress = self._build_ingress_from_exposures(exposures)
        except TunnelValidationError as exc:
            raise RuntimeError(str(exc)) from exc

        updated_config = dict(current_config)
        updated_config["ingress"] = ingress

        backup_path = self.backup_manager.create_backup(self.settings.CLOUDFLARED_CONFIG_PATH)

        try:
            self.yaml_manager.write(self.settings.CLOUDFLARED_CONFIG_PATH, updated_config)
            self.systemd.restart()

            if not self.systemd.is_active():
                raise RuntimeError("cloudflared service is not active after restart")

        except Exception as exc:
            self.backup_manager.restore_backup(backup_path, self.settings.CLOUDFLARED_CONFIG_PATH)
            try:
                self.systemd.restart()
            except Exception:
                pass
            raise RuntimeError("Failed to apply cloudflared config; rollback executed") from exc

        backup_record = ConfigBackup(
            file_path=str(backup_path),
            reason=reason,
            triggered_by=actor_email,
        )
        db.add(backup_record)
        db.flush()

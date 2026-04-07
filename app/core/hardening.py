from __future__ import annotations

import logging
import os
from pathlib import Path

from app.core.config import Settings

logger = logging.getLogger("app.hardening")


def run_startup_hardening_checks(settings: Settings) -> None:
    if settings.APP_ENV != "production":
        return

    logger.info({"event": "hardening_check", "message": "Running production hardening checks"})

    if os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() == 0:
        logger.warning(
            {
                "event": "hardening_warning",
                "code": "running_as_root",
                "message": "Application is running as root. Use a least-privileged user.",
            }
        )

    docker_socket = Path(settings.DOCKER_SOCKET_PATH)
    if docker_socket.exists():
        logger.warning(
            {
                "event": "hardening_warning",
                "code": "docker_socket_privileged",
                "message": "Docker socket access is highly privileged. Restrict network/API exposure.",
                "docker_socket": str(docker_socket),
            }
        )
    elif settings.CLOUDFLARED_CONTROL_MODE == "docker":
        logger.warning(
            {
                "event": "hardening_warning",
                "code": "docker_socket_missing",
                "message": "CLOUDFLARED_CONTROL_MODE=docker but Docker socket is missing.",
                "docker_socket": str(docker_socket),
            }
        )

    cloudflared_config = Path(settings.CLOUDFLARED_CONFIG_PATH)
    if not cloudflared_config.exists():
        logger.warning(
            {
                "event": "hardening_warning",
                "code": "cloudflared_config_missing",
                "message": "Cloudflared config path is missing at startup.",
                "config_path": str(cloudflared_config),
            }
        )

    if settings.DATABASE_URL.startswith("sqlite"):
        logger.warning(
            {
                "event": "hardening_warning",
                "code": "sqlite_production",
                "message": "SQLite is enabled in production. Ensure backups and filesystem protections.",
            }
        )

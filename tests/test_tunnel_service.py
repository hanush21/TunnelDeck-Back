from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from filelock import FileLock
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.persistence.models import Base, ConfigBackup, Exposure, ServiceType
from app.modules.tunnel.service import TunnelService


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def _settings(tmp_path: Path) -> SimpleNamespace:
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """tunnel: test\ncredentials-file: /tmp/creds.json\ningress:\n  - service: http_status:404\n""",
        encoding="utf-8",
    )

    return SimpleNamespace(
        CLOUDFLARED_CONFIG_PATH=str(config_path),
        CLOUDFLARED_SERVICE_NAME="cloudflared",
        CLOUDFLARED_BACKUP_DIR=str(tmp_path / "backups"),
        CLOUDFLARED_BACKUP_MAX_FILES=20,
        TUNNEL_CONFIG_LOCK_PATH=str(tmp_path / "config.lock"),
        TUNNEL_CONFIG_LOCK_TIMEOUT_SECONDS=1,
    )


def _exposure() -> Exposure:
    return Exposure(
        container_name="alpha",
        hostname="app.example.com",
        service_type=ServiceType.HTTP,
        target_host="localhost",
        target_port=3000,
        enabled=True,
        created_by="admin@example.com",
    )


def test_apply_exposure_config_returns_423_when_lock_is_held(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    tunnel = TunnelService(settings)
    db = _session()

    lock = FileLock(settings.TUNNEL_CONFIG_LOCK_PATH)
    with lock:
        with pytest.raises(HTTPException) as exc:
            tunnel.apply_exposure_config(
                db,
                exposures=[_exposure()],
                actor_email="admin@example.com",
                reason="test",
            )

    assert exc.value.status_code == 423
    assert exc.value.detail["code"] == "tunnel_config_locked"


def test_apply_exposure_config_rolls_back_on_restart_failure(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    tunnel = TunnelService(settings)
    db = _session()

    restore_called = {"value": False}

    backup_file = tmp_path / "backup.bak"
    backup_file.write_text("backup", encoding="utf-8")

    tunnel.yaml_manager.load = lambda _: {"tunnel": "test", "credentials-file": "/tmp/creds.json"}
    tunnel.yaml_manager.write = lambda *_: None
    tunnel.backup_manager.create_backup = lambda _: backup_file

    def _restore(*_):
        restore_called["value"] = True

    tunnel.backup_manager.restore_backup = _restore
    tunnel.systemd.restart = lambda: (_ for _ in ()).throw(RuntimeError("restart failed"))

    with pytest.raises(HTTPException) as exc:
        tunnel.apply_exposure_config(
            db,
            exposures=[_exposure()],
            actor_email="admin@example.com",
            reason="test",
        )

    assert exc.value.status_code == 500
    assert exc.value.detail["code"] == "tunnel_apply_failed"
    assert restore_called["value"] is True


def test_restore_backup_rolls_back_when_restart_fails(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    tunnel = TunnelService(settings)
    db = _session()

    source_backup = tmp_path / "source-backup.bak"
    source_backup.write_text("backup", encoding="utf-8")
    backup_record = ConfigBackup(
        file_path=str(source_backup),
        reason="test",
        triggered_by="admin@example.com",
    )
    db.add(backup_record)
    db.commit()
    db.refresh(backup_record)

    restore_called = {"count": 0}
    safety_backup = tmp_path / "safety-backup.bak"
    safety_backup.write_text("backup", encoding="utf-8")

    tunnel.backup_manager.create_backup = lambda _: safety_backup

    def _restore(*_):
        restore_called["count"] += 1

    tunnel.backup_manager.restore_backup = _restore
    tunnel.systemd.restart = lambda: (_ for _ in ()).throw(RuntimeError("restart failed"))

    with pytest.raises(HTTPException) as exc:
        tunnel.restore_backup(
            db,
            backup_id=backup_record.id,
            actor_email="admin@example.com",
        )

    assert exc.value.status_code == 500
    assert exc.value.detail["code"] == "tunnel_restore_failed"
    # One restore for target backup + one restore for rollback.
    assert restore_called["count"] == 2

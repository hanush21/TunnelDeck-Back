from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
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


def _settings(tmp_path: Path, config_content: str | None = None) -> SimpleNamespace:
    config_path = tmp_path / "config.yml"
    if config_content is not None:
        config_path.write_text(config_content, encoding="utf-8")
    else:
        config_path.write_text(
            "tunnel: test\ncredentials-file: /tmp/creds.json\ningress:\n  - service: http_status:404\n",
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


def _noop_tunnel(tunnel: TunnelService, tmp_path: Path) -> None:
    """Stub write/backup/restart so apply_exposure_config doesn't touch filesystem or systemd."""
    backup_file = tmp_path / "backup.bak"
    backup_file.write_text("backup", encoding="utf-8")
    tunnel.backup_manager.create_backup = lambda _: backup_file
    tunnel.backup_manager.restore_backup = lambda *_: None
    tunnel.yaml_manager.write = lambda *_: None
    tunnel.systemd.restart = lambda: None
    tunnel.systemd.is_active = lambda: True


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


# ---------------------------------------------------------------------------
# import_external_config_entries
# ---------------------------------------------------------------------------

def test_import_returns_empty_when_config_missing(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    Path(settings.CLOUDFLARED_CONFIG_PATH).unlink()
    tunnel = TunnelService(settings)
    db = _session()

    result = tunnel.import_external_config_entries(db, actor_email="admin@example.com")

    assert result == []


def test_import_returns_empty_when_ingress_only_fallback(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    tunnel = TunnelService(settings)
    db = _session()

    result = tunnel.import_external_config_entries(db, actor_email="admin@example.com")

    assert result == []


def test_import_creates_exposure_for_unknown_hostname(tmp_path: Path) -> None:
    config = textwrap.dedent("""\
        tunnel: test
        credentials-file: /tmp/creds.json
        ingress:
          - hostname: cool.example.com
            service: http://localhost:8080
          - service: http_status:404
    """)
    settings = _settings(tmp_path, config)
    tunnel = TunnelService(settings)
    db = _session()

    imported = tunnel.import_external_config_entries(db, actor_email="admin@example.com")

    assert len(imported) == 1
    e = imported[0]
    assert e.hostname == "cool.example.com"
    assert e.service_type == ServiceType.HTTP
    assert e.target_host == "localhost"
    assert e.target_port == 8080
    assert e.enabled is True
    assert e.created_by == "admin@example.com"


def test_import_skips_hostname_already_in_db(tmp_path: Path) -> None:
    config = textwrap.dedent("""\
        tunnel: test
        credentials-file: /tmp/creds.json
        ingress:
          - hostname: app.example.com
            service: http://localhost:3000
          - service: http_status:404
    """)
    settings = _settings(tmp_path, config)
    tunnel = TunnelService(settings)
    db = _session()

    existing = _exposure()
    db.add(existing)
    db.flush()

    imported = tunnel.import_external_config_entries(db, actor_email="admin@example.com")

    assert imported == []


def test_import_skips_non_http_scheme(tmp_path: Path) -> None:
    config = textwrap.dedent("""\
        tunnel: test
        credentials-file: /tmp/creds.json
        ingress:
          - hostname: sock.example.com
            service: unix:///var/run/myapp.sock
          - service: http_status:404
    """)
    settings = _settings(tmp_path, config)
    tunnel = TunnelService(settings)
    db = _session()

    imported = tunnel.import_external_config_entries(db, actor_email="admin@example.com")

    assert imported == []


def test_import_skips_entry_without_port(tmp_path: Path) -> None:
    config = textwrap.dedent("""\
        tunnel: test
        credentials-file: /tmp/creds.json
        ingress:
          - hostname: noport.example.com
            service: http://localhost
          - service: http_status:404
    """)
    settings = _settings(tmp_path, config)
    tunnel = TunnelService(settings)
    db = _session()

    imported = tunnel.import_external_config_entries(db, actor_email="admin@example.com")

    assert imported == []


def test_import_idempotent_on_second_call(tmp_path: Path) -> None:
    config = textwrap.dedent("""\
        tunnel: test
        credentials-file: /tmp/creds.json
        ingress:
          - hostname: once.example.com
            service: https://backend:9000
          - service: http_status:404
    """)
    settings = _settings(tmp_path, config)
    tunnel = TunnelService(settings)
    db = _session()

    first = tunnel.import_external_config_entries(db, actor_email="admin@example.com")
    db.flush()
    second = tunnel.import_external_config_entries(db, actor_email="admin@example.com")

    assert len(first) == 1
    assert second == []


def test_import_multiple_entries(tmp_path: Path) -> None:
    config = textwrap.dedent("""\
        tunnel: test
        credentials-file: /tmp/creds.json
        ingress:
          - hostname: a.example.com
            service: http://host-a:1000
          - hostname: b.example.com
            service: https://host-b:2000
          - service: http_status:404
    """)
    settings = _settings(tmp_path, config)
    tunnel = TunnelService(settings)
    db = _session()

    imported = tunnel.import_external_config_entries(db, actor_email="admin@example.com")

    assert len(imported) == 2
    hostnames = {e.hostname for e in imported}
    assert hostnames == {"a.example.com", "b.example.com"}


# ---------------------------------------------------------------------------
# apply_exposure_config — merge / external entry preservation
# ---------------------------------------------------------------------------

def test_apply_preserves_external_entry(tmp_path: Path) -> None:
    config = textwrap.dedent("""\
        tunnel: test
        credentials-file: /tmp/creds.json
        ingress:
          - hostname: external.example.com
            service: http://coolify:3000
          - service: http_status:404
    """)
    settings = _settings(tmp_path, config)
    tunnel = TunnelService(settings)
    db = _session()

    written: dict = {}

    def _capture_write(_, data: dict) -> None:
        written.update(data)

    backup_file = tmp_path / "backup.bak"
    backup_file.write_text("backup", encoding="utf-8")
    tunnel.backup_manager.create_backup = lambda _: backup_file
    tunnel.backup_manager.restore_backup = lambda *_: None
    tunnel.yaml_manager.write = _capture_write
    tunnel.systemd.restart = lambda: None
    tunnel.systemd.is_active = lambda: True

    tunnel.apply_exposure_config(
        db,
        exposures=[_exposure()],
        actor_email="admin@example.com",
        reason="test",
    )

    ingress = written["ingress"]
    hostnames = [e.get("hostname") for e in ingress]
    assert "external.example.com" in hostnames
    assert "app.example.com" in hostnames
    assert ingress[-1] == {"service": "http_status:404"}


def test_apply_external_entries_come_before_db_entries(tmp_path: Path) -> None:
    config = textwrap.dedent("""\
        tunnel: test
        credentials-file: /tmp/creds.json
        ingress:
          - hostname: external.example.com
            service: http://coolify:3000
          - service: http_status:404
    """)
    settings = _settings(tmp_path, config)
    tunnel = TunnelService(settings)
    db = _session()

    written: dict = {}

    def _capture_write(_, data: dict) -> None:
        written.update(data)

    backup_file = tmp_path / "backup.bak"
    backup_file.write_text("backup", encoding="utf-8")
    tunnel.backup_manager.create_backup = lambda _: backup_file
    tunnel.backup_manager.restore_backup = lambda *_: None
    tunnel.yaml_manager.write = _capture_write
    tunnel.systemd.restart = lambda: None
    tunnel.systemd.is_active = lambda: True

    tunnel.apply_exposure_config(
        db,
        exposures=[_exposure()],
        actor_email="admin@example.com",
        reason="test",
    )

    ingress = written["ingress"]
    hostnames_without_fallback = [e.get("hostname") for e in ingress[:-1]]
    assert hostnames_without_fallback[0] == "external.example.com"
    assert hostnames_without_fallback[1] == "app.example.com"


def test_apply_starts_fresh_when_config_missing(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    Path(settings.CLOUDFLARED_CONFIG_PATH).unlink()
    tunnel = TunnelService(settings)
    db = _session()

    written: dict = {}

    def _capture_write(path: str, data: dict) -> None:
        written.update(data)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text("written", encoding="utf-8")

    backup_file = tmp_path / "backup.bak"
    backup_file.write_text("backup", encoding="utf-8")
    tunnel.backup_manager.create_backup = lambda _: backup_file
    tunnel.backup_manager.restore_backup = lambda *_: None
    tunnel.yaml_manager.write = _capture_write
    tunnel.systemd.restart = lambda: None
    tunnel.systemd.is_active = lambda: True

    tunnel.apply_exposure_config(
        db,
        exposures=[_exposure()],
        actor_email="admin@example.com",
        reason="test",
    )

    ingress = written["ingress"]
    assert ingress[-1] == {"service": "http_status:404"}
    assert any(e.get("hostname") == "app.example.com" for e in ingress)


def test_apply_db_entry_replaces_its_own_old_config_entry(tmp_path: Path) -> None:
    """DB exposure with updated port must overwrite the old config entry, not preserve it."""
    config = textwrap.dedent("""\
        tunnel: test
        credentials-file: /tmp/creds.json
        ingress:
          - hostname: app.example.com
            service: http://localhost:9999
          - service: http_status:404
    """)
    settings = _settings(tmp_path, config)
    tunnel = TunnelService(settings)
    db = _session()

    written: dict = {}

    def _capture_write(_, data: dict) -> None:
        written.update(data)

    backup_file = tmp_path / "backup.bak"
    backup_file.write_text("backup", encoding="utf-8")
    tunnel.backup_manager.create_backup = lambda _: backup_file
    tunnel.backup_manager.restore_backup = lambda *_: None
    tunnel.yaml_manager.write = _capture_write
    tunnel.systemd.restart = lambda: None
    tunnel.systemd.is_active = lambda: True

    tunnel.apply_exposure_config(
        db,
        exposures=[_exposure()],  # port 3000
        actor_email="admin@example.com",
        reason="test",
    )

    ingress = written["ingress"]
    app_entry = next(e for e in ingress if e.get("hostname") == "app.example.com")
    assert app_entry["service"] == "http://localhost:3000"
    assert len([e for e in ingress if e.get("hostname") == "app.example.com"]) == 1


# ---------------------------------------------------------------------------
# startup import
# ---------------------------------------------------------------------------

def test_startup_import_creates_exposures_from_config(tmp_path: Path) -> None:
    from app.main import _import_config_entries_on_startup
    from sqlalchemy import select

    config = textwrap.dedent("""\
        tunnel: test
        credentials-file: /tmp/creds.json
        ingress:
          - hostname: startup.example.com
            service: http://backend:4000
          - service: http_status:404
    """)
    settings = _settings(tmp_path, config)
    db = _session()

    def _fake_get_db():
        return db

    import app.main as main_module
    original = main_module.get_db_session
    main_module.get_db_session = _fake_get_db
    try:
        _import_config_entries_on_startup(settings)
    finally:
        main_module.get_db_session = original

    rows = list(db.scalars(select(Exposure)).all())
    assert len(rows) == 1
    assert rows[0].hostname == "startup.example.com"
    assert rows[0].target_port == 4000


def test_startup_import_does_not_crash_when_config_missing(tmp_path: Path) -> None:
    from app.main import _import_config_entries_on_startup

    settings = _settings(tmp_path)
    Path(settings.CLOUDFLARED_CONFIG_PATH).unlink()
    db = _session()

    import app.main as main_module
    original = main_module.get_db_session
    main_module.get_db_session = lambda: db
    try:
        _import_config_entries_on_startup(settings)
    finally:
        main_module.get_db_session = original

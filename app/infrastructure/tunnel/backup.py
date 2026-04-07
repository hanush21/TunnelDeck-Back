from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
from shutil import copy2

logger = logging.getLogger("app.backup")


class BackupManager:
    def __init__(self, backup_dir: str, max_files: int = 20) -> None:
        self.backup_dir = Path(backup_dir)
        self.max_files = max_files
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self, config_path: str) -> Path:
        source = Path(config_path)
        if not source.exists():
            raise FileNotFoundError(f"Cannot backup missing config: {config_path}")

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        backup_path = self.backup_dir / f"config-{timestamp}.yml.bak"
        copy2(source, backup_path)
        self._prune_old_backups()
        return backup_path

    def restore_backup(self, backup_path: Path, config_path: str) -> None:
        destination = Path(config_path)
        copy2(backup_path, destination)

    def _prune_old_backups(self) -> None:
        backups = sorted(
            self.backup_dir.glob("config-*.yml.bak"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        for stale_backup in backups[self.max_files :]:
            try:
                stale_backup.unlink(missing_ok=True)
                logger.info(
                    {
                        "event": "backup_pruned",
                        "file_path": str(stale_backup),
                    }
                )
            except Exception as exc:
                logger.warning(
                    {
                        "event": "backup_prune_failed",
                        "file_path": str(stale_backup),
                        "error": str(exc),
                    }
                )

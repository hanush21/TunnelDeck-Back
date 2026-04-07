from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from shutil import copy2


class BackupManager:
    def __init__(self, backup_dir: str) -> None:
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self, config_path: str) -> Path:
        source = Path(config_path)
        if not source.exists():
            raise FileNotFoundError(f"Cannot backup missing config: {config_path}")

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        backup_path = self.backup_dir / f"config-{timestamp}.yml.bak"
        copy2(source, backup_path)
        return backup_path

    def restore_backup(self, backup_path: Path, config_path: str) -> None:
        destination = Path(config_path)
        copy2(backup_path, destination)

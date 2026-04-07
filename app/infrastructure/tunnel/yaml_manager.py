from __future__ import annotations

from pathlib import Path

import yaml


class YamlManager:
    def load(self, config_path: str) -> dict:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Cloudflared config does not exist: {config_path}")

        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}

        if not isinstance(data, dict):
            raise ValueError("Cloudflared config must be a YAML object")

        return data

    def write(self, config_path: str, config_data: dict) -> None:
        path = Path(config_path)
        with path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(config_data, fh, sort_keys=False)

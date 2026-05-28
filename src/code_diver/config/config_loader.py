from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .app_config import AppConfig


class ConfigLoader:
    def load(self, path: Path | None) -> AppConfig:
        config_path = path or Path("code-diver.yml")
        data: dict[str, Any] = {}
        if config_path.exists():
            loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if loaded:
                if not isinstance(loaded, dict):
                    raise ValueError(f"Config must be a YAML mapping: {config_path}")
                data = loaded
        return AppConfig(
            root=Path(data.get("root", ".")),
            artifact=Path(data.get("artifact", ".code-diver/index.json")),
            embedding=dict(data.get("embedding") or {}),
            pi=dict(data.get("pi") or {}),
            scanner=dict(data.get("scanner") or {}),
            search=dict(data.get("search") or {}),
            ui=dict(data.get("ui") or {}),
            evaluation=dict(data.get("evaluation") or {}),
            plugins=[str(value) for value in data.get("plugins") or []],
        )

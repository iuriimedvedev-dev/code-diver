from __future__ import annotations

from pathlib import Path

import yaml

from .runtime_config import RuntimeConfig


class RuntimeConfigStore:
    def __init__(self, path: Path = Path(".code-diver/runtime.yml")) -> None:
        self.path = path

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> RuntimeConfig:
        if not self.path.exists():
            raise FileNotFoundError(f"Runtime config not found: {self.path}")
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Runtime config must be a YAML mapping: {self.path}")
        return RuntimeConfig.from_yaml_data(data)

    def save(self, config: RuntimeConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(yaml.safe_dump(config.to_yaml_data(), sort_keys=False), encoding="utf-8")


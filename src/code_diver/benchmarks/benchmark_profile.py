from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BenchmarkProfile:
    name: str
    dataset: Path
    description: str
    config_path: Path | None = None
    external_repo: str | None = None
    setup_hint: str | None = None

    def to_json(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "dataset": str(self.dataset),
            "description": self.description,
            "config_path": str(self.config_path) if self.config_path is not None else None,
            "external_repo": self.external_repo,
            "setup_hint": self.setup_hint,
        }

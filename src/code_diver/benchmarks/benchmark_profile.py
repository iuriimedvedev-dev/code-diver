from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .benchmark_preparation import BenchmarkPreparation


@dataclass(frozen=True, slots=True)
class BenchmarkProfile:
    name: str
    dataset: Path
    description: str
    config_path: Path | None = None
    external_repo: str | None = None
    setup_hint: str | None = None
    preparation: BenchmarkPreparation | None = None

    def to_json(self) -> dict[str, str | None]:
        payload: dict[str, str | int | None] = {
            "name": self.name,
            "dataset": str(self.dataset),
            "description": self.description,
            "config_path": str(self.config_path) if self.config_path is not None else None,
            "external_repo": self.external_repo,
            "setup_hint": self.setup_hint,
        }
        if self.preparation is not None:
            payload.update(
                {
                    "preparation": self.preparation.kind,
                    "source_dataset": self.preparation.dataset_name,
                    "language": self.preparation.language,
                    "cases": self.preparation.limit,
                    "estimated_download_mb": self.preparation.estimated_download_mb,
                }
            )
        return payload

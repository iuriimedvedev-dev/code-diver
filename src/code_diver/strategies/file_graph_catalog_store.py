from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .file_graph_catalog import FileGraphCatalog

SCHEMA_VERSION = 2


class FileGraphCatalogStore:
    def __init__(self, artifact: Path):
        self.artifact = artifact

    @classmethod
    def for_graph_artifact(cls, graph_artifact: Path) -> FileGraphCatalogStore:
        return cls(graph_artifact.with_name(f"{graph_artifact.stem}.file-graph-catalog.json"))

    def exists(self) -> bool:
        return self.artifact.exists()

    def is_fresh_for(self, source: Path) -> bool:
        if not self.exists() or not source.exists():
            return False
        return self.artifact.stat().st_mtime >= source.stat().st_mtime

    def load(self) -> FileGraphCatalog:
        payload = json.loads(self.artifact.read_text(encoding="utf-8"))
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported file graph catalog schema: {payload.get('schema_version')}")
        catalog = FileGraphCatalog.from_json(dict(payload.get("catalog") or {}))
        if catalog.fan_in is None:
            raise ValueError("File graph catalog is missing fan_in index")
        return catalog

    def save(self, catalog: FileGraphCatalog) -> None:
        self.artifact.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "catalog": catalog.to_json(),
        }
        self.artifact.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

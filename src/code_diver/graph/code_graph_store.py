from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..settings import SchemaKey
from .code_graph import CodeGraph

SCHEMA_VERSION = 1


class CodeGraphStore:
    def __init__(self, artifact: Path):
        self.artifact = artifact

    def exists(self) -> bool:
        return self.artifact.exists()

    def save(self, graph: CodeGraph) -> None:
        self.artifact.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            SchemaKey.SCHEMA_VERSION.value: SCHEMA_VERSION,
            SchemaKey.CREATED_AT.value: datetime.now(timezone.utc).isoformat(),
            SchemaKey.GRAPH.value: graph.to_json(),
        }
        self.artifact.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load(self) -> CodeGraph:
        payload = json.loads(self.artifact.read_text(encoding="utf-8"))
        if payload.get(SchemaKey.SCHEMA_VERSION.value) != SCHEMA_VERSION:
            raise ValueError(f"Unsupported graph schema: {payload.get(SchemaKey.SCHEMA_VERSION.value)}")
        return CodeGraph.from_json(payload[SchemaKey.GRAPH.value])

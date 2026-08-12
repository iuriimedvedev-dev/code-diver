from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import ijson

from ..domain import CodeItem
from ..settings import SchemaKey
from .code_graph import CodeGraph
from .graph_edge import GraphEdge

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
            SchemaKey.CREATED_AT.value: datetime.now(UTC).isoformat(),
            SchemaKey.GRAPH.value: graph.to_json(),
        }
        self.artifact.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load(self) -> CodeGraph:
        payload = json.loads(self.artifact.read_text(encoding="utf-8"))
        if payload.get(SchemaKey.SCHEMA_VERSION.value) != SCHEMA_VERSION:
            raise ValueError(f"Unsupported graph schema: {payload.get(SchemaKey.SCHEMA_VERSION.value)}")
        return CodeGraph.from_json(payload[SchemaKey.GRAPH.value])

    def stream_items(self) -> Iterator[CodeItem]:
        with self.artifact.open("rb") as graph_file:
            for _, item in ijson.kvitems(graph_file, f"{SchemaKey.GRAPH.value}.{SchemaKey.ITEMS.value}"):
                yield CodeItem.from_json(dict(item))

    def stream_edges(self) -> Iterator[GraphEdge]:
        with self.artifact.open("rb") as graph_file:
            for edge in ijson.items(graph_file, f"{SchemaKey.GRAPH.value}.{SchemaKey.EDGES.value}.item"):
                yield GraphEdge.from_json(dict(edge))

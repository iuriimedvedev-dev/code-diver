from __future__ import annotations

from dataclasses import dataclass

from ..domain import CodeItem
from ..settings import SchemaKey
from .graph_edge import GraphEdge


@dataclass(slots=True)
class CodeGraph:
    items: dict[str, CodeItem]
    edges: list[GraphEdge]

    def neighbors(self, item_id: str) -> list[GraphEdge]:
        return [edge for edge in self.edges if edge.source == item_id or edge.target == item_id]

    def to_json(self) -> dict:
        return {
            SchemaKey.ITEMS.value: {item_id: item.to_json() for item_id, item in self.items.items()},
            SchemaKey.EDGES.value: [edge.to_json() for edge in self.edges],
        }

    @classmethod
    def from_json(cls, data: dict) -> CodeGraph:
        return cls(
            items={
                item_id: CodeItem.from_json(item)
                for item_id, item in dict(data.get(SchemaKey.ITEMS.value) or {}).items()
            },
            edges=[GraphEdge.from_json(edge) for edge in data.get(SchemaKey.EDGES.value) or []],
        )

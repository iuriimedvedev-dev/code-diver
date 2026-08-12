from __future__ import annotations

from dataclasses import dataclass

from ..settings import SchemaKey


@dataclass(slots=True)
class GraphEdge:
    source: str
    target: str
    kind: str
    weight: float = 1.0

    def to_json(self) -> dict:
        return {
            SchemaKey.SOURCE.value: self.source,
            SchemaKey.TARGET.value: self.target,
            SchemaKey.KIND.value: self.kind,
            SchemaKey.WEIGHT.value: self.weight,
        }

    @classmethod
    def from_json(cls, data: dict) -> GraphEdge:
        return cls(
            source=str(data[SchemaKey.SOURCE.value]),
            target=str(data[SchemaKey.TARGET.value]),
            kind=str(data[SchemaKey.KIND.value]),
            weight=float(data.get(SchemaKey.WEIGHT.value, 1.0)),
        )

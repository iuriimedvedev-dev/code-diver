from __future__ import annotations

from dataclasses import dataclass

from ..graph import GraphEdge


@dataclass(frozen=True, slots=True)
class GraphNeighbor:
    item_id: str
    edge: GraphEdge
    weight: float

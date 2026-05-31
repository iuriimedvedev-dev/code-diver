from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class GraphExpansionProfile:
    depth: int
    neighbor_limit: int
    decay: float = 0.72
    min_score: float = 0.0
    edge_weights: dict[str, float] = field(default_factory=dict)
    reverse_edge_weights: dict[str, float] = field(default_factory=dict)

    def weight_for(self, edge_kind: str, *, reverse: bool) -> float:
        weights = self.reverse_edge_weights if reverse else self.edge_weights
        return weights.get(edge_kind, 0.0)

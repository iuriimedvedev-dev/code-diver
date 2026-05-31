from __future__ import annotations

from collections import defaultdict

from ..graph import CodeGraph, GraphEdge
from .graph_expansion_profile import GraphExpansionProfile
from .graph_neighbor import GraphNeighbor


class GraphNeighborIndex:
    def __init__(self, graph: CodeGraph):
        outgoing: dict[str, list[GraphEdge]] = defaultdict(list)
        incoming: dict[str, list[GraphEdge]] = defaultdict(list)
        for edge in graph.edges:
            outgoing[edge.source].append(edge)
            incoming[edge.target].append(edge)
        self.outgoing = dict(outgoing)
        self.incoming = dict(incoming)

    def neighbors(self, item_id: str, profile: GraphExpansionProfile) -> list[GraphNeighbor]:
        neighbors: list[GraphNeighbor] = []
        for edge in self.outgoing.get(item_id, []):
            weight = edge.weight * profile.weight_for(edge.kind, reverse=False)
            if weight > 0:
                neighbors.append(GraphNeighbor(item_id=edge.target, edge=edge, weight=weight))
        for edge in self.incoming.get(item_id, []):
            weight = edge.weight * profile.weight_for(edge.kind, reverse=True)
            if weight > 0:
                neighbors.append(GraphNeighbor(item_id=edge.source, edge=edge, weight=weight))
        neighbors.sort(key=lambda neighbor: (neighbor.weight, neighbor.edge.kind, neighbor.item_id), reverse=True)
        return neighbors[: profile.neighbor_limit]

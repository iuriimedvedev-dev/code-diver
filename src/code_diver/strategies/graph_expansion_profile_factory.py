from __future__ import annotations

from ..settings import EdgeKind
from .graph_expansion_profile import GraphExpansionProfile
from .hybrid_query_router import ROUTE_PATH_SYMBOL, ROUTE_WORKFLOW


class GraphExpansionProfileFactory:
    def create(self, route_name: str, *, depth: int, neighbor_limit: int) -> GraphExpansionProfile:
        if route_name == ROUTE_WORKFLOW:
            return self._workflow(depth, neighbor_limit)
        if route_name == ROUTE_PATH_SYMBOL:
            return self._path_symbol(depth, neighbor_limit)
        return self._semantic(depth, neighbor_limit)

    def _workflow(self, depth: int, neighbor_limit: int) -> GraphExpansionProfile:
        return GraphExpansionProfile(
            depth=max(depth, 2),
            neighbor_limit=max(neighbor_limit, 30),
            decay=0.72,
            edge_weights={
                EdgeKind.CALLS.value: 1.0,
                EdgeKind.REFERENCES.value: 0.9,
                EdgeKind.IMPORTS.value: 0.65,
                EdgeKind.CONTAINS.value: 0.45,
                EdgeKind.SUMMARIZES.value: 0.3,
                EdgeKind.SAME_FILE_NEXT.value: 0.25,
            },
            reverse_edge_weights={
                EdgeKind.CALLS.value: 0.7,
                EdgeKind.REFERENCES.value: 0.65,
                EdgeKind.IMPORTS.value: 0.35,
                EdgeKind.CONTAINS.value: 0.7,
                EdgeKind.SUMMARIZES.value: 0.35,
                EdgeKind.SAME_FILE_NEXT.value: 0.25,
            },
        )

    def _path_symbol(self, depth: int, neighbor_limit: int) -> GraphExpansionProfile:
        return GraphExpansionProfile(
            depth=max(depth, 1),
            neighbor_limit=max(neighbor_limit, 24),
            decay=0.7,
            edge_weights={
                EdgeKind.CONTAINS.value: 0.85,
                EdgeKind.SUMMARIZES.value: 0.55,
                EdgeKind.REFERENCES.value: 0.5,
                EdgeKind.CALLS.value: 0.4,
                EdgeKind.IMPORTS.value: 0.25,
                EdgeKind.SAME_FILE_NEXT.value: 0.35,
            },
            reverse_edge_weights={
                EdgeKind.CONTAINS.value: 0.9,
                EdgeKind.SUMMARIZES.value: 0.65,
                EdgeKind.REFERENCES.value: 0.45,
                EdgeKind.CALLS.value: 0.35,
                EdgeKind.IMPORTS.value: 0.2,
                EdgeKind.SAME_FILE_NEXT.value: 0.35,
            },
        )

    def _semantic(self, depth: int, neighbor_limit: int) -> GraphExpansionProfile:
        return GraphExpansionProfile(
            depth=min(max(depth, 0), 1),
            neighbor_limit=min(max(neighbor_limit, 8), 16),
            decay=0.65,
            edge_weights={
                EdgeKind.CONTAINS.value: 0.45,
                EdgeKind.SUMMARIZES.value: 0.25,
                EdgeKind.SAME_FILE_NEXT.value: 0.2,
                EdgeKind.IMPORTS.value: 0.12,
                EdgeKind.CALLS.value: 0.1,
                EdgeKind.REFERENCES.value: 0.1,
            },
            reverse_edge_weights={
                EdgeKind.CONTAINS.value: 0.5,
                EdgeKind.SUMMARIZES.value: 0.3,
                EdgeKind.SAME_FILE_NEXT.value: 0.2,
                EdgeKind.IMPORTS.value: 0.08,
                EdgeKind.CALLS.value: 0.08,
                EdgeKind.REFERENCES.value: 0.08,
            },
        )

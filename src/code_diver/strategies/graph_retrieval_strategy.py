from __future__ import annotations

from collections import defaultdict

from ..domain import SearchResult
from ..graph import CodeGraph, CodeGraphStore, GraphEdge
from .retrieval_strategy import RetrievalStrategy


class GraphRetrievalStrategy(RetrievalStrategy):
    def __init__(
        self,
        base_strategy: RetrievalStrategy,
        graph_store: CodeGraphStore,
        *,
        expansion_depth: int = 1,
        neighbor_limit: int = 20,
    ):
        self.base_strategy = base_strategy
        self.graph_store = graph_store
        self.expansion_depth = expansion_depth
        self.neighbor_limit = neighbor_limit
        self._graph: CodeGraph | None = None
        self._neighbors_by_id: dict[str, list[GraphEdge]] | None = None

    def search(self, query: str, limit: int) -> list[SearchResult]:
        graph = self._load_graph()
        seed_results = self.base_strategy.search(query, limit)
        items_by_id = {**graph.items, **{result.item.id: result.item for result in seed_results}}
        scores: dict[str, float] = defaultdict(float)
        for result in seed_results:
            scores[result.item.id] = max(scores[result.item.id], result.score)

        frontier = [result.item.id for result in seed_results]
        visited = set(frontier)
        for depth in range(max(self.expansion_depth, 0)):
            next_frontier: list[str] = []
            for item_id in frontier:
                for edge in self._neighbors(item_id)[: self.neighbor_limit]:
                    neighbor_id = edge.target if edge.source == item_id else edge.source
                    if neighbor_id not in items_by_id:
                        continue
                    base_score = scores.get(item_id, 0.0)
                    scores[neighbor_id] = max(scores[neighbor_id], base_score * edge.weight * (0.75**depth))
                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        next_frontier.append(neighbor_id)
            frontier = next_frontier[: self.neighbor_limit]
            if not frontier:
                break

        results = [
            SearchResult(item=items_by_id[item_id], score=score)
            for item_id, score in scores.items()
            if item_id in items_by_id
        ]
        results.sort(key=lambda result: result.score, reverse=True)
        return results[:limit]

    def _load_graph(self) -> CodeGraph:
        if self._graph is None:
            self._graph = self.graph_store.load()
        return self._graph

    def _neighbors(self, item_id: str) -> list[GraphEdge]:
        if self._neighbors_by_id is None:
            by_id: dict[str, list[GraphEdge]] = defaultdict(list)
            for edge in self._load_graph().edges:
                by_id[edge.source].append(edge)
                by_id[edge.target].append(edge)
            self._neighbors_by_id = by_id
        return self._neighbors_by_id.get(item_id, [])

from __future__ import annotations

from collections import defaultdict

from ..domain import SearchResult
from ..graph import CodeGraphStore
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

    def search(self, query: str, limit: int) -> list[SearchResult]:
        graph = self.graph_store.load()
        seed_results = self.base_strategy.search(query, limit)
        scores: dict[str, float] = defaultdict(float)
        for result in seed_results:
            scores[result.item.id] = max(scores[result.item.id], result.score)

        frontier = [result.item.id for result in seed_results]
        visited = set(frontier)
        for depth in range(max(self.expansion_depth, 0)):
            next_frontier: list[str] = []
            for item_id in frontier:
                for edge in graph.neighbors(item_id)[: self.neighbor_limit]:
                    neighbor_id = edge.target if edge.source == item_id else edge.source
                    if neighbor_id not in graph.items:
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
            SearchResult(item=graph.items[item_id], score=score)
            for item_id, score in scores.items()
            if item_id in graph.items
        ]
        results.sort(key=lambda result: result.score, reverse=True)
        return results[:limit]

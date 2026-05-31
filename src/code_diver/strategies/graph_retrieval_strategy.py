from __future__ import annotations

from ..domain import SearchResult
from ..graph import CodeGraph, CodeGraphStore
from .graph_candidate_expander import GraphCandidateExpander
from .graph_expansion_profile_factory import GraphExpansionProfileFactory
from .graph_neighbor_index import GraphNeighborIndex
from .graph_query_classifier import GraphQueryClassifier
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
        self._neighbor_index: GraphNeighborIndex | None = None
        self.query_classifier = GraphQueryClassifier()
        self.profile_factory = GraphExpansionProfileFactory()

    def search(self, query: str, limit: int) -> list[SearchResult]:
        graph = self._load_graph()
        seed_results = self.base_strategy.search(query, max(limit, self.neighbor_limit))
        items_by_id = {**graph.items, **{result.item.id: result.item for result in seed_results}}
        scores: dict[str, float] = {}
        for result in seed_results:
            scores[result.item.id] = max(scores.get(result.item.id, 0.0), result.score)

        route_name = self.query_classifier.classify(query)
        profile = self.profile_factory.create(
            route_name,
            depth=self.expansion_depth,
            neighbor_limit=self.neighbor_limit,
        )
        expanded_scores = GraphCandidateExpander(self._neighbors()).expand(scores, profile)
        for item_id, score in expanded_scores.items():
            if item_id not in items_by_id:
                continue
            scores[item_id] = max(scores.get(item_id, 0.0), score)

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

    def _neighbors(self) -> GraphNeighborIndex:
        if self._neighbor_index is None:
            self._neighbor_index = GraphNeighborIndex(self._load_graph())
        return self._neighbor_index

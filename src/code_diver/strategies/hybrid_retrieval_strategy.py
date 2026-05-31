from __future__ import annotations

from collections import defaultdict

from ..config import HybridSearchConfig
from ..domain import CodeItem, SearchResult
from ..graph import CodeGraph, CodeGraphStore, GraphEdge
from .hybrid_candidate_score import HybridCandidateScore
from .hybrid_candidate_scorer import HybridCandidateScorer
from .hybrid_item_profile import HybridItemProfile
from .hybrid_item_profiler import HybridItemProfiler
from .hybrid_lexical_index import HybridLexicalIndex
from .hybrid_query import HybridQuery
from .hybrid_query_analyzer import HybridQueryAnalyzer
from .retrieval_strategy import RetrievalStrategy


class HybridRetrievalStrategy(RetrievalStrategy):
    def __init__(
        self,
        base_strategy: RetrievalStrategy,
        graph_store: CodeGraphStore,
        config: HybridSearchConfig,
    ):
        self.base_strategy = base_strategy
        self.graph_store = graph_store
        self.config = config
        self.analyzer = HybridQueryAnalyzer(config)
        self.item_profiler = HybridItemProfiler()
        self._item_profiles: dict[str, HybridItemProfile] = {}
        self._lexical_index: HybridLexicalIndex | None = None
        self._graph: CodeGraph | None = None
        self._neighbors_by_id: dict[str, list[GraphEdge]] | None = None

    def search(self, query: str, limit: int) -> list[SearchResult]:
        vector_limit = max(limit, self.config.candidate_limit)
        vector_results = self.base_strategy.search(query, vector_limit)
        graph = self._load_graph()
        if graph is None:
            return vector_results[:limit]

        scores = self._seed_vector_scores(vector_results)
        query_profile = self.analyzer.analyze(query)
        scorer = HybridCandidateScorer(query_profile, self.item_profiler, self._item_profiles)
        for item in self._lexical_candidates(graph, query_profile, scorer):
            existing = scores.setdefault(item.id, HybridCandidateScore(item=item))
            lexical = scorer.score(item)
            existing.lexical_score = max(existing.lexical_score, lexical.lexical_score)
            existing.path_score = max(existing.path_score, lexical.path_score)
            existing.symbol_score = max(existing.symbol_score, lexical.symbol_score)

        for item_id, graph_score in self._graph_scores(vector_results).items():
            item = graph.items.get(item_id)
            if item is None:
                continue
            existing = scores.setdefault(item_id, HybridCandidateScore(item=item))
            existing.graph_score = max(existing.graph_score, graph_score)

        ranked = sorted(
            scores.values(),
            key=lambda score: (score.total(self.config), score.vector_score, score.lexical_score, score.item.path),
            reverse=True,
        )
        return [SearchResult(item=score.item, score=score.total(self.config)) for score in ranked[:limit]]

    def _seed_vector_scores(self, vector_results: list[SearchResult]) -> dict[str, HybridCandidateScore]:
        normalized = self._normalize({result.item.id: result.score for result in vector_results})
        return {
            result.item.id: HybridCandidateScore(item=result.item, vector_score=normalized[result.item.id])
            for result in vector_results
        }

    def _lexical_candidates(
        self,
        graph: CodeGraph,
        query_profile: HybridQuery,
        scorer: HybridCandidateScorer,
    ) -> list[CodeItem]:
        scored = [scorer.score(item) for item in self._load_lexical_index(graph).candidates(query_profile.terms)]
        scored.sort(
            key=lambda score: (score.lexical_score + score.path_score + score.symbol_score, score.item.path),
            reverse=True,
        )
        return [
            score.item
            for score in scored[: self.config.lexical_candidate_limit]
            if score.lexical_score > 0 or score.path_score > 0 or score.symbol_score > 0
        ]

    def _graph_scores(self, vector_results: list[SearchResult]) -> dict[str, float]:
        frontier_scores = self._normalize({result.item.id: result.score for result in vector_results})
        accumulated: dict[str, float] = defaultdict(float)
        visited = set(frontier_scores)
        frontier = frontier_scores
        for depth in range(max(self.config.graph_depth, 0)):
            next_frontier: dict[str, float] = {}
            decay = 0.75**depth
            for item_id, seed_score in frontier.items():
                for edge in self._neighbors(item_id)[: self.config.graph_neighbor_limit]:
                    neighbor_id = edge.target if edge.source == item_id else edge.source
                    score = seed_score * edge.weight * decay
                    accumulated[neighbor_id] = max(accumulated[neighbor_id], score)
                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        next_frontier[neighbor_id] = max(next_frontier.get(neighbor_id, 0.0), score)
            frontier = next_frontier
            if not frontier:
                break
        return self._normalize(accumulated)

    def _load_lexical_index(self, graph: CodeGraph) -> HybridLexicalIndex:
        if self._lexical_index is None:
            self._lexical_index = HybridLexicalIndex(graph.items.values(), self.item_profiler)
            self._item_profiles.update(self._lexical_index.profiles)
        return self._lexical_index

    def _neighbors(self, item_id: str) -> list[GraphEdge]:
        if self._neighbors_by_id is None:
            graph = self._load_graph()
            by_id: dict[str, list[GraphEdge]] = defaultdict(list)
            if graph is not None:
                for edge in graph.edges:
                    by_id[edge.source].append(edge)
                    by_id[edge.target].append(edge)
            self._neighbors_by_id = by_id
        return self._neighbors_by_id.get(item_id, [])

    def _load_graph(self) -> CodeGraph | None:
        if self._graph is not None:
            return self._graph
        if not self.graph_store.exists():
            return None
        self._graph = self.graph_store.load()
        return self._graph

    def _normalize(self, scores: dict[str, float]) -> dict[str, float]:
        if not scores:
            return {}
        values = list(scores.values())
        low = min(values)
        high = max(values)
        if high == low:
            return {item_id: 1.0 for item_id in scores}
        return {item_id: (score - low) / (high - low) for item_id, score in scores.items()}

from __future__ import annotations

from collections import defaultdict

from ..config import HybridSearchConfig
from ..domain import CodeItem, CodeItemIndexKindResolver, SearchResult
from ..graph import CodeGraph, CodeGraphStore, GraphEdge
from .hybrid_candidate_score import HybridCandidateScore
from .hybrid_candidate_scorer import HybridCandidateScorer
from .hybrid_item_profile import HybridItemProfile
from .hybrid_item_profiler import HybridItemProfiler
from .hybrid_lexical_index import HybridLexicalIndex
from .hybrid_query import HybridQuery
from .hybrid_query_analyzer import HybridQueryAnalyzer
from .hybrid_query_router import HybridQueryRouter
from .retrieval_strategy import RetrievalStrategy

LEXICAL_SCORING_BM25 = "bm25"
FUSION_RRF = "rrf"


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
        self.router = HybridQueryRouter()
        self.item_profiler = HybridItemProfiler()
        self.item_kind_resolver = CodeItemIndexKindResolver()
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
        active_config = self.router.route(query, query_profile.terms, self.config)
        scorer = HybridCandidateScorer(query_profile, self.item_profiler, self._item_profiles)
        lexical_scores = self._lexical_scores(graph, query_profile, active_config)
        normalized_lexical_scores = self._normalize(lexical_scores)
        for item in self._lexical_candidates(graph, query_profile, scorer, normalized_lexical_scores, active_config):
            existing = scores.setdefault(item.id, HybridCandidateScore(item=item))
            lexical = scorer.score(item)
            lexical_score = normalized_lexical_scores.get(item.id, lexical.lexical_score)
            existing.lexical_score = max(existing.lexical_score, lexical_score)
            existing.path_score = max(existing.path_score, lexical.path_score)
            existing.symbol_score = max(existing.symbol_score, lexical.symbol_score)

        for item_id, graph_score in self._graph_scores(vector_results, active_config).items():
            item = graph.items.get(item_id)
            if item is None:
                continue
            existing = scores.setdefault(item_id, HybridCandidateScore(item=item))
            existing.graph_score = max(existing.graph_score, graph_score)

        if active_config.fusion == FUSION_RRF:
            return self._rrf_results(scores, vector_results, limit, active_config)
        return self._weighted_results(scores, limit, active_config)

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
        lexical_scores: dict[str, float],
        config: HybridSearchConfig,
    ) -> list[CodeItem]:
        candidates = self._load_lexical_index(graph).candidates(query_profile.terms)
        scored = [scorer.score(item) for item in candidates]
        for score in scored:
            score.lexical_score = max(score.lexical_score, lexical_scores.get(score.item.id, 0.0))
        scored.sort(
            key=lambda score: (score.lexical_score + score.path_score + score.symbol_score, score.item.path),
            reverse=True,
        )
        return [
            score.item
            for score in scored[: config.lexical_candidate_limit]
            if score.lexical_score > 0 or score.path_score > 0 or score.symbol_score > 0
        ]

    def _lexical_scores(
        self,
        graph: CodeGraph,
        query_profile: HybridQuery,
        config: HybridSearchConfig,
    ) -> dict[str, float]:
        if config.lexical_scoring == LEXICAL_SCORING_BM25:
            return self._load_lexical_index(graph).bm25_scores(
                query_profile.terms,
                k1=config.bm25_k1,
                b=config.bm25_b,
            )
        return {}

    def _graph_scores(self, vector_results: list[SearchResult], config: HybridSearchConfig) -> dict[str, float]:
        frontier_scores = self._normalize({result.item.id: result.score for result in vector_results})
        accumulated: dict[str, float] = defaultdict(float)
        visited = set(frontier_scores)
        frontier = frontier_scores
        for depth in range(max(config.graph_depth, 0)):
            next_frontier: dict[str, float] = {}
            decay = 0.75**depth
            for item_id, seed_score in frontier.items():
                for edge in self._neighbors(item_id)[: config.graph_neighbor_limit]:
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

    def _weighted_results(
        self,
        scores: dict[str, HybridCandidateScore],
        limit: int,
        config: HybridSearchConfig,
    ) -> list[SearchResult]:
        ranked = sorted(
            scores.values(),
            key=lambda score: (
                self._weighted_total(score, config),
                score.vector_score,
                score.lexical_score,
                score.item.path,
            ),
            reverse=True,
        )
        return [SearchResult(item=score.item, score=self._weighted_total(score, config)) for score in ranked[:limit]]

    def _rrf_results(
        self,
        scores: dict[str, HybridCandidateScore],
        vector_results: list[SearchResult],
        limit: int,
        config: HybridSearchConfig,
    ) -> list[SearchResult]:
        rrf_scores: dict[str, float] = defaultdict(float)
        self._add_rrf(rrf_scores, [result.item.id for result in vector_results], config.vector_weight, config)
        self._add_rrf(
            rrf_scores,
            self._ranked_ids(scores, lambda score: score.lexical_score),
            config.lexical_weight,
            config,
        )
        self._add_rrf(rrf_scores, self._ranked_ids(scores, lambda score: score.path_score), config.path_weight, config)
        self._add_rrf(
            rrf_scores,
            self._ranked_ids(scores, lambda score: score.symbol_score),
            config.symbol_weight,
            config,
        )
        self._add_rrf(rrf_scores, self._ranked_ids(scores, lambda score: score.graph_score), config.graph_weight, config)
        weighted_rrf_scores = {
            item_id: score * self._item_kind_weight(scores[item_id].item, config)
            for item_id, score in rrf_scores.items()
        }
        ranked = sorted(
            weighted_rrf_scores.items(),
            key=lambda item: (item[1], scores[item[0]].item.path),
            reverse=True,
        )
        return [SearchResult(item=scores[item_id].item, score=score) for item_id, score in ranked[:limit]]

    def _ranked_ids(self, scores: dict[str, HybridCandidateScore], value) -> list[str]:
        ranked = [score for score in scores.values() if value(score) > 0]
        ranked.sort(key=lambda score: (value(score), score.item.path), reverse=True)
        return [score.item.id for score in ranked]

    def _add_rrf(
        self,
        scores: dict[str, float],
        item_ids: list[str],
        weight: float,
        config: HybridSearchConfig,
    ) -> None:
        if weight <= 0:
            return
        for rank, item_id in enumerate(item_ids, start=1):
            scores[item_id] += weight / (config.rrf_k + rank)

    def _weighted_total(self, score: HybridCandidateScore, config: HybridSearchConfig) -> float:
        return score.total(config) * self._item_kind_weight(score.item, config)

    def _item_kind_weight(self, item: CodeItem, config: HybridSearchConfig) -> float:
        kind = self.item_kind_resolver.resolve(item)
        return config.item_kind_weights.get(kind, 1.0)

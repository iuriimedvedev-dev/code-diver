from __future__ import annotations

import logging
from collections import defaultdict
from threading import RLock

from ..config import HybridSearchConfig
from ..domain import CodeItem, CodeItemIndexKindResolver, SearchResult
from ..graph import CodeGraph, CodeGraphStore
from ..tracing import TraceLogger
from .file_graph_adjacency_index import FileGraphAdjacencyIndex
from .file_graph_candidate_expander import FileGraphCandidateExpander
from .file_graph_catalog import FileGraphCatalog
from .file_graph_catalog_store import FileGraphCatalogStore
from .graph_candidate_expander import GraphCandidateExpander
from .graph_expansion_profile import GraphExpansionProfile
from .graph_expansion_profile_factory import GraphExpansionProfileFactory
from .graph_neighbor_index import GraphNeighborIndex
from .hybrid_candidate_score import HybridCandidateScore
from .hybrid_candidate_scorer import HybridCandidateScorer
from .hybrid_item_profile import HybridItemProfile
from .hybrid_item_profiler import HybridItemProfiler
from .hybrid_lexical_index import HybridLexicalIndex
from .hybrid_query import HybridQuery
from .hybrid_query_analyzer import HybridQueryAnalyzer
from .hybrid_query_router import HybridQueryRouter
from .hybrid_rank_context import HybridRankContext
from .retrieval_strategy import RetrievalStrategy

LEXICAL_SCORING_BM25 = "bm25"
FUSION_RRF = "rrf"
TRACE_CANDIDATE_LIMIT = 60

logger = logging.getLogger(__name__)

_SHARED_CACHE_LOCK = RLock()
_SHARED_GRAPHS: dict[str, CodeGraph | None] = {}
_SHARED_LEXICAL_INDEXES: dict[str, tuple[HybridLexicalIndex, dict[str, HybridItemProfile]]] = {}
_SHARED_NEIGHBOR_INDEXES: dict[str, GraphNeighborIndex] = {}
_SHARED_FILE_GRAPH_EXPANDERS: dict[str, FileGraphCandidateExpander] = {}
_SHARED_FILE_GRAPH_CATALOGS: dict[str, FileGraphCatalog] = {}


class HybridRetrievalStrategy(RetrievalStrategy):
    def __init__(
        self,
        base_strategy: RetrievalStrategy,
        graph_store: CodeGraphStore,
        config: HybridSearchConfig,
        trace_logger: TraceLogger | None = None,
    ):
        self.base_strategy = base_strategy
        self.graph_store = graph_store
        self.config = config
        self.trace_logger = trace_logger or TraceLogger.disabled()
        self.analyzer = HybridQueryAnalyzer(config)
        self.router = HybridQueryRouter()
        self.item_profiler = HybridItemProfiler()
        self.item_kind_resolver = CodeItemIndexKindResolver()
        self.graph_profile_factory = GraphExpansionProfileFactory()
        self._item_profiles: dict[str, HybridItemProfile] = {}
        self._lexical_index: HybridLexicalIndex | None = None
        self._graph: CodeGraph | None = None
        self._neighbor_index: GraphNeighborIndex | None = None
        self._file_graph_expander: FileGraphCandidateExpander | None = None
        self._cache_lock = RLock()

    def search(self, query: str, limit: int) -> list[SearchResult]:
        context = self.collect_rank_context(query, limit)
        if context is None:
            vector_results = self.base_strategy.search(query, max(limit, self.config.candidate_limit))
            return vector_results[:limit]

        results = self.rank_context(context, limit)
        self._trace_rank_stages(
            query,
            context.route_name,
            context.scores,
            context.vector_results,
            results,
            context.config,
            effective_graph_depth=context.effective_graph_depth,
            effective_graph_neighbor_limit=context.effective_graph_neighbor_limit,
            graph_candidate_count=context.graph_candidate_count,
        )
        return results

    def collect_rank_context(self, query: str, limit: int) -> HybridRankContext | None:
        vector_limit = max(limit, self.config.candidate_limit)
        vector_results = self.base_strategy.search(query, vector_limit)
        graph = self._load_catalog_graph()
        if graph is None:
            return None

        scores = self._seed_vector_scores(vector_results)
        query_profile = self.analyzer.analyze(query)
        active_config = self.router.route(query, query_profile.terms, self.config)
        scorer = HybridCandidateScorer(
            query_profile,
            self.item_profiler,
            self._item_profiles,
            profile_lock=self._cache_lock,
        )
        if not self._uses_bounded_catalog():
            lexical_scores = self._lexical_scores(graph, query_profile, active_config)
            normalized_lexical_scores = self._normalize(lexical_scores)
            for item in self._lexical_candidates(graph, query_profile, scorer, normalized_lexical_scores, active_config):
                existing = scores.setdefault(item.id, HybridCandidateScore(item=item))
                lexical = scorer.score(item)
                lexical_score = normalized_lexical_scores.get(item.id, lexical.lexical_score)
                existing.lexical_score = max(existing.lexical_score, lexical_score)
                existing.path_score = max(existing.path_score, lexical.path_score)
                existing.symbol_score = max(existing.symbol_score, lexical.symbol_score)
                existing.symbol_match_score = max(existing.symbol_match_score, lexical.symbol_match_score)

        route_name = self.router.route_name(query, query_profile.terms)
        graph_profile = self.graph_profile_factory.create(
            route_name,
            depth=active_config.graph_depth,
            neighbor_limit=active_config.graph_neighbor_limit,
        )
        # graph_score is multiplied by graph_weight in both the weighted-total path
        # (FileScore.total/_weighted_total) and RRF (_add_rrf returns early when weight <= 0),
        # so the expansion below has no effect on ranking once graph_weight is non-positive.
        graph_scores = (
            self._graph_scores(vector_results, graph, graph_profile, active_config)
            if active_config.graph_weight > 0
            else {}
        )
        for item_id, graph_score in graph_scores.items():
            item = graph.items.get(item_id)
            if item is None:
                continue
            existing = scores.setdefault(item_id, HybridCandidateScore(item=item))
            existing.graph_score = max(existing.graph_score, graph_score)

        if self._uses_bounded_catalog():
            self._score_existing_candidates(scores, scorer)

        self._apply_family_penalty(scores, active_config)
        self._apply_file_vote_scores(scores, active_config)
        return HybridRankContext(
            query=query,
            route_name=route_name,
            scores=scores,
            vector_results=vector_results,
            config=active_config,
            effective_graph_depth=graph_profile.depth,
            effective_graph_neighbor_limit=graph_profile.neighbor_limit,
            graph_candidate_count=len(graph_scores),
        )

    def rank_context(self, context: HybridRankContext, limit: int) -> list[SearchResult]:
        if context.config.fusion == FUSION_RRF:
            results = self._rrf_results(context.scores, context.vector_results, limit, context.config)
        else:
            results = self._weighted_results(context.scores, limit, context.config)
        return self._preserve_vector_top(results, context.vector_results, limit, context.config)

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

    def _graph_scores(
        self,
        vector_results: list[SearchResult],
        graph: CodeGraph,
        profile: GraphExpansionProfile,
        config: HybridSearchConfig,
    ) -> dict[str, float]:
        seed_scores = self._normalize({result.item.id: result.score for result in vector_results})
        if config.graph_scope == "file":
            return self._normalize(self._file_expander(graph).expand(seed_scores, profile))
        return self._normalize(GraphCandidateExpander(self._neighbors()).expand(seed_scores, profile))

    def _score_existing_candidates(
        self,
        scores: dict[str, HybridCandidateScore],
        scorer: HybridCandidateScorer,
    ) -> None:
        for existing in scores.values():
            lexical = scorer.score(existing.item)
            existing.lexical_score = max(existing.lexical_score, lexical.lexical_score)
            existing.path_score = max(existing.path_score, lexical.path_score)
            existing.symbol_score = max(existing.symbol_score, lexical.symbol_score)
            existing.symbol_match_score = max(existing.symbol_match_score, lexical.symbol_match_score)

    def _file_expander(self, graph: CodeGraph) -> FileGraphCandidateExpander:
        if self._file_graph_expander is None:
            with self._cache_lock:
                if self._file_graph_expander is None:
                    key = self._cache_key()
                    if key:
                        with _SHARED_CACHE_LOCK:
                            cached = _SHARED_FILE_GRAPH_EXPANDERS.get(key)
                            if cached is None:
                                cached = FileGraphCandidateExpander(
                                    items=graph.items.values(),
                                    adjacency=self._load_file_graph_catalog().adjacency,
                                )
                                _SHARED_FILE_GRAPH_EXPANDERS[key] = cached
                        self._file_graph_expander = cached
                    else:
                        self._file_graph_expander = FileGraphCandidateExpander(
                            items=graph.items.values(),
                            adjacency=self._load_file_graph_catalog().adjacency,
                        )
        return self._file_graph_expander

    def _load_lexical_index(self, graph: CodeGraph) -> HybridLexicalIndex:
        if self._lexical_index is None:
            with self._cache_lock:
                if self._lexical_index is None:
                    key = self._cache_key()
                    if key:
                        with _SHARED_CACHE_LOCK:
                            cached = _SHARED_LEXICAL_INDEXES.get(key)
                            if cached is None:
                                index = HybridLexicalIndex(graph.items.values(), self.item_profiler)
                                cached = (index, dict(index.profiles))
                                _SHARED_LEXICAL_INDEXES[key] = cached
                        self._lexical_index, profiles = cached
                        self._item_profiles.update(profiles)
                    else:
                        self._lexical_index = HybridLexicalIndex(graph.items.values(), self.item_profiler)
                        self._item_profiles.update(self._lexical_index.profiles)
        return self._lexical_index

    def _neighbors(self) -> GraphNeighborIndex:
        if self._neighbor_index is None:
            with self._cache_lock:
                if self._neighbor_index is None:
                    key = self._cache_key()
                    if key:
                        with _SHARED_CACHE_LOCK:
                            cached = _SHARED_NEIGHBOR_INDEXES.get(key)
                            if cached is None:
                                graph = self._load_full_graph()
                                cached = GraphNeighborIndex(graph or CodeGraph(items={}, edges=[]))
                                _SHARED_NEIGHBOR_INDEXES[key] = cached
                        self._neighbor_index = cached
                    else:
                        graph = self._load_full_graph()
                        self._neighbor_index = GraphNeighborIndex(graph or CodeGraph(items={}, edges=[]))
        return self._neighbor_index

    def _load_catalog_graph(self) -> CodeGraph | None:
        if not self._uses_bounded_catalog():
            return self._load_full_graph()
        if not self.graph_store.exists():
            return None
        catalog = self._load_file_graph_catalog()
        return CodeGraph(items=catalog.items_by_id, edges=[])

    def _uses_bounded_catalog(self) -> bool:
        return self.config.graph_scope == "file"

    def _load_file_graph_catalog(self) -> FileGraphCatalog:
        key = self._cache_key()
        if key:
            with _SHARED_CACHE_LOCK:
                cached = _SHARED_FILE_GRAPH_CATALOGS.get(key)
                if cached is not None:
                    return cached
        store = FileGraphCatalogStore.for_graph_artifact(self.graph_store.artifact)
        if store.is_fresh_for(self.graph_store.artifact):
            catalog = store.load()
        else:
            if not self.graph_store.exists():
                catalog = FileGraphCatalog(items_by_id={}, adjacency=FileGraphAdjacencyIndex({}))
            else:
                catalog = FileGraphCatalog.build(
                    self.graph_store.stream_items(),
                    self.graph_store.stream_edges(),
                )
                store.save(catalog)
        if key:
            with _SHARED_CACHE_LOCK:
                _SHARED_FILE_GRAPH_CATALOGS[key] = catalog
        return catalog

    def _load_full_graph(self) -> CodeGraph | None:
        if self._graph is not None:
            return self._graph
        with self._cache_lock:
            if self._graph is not None:
                return self._graph
            key = self._cache_key()
            if key:
                with _SHARED_CACHE_LOCK:
                    if key in _SHARED_GRAPHS:
                        self._graph = _SHARED_GRAPHS[key]
                        return self._graph
            if not self.graph_store.exists():
                if key:
                    with _SHARED_CACHE_LOCK:
                        _SHARED_GRAPHS[key] = None
                return None
            graph = self.graph_store.load()
            if key:
                with _SHARED_CACHE_LOCK:
                    _SHARED_GRAPHS[key] = graph
            self._graph = graph
        return self._graph

    def _cache_key(self) -> str:
        try:
            return str(self.graph_store.artifact.resolve())
        except Exception:
            logger.debug("failed to resolve graph artifact path for cache key", exc_info=True)
            return str(self.graph_store.artifact)

    def _normalize(self, scores: dict[str, float]) -> dict[str, float]:
        if not scores:
            return {}
        values = list(scores.values())
        low = min(values)
        high = max(values)
        if high == low:
            return {item_id: 1.0 for item_id in scores}
        return {item_id: (score - low) / (high - low) for item_id, score in scores.items()}

    _FAMILY_PENALTY_FIELDS: tuple[str, ...] = ("path_score", "symbol_score", "symbol_match_score")

    def _apply_family_penalty(
        self,
        scores: dict[str, HybridCandidateScore],
        config: HybridSearchConfig,
    ) -> None:
        """Dampen path/symbol/symbol_match for candidates that tie on that dimension.

        H49 / H-A: sibling files in the same area of the codebase (e.g. RenameHandler.java and
        RenameProcessor.java) often share every path token the query has, so their path_score
        comes out identical, while their symbol_score can legitimately differ (distinct class
        names). Each field is therefore treated as its own independent "family": within
        path_score, within symbol_score, and within symbol_match_score separately, candidates
        that tie (or nearly tie, given `family_penalty_score_tolerance`) on that one field form a
        family, and if the family has at least `family_penalty_min_family_size` members, that
        field's contribution is proportionally dampened for all of them -- because a value every
        member of a large tied group shares cannot be what discriminates among them. This gives
        zero discrimination for exactly the fraction of the fused score (up to path_weight +
        symbol_weight + symbol_match_weight) that a tied field would otherwise contribute,
        forcing the fused score to lean on vector+lexical there. Families below the size
        threshold (the normal case for mechanical queries, where the correct file's path/symbol
        match is usually unique) are left untouched on that field.
        """
        if not config.family_penalty_enabled or not scores:
            return
        for field in self._FAMILY_PENALTY_FIELDS:
            self._dampen_tied_field(scores, config, field)

    def _dampen_tied_field(
        self,
        scores: dict[str, HybridCandidateScore],
        config: HybridSearchConfig,
        field: str,
    ) -> None:
        families: dict[float, list[HybridCandidateScore]] = defaultdict(list)
        for score in scores.values():
            value = getattr(score, field)
            if value <= 0.0:
                continue
            families[self._family_key(value, config.family_penalty_score_tolerance)].append(score)
        for members in families.values():
            family_size = len(members)
            if family_size < config.family_penalty_min_family_size:
                continue
            factor = (config.family_penalty_min_family_size / family_size) ** config.family_penalty_strength
            for member in members:
                setattr(member, field, getattr(member, field) * factor)

    def _family_key(self, value: float, tolerance: float) -> float:
        if tolerance <= 0.0:
            return value
        return round(value / tolerance) * tolerance

    def _apply_file_vote_scores(
        self,
        scores: dict[str, HybridCandidateScore],
        config: HybridSearchConfig,
    ) -> None:
        if config.file_vote_weight <= 0 or not scores:
            return
        raw_votes: dict[str, float] = defaultdict(float)
        for path, path_scores in self._scores_by_path(scores).items():
            ranked = sorted((self._base_total(score, config) for score in path_scores), reverse=True)
            raw_votes[path] = sum(value * (0.5**index) for index, value in enumerate(ranked[:4]))
        normalized_votes = self._normalize(raw_votes)
        for score in scores.values():
            score.file_vote_score = normalized_votes.get(score.item.path, 0.0)

    def _scores_by_path(
        self,
        scores: dict[str, HybridCandidateScore],
    ) -> dict[str, list[HybridCandidateScore]]:
        by_path: dict[str, list[HybridCandidateScore]] = defaultdict(list)
        for score in scores.values():
            by_path[score.item.path].append(score)
        return by_path

    def _base_total(self, score: HybridCandidateScore, config: HybridSearchConfig) -> float:
        return (
            score.vector_score * config.vector_weight
            + score.lexical_score * config.lexical_weight
            + score.path_score * config.path_weight
            + score.symbol_score * config.symbol_weight
            + score.symbol_match_score * config.symbol_match_weight
            + score.graph_score * config.graph_weight
        )

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

    def _preserve_vector_top(
        self,
        results: list[SearchResult],
        vector_results: list[SearchResult],
        limit: int,
        config: HybridSearchConfig,
    ) -> list[SearchResult]:
        if not config.preserve_vector_top or not results or not vector_results:
            return results
        if results[0].item.id == vector_results[0].item.id:
            return results
        if len(vector_results) > 1:
            margin = vector_results[0].score - vector_results[1].score
            if margin < config.vector_top_score_margin:
                return results

        vector_top = vector_results[0]
        guarded = [SearchResult(item=vector_top.item, score=max(vector_top.score, results[0].score))]
        guarded.extend(result for result in results if result.item.id != vector_top.item.id)
        return guarded[:limit]

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
        self._add_rrf(
            rrf_scores,
            self._ranked_ids(scores, lambda score: score.symbol_match_score),
            config.symbol_match_weight,
            config,
        )
        self._add_rrf(rrf_scores, self._ranked_ids(scores, lambda score: score.graph_score), config.graph_weight, config)
        self._add_rrf(
            rrf_scores,
            self._ranked_ids(scores, lambda score: score.file_vote_score),
            config.file_vote_weight,
            config,
        )
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

    def _trace_rank_stages(
        self,
        query: str,
        route_name: str,
        scores: dict[str, HybridCandidateScore],
        vector_results: list[SearchResult],
        final_results: list[SearchResult],
        config: HybridSearchConfig,
        *,
        effective_graph_depth: int,
        effective_graph_neighbor_limit: int,
        graph_candidate_count: int,
    ) -> None:
        if not self.trace_logger.config.enabled:
            return
        final_graph_hits = sum(1 for result in final_results if scores[result.item.id].graph_score > 0)
        self.trace_logger.write(
            "hybrid_rank_stages",
            {
                "query": query,
                "route": route_name,
                "fusion": config.fusion,
                "candidate_count": len(scores),
                "graph": {
                    "requested_depth": config.graph_depth,
                    "effective_depth": effective_graph_depth,
                    "requested_neighbor_limit": config.graph_neighbor_limit,
                    "effective_neighbor_limit": effective_graph_neighbor_limit,
                    "candidate_count": graph_candidate_count,
                    "final_result_count": final_graph_hits,
                    "final_result_rate": final_graph_hits / max(len(final_results), 1),
                },
                "weights": {
                    "vector": config.vector_weight,
                    "lexical": config.lexical_weight,
                    "path": config.path_weight,
                    "symbol": config.symbol_weight,
                    "symbol_match": config.symbol_match_weight,
                    "graph": config.graph_weight,
                    "file_vote": config.file_vote_weight,
                    "graph_scope": config.graph_scope,
                },
                "candidates": self._trace_candidates(scores, vector_results, final_results, config),
            },
        )

    def _trace_candidates(
        self,
        scores: dict[str, HybridCandidateScore],
        vector_results: list[SearchResult],
        final_results: list[SearchResult],
        config: HybridSearchConfig,
    ) -> list[dict[str, object]]:
        vector_rank = {result.item.id: rank for rank, result in enumerate(vector_results, start=1)}
        final_rank = {result.item.id: rank for rank, result in enumerate(final_results, start=1)}
        lexical_rank = self._rank_map(scores, lambda score: score.lexical_score)
        path_rank = self._rank_map(scores, lambda score: score.path_score)
        symbol_rank = self._rank_map(scores, lambda score: score.symbol_score)
        symbol_match_rank = self._rank_map(scores, lambda score: score.symbol_match_score)
        graph_rank = self._rank_map(scores, lambda score: score.graph_score)
        file_vote_rank = self._rank_map(scores, lambda score: score.file_vote_score)
        ranked_scores = sorted(scores.values(), key=lambda score: self._weighted_total(score, config), reverse=True)
        rows: list[dict[str, object]] = []
        for score in ranked_scores[:TRACE_CANDIDATE_LIMIT]:
            rows.append(
                {
                    "id": score.item.id,
                    "path": score.item.path,
                    "title": score.item.title,
                    "kind": self.item_kind_resolver.resolve(score.item),
                    "final_rank": final_rank.get(score.item.id),
                    "vector_rank": vector_rank.get(score.item.id),
                    "lexical_rank": lexical_rank.get(score.item.id),
                    "path_rank": path_rank.get(score.item.id),
                    "symbol_rank": symbol_rank.get(score.item.id),
                    "symbol_match_rank": symbol_match_rank.get(score.item.id),
                    "graph_rank": graph_rank.get(score.item.id),
                    "file_vote_rank": file_vote_rank.get(score.item.id),
                    "scores": {
                        "total": self._weighted_total(score, config),
                        "vector": score.vector_score,
                        "lexical": score.lexical_score,
                        "path": score.path_score,
                        "symbol": score.symbol_score,
                        "symbol_match": score.symbol_match_score,
                        "graph": score.graph_score,
                        "file_vote": score.file_vote_score,
                    },
                }
            )
        return rows

    def _rank_map(self, scores: dict[str, HybridCandidateScore], value) -> dict[str, int]:
        ranked = [score for score in scores.values() if value(score) > 0]
        ranked.sort(key=lambda score: (value(score), score.item.path), reverse=True)
        return {score.item.id: rank for rank, score in enumerate(ranked, start=1)}

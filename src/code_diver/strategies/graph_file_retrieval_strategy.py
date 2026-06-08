from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ..config import GraphFileSearchConfig
from ..domain import CodeItem, SearchResult
from ..graph import CodeGraphStore
from ..services.tokenizer import tokenize
from .file_graph_catalog import FileGraphCatalog
from .file_graph_catalog_store import FileGraphCatalogStore
from .hybrid_candidate_scorer import HybridCandidateScorer
from .hybrid_item_profiler import HybridItemProfiler
from .hybrid_query import HybridQuery
from .retrieval_strategy import RetrievalStrategy


@dataclass(slots=True)
class FileScore:
    path: str
    item: CodeItem
    vector_score: float = 0.0
    lexical_score: float = 0.0
    path_score: float = 0.0
    symbol_score: float = 0.0
    graph_score: float = 0.0

    def total(self, config: GraphFileSearchConfig) -> float:
        return (
            self.vector_score * config.vector_weight
            + self.lexical_score * config.lexical_weight
            + self.path_score * config.path_weight
            + self.symbol_score * config.symbol_weight
            + self.graph_score * config.graph_weight
        )


class GraphFileRetrievalStrategy(RetrievalStrategy):
    def __init__(
        self,
        base_strategy: RetrievalStrategy,
        graph_store: CodeGraphStore,
        config: GraphFileSearchConfig,
    ):
        self.base_strategy = base_strategy
        self.graph_store = graph_store
        self.config = config
        self.profiler = HybridItemProfiler()
        self._catalog: FileGraphCatalog | None = None

    def search(self, query: str, limit: int) -> list[SearchResult]:
        catalog = self._load_catalog()
        if not catalog.items_by_id:
            return self.base_strategy.search(query, limit)

        file_scores = self._seed_scores(query, catalog, limit)
        if not file_scores:
            return []

        seed_file_scores = {
            path: score.total(self.config)
            for path, score in file_scores.items()
            if score.total(self.config) > 0
        }
        propagated = self._normalize(self._propagate(catalog, seed_file_scores))
        for path, graph_score in propagated.items():
            item = self._item_for_path(catalog, path)
            if item is None:
                continue
            file_score = file_scores.setdefault(path, FileScore(path=path, item=item))
            file_score.graph_score = max(file_score.graph_score, graph_score)

        ranked = sorted(
            file_scores.values(),
            key=lambda score: (score.total(self.config), score.graph_score, score.path),
            reverse=True,
        )
        return [SearchResult(item=score.item, score=score.total(self.config)) for score in ranked[:limit]]

    def _seed_scores(
        self,
        query: str,
        catalog: FileGraphCatalog,
        limit: int,
    ) -> dict[str, FileScore]:
        scores: dict[str, FileScore] = {}
        base_scores: dict[str, float] = {}
        for result in self.base_strategy.search(query, max(limit, self.config.seed_limit)):
            base_scores[result.item.path] = max(base_scores.get(result.item.path, 0.0), result.score)
        vector_scores = self._normalize(base_scores)
        for path, vector_score in vector_scores.items():
            item = self._item_for_path(catalog, path)
            if item is None:
                continue
            scores.setdefault(path, FileScore(path=path, item=item)).vector_score = vector_score

        query_model = HybridQuery(text=query, terms=self._query_terms(query))
        scorer = HybridCandidateScorer(query_model, self.profiler)
        lexical_candidates: list[FileScore] = []
        if self.config.lexical_seed_limit > 0:
            for item in catalog.items_by_id.values():
                candidate = scorer.score(item)
                lexical_score = candidate.lexical_score
                path_score = candidate.path_score
                symbol_score = max(candidate.symbol_score, candidate.symbol_match_score)
                if lexical_score <= 0 and path_score <= 0 and symbol_score <= 0:
                    continue
                lexical_candidates.append(
                    FileScore(
                        path=item.path,
                        item=item,
                        lexical_score=lexical_score,
                        path_score=path_score,
                        symbol_score=symbol_score,
                    )
                )
        lexical_candidates.sort(
            key=lambda score: (score.lexical_score, score.path_score, score.symbol_score, score.path),
            reverse=True,
        )
        for candidate in lexical_candidates[: self.config.lexical_seed_limit]:
            existing = scores.setdefault(candidate.path, FileScore(path=candidate.path, item=candidate.item))
            existing.lexical_score = max(existing.lexical_score, candidate.lexical_score)
            existing.path_score = max(existing.path_score, candidate.path_score)
            existing.symbol_score = max(existing.symbol_score, candidate.symbol_score)
        return scores

    def _propagate(
        self,
        catalog: FileGraphCatalog,
        seed_file_scores: dict[str, float],
    ) -> dict[str, float]:
        accumulated: dict[str, float] = defaultdict(float)
        frontier = dict(sorted(seed_file_scores.items(), key=lambda item: item[1], reverse=True)[: self.config.seed_limit])
        for depth in range(max(self.config.depth, 0)):
            next_frontier: dict[str, float] = defaultdict(float)
            decay = self.config.decay ** (depth + 1)
            for path, seed_score in frontier.items():
                for neighbor_path, edge_weight in catalog.adjacency.adjacency.get(path, [])[: self.config.neighbor_limit]:
                    score = seed_score * edge_weight * decay
                    if score <= 0:
                        continue
                    accumulated[neighbor_path] = max(accumulated[neighbor_path], score)
                    next_frontier[neighbor_path] = max(next_frontier[neighbor_path], score)
            if not next_frontier:
                break
            frontier = dict(
                sorted(next_frontier.items(), key=lambda item: item[1], reverse=True)[: self.config.neighbor_limit]
            )
        return dict(accumulated)

    def _query_terms(self, query: str) -> tuple[str, ...]:
        stop_words = {word.lower() for word in self.config.stop_words}
        tokens = [
            token
            for token in tokenize(query)
            if len(token) >= self.config.min_token_length and token not in stop_words
        ]
        return tuple(dict.fromkeys(tokens))

    def _item_for_path(self, catalog: FileGraphCatalog, path: str) -> CodeItem | None:
        candidates = [item for item in catalog.items_by_id.values() if item.path == path]
        if not candidates:
            return None
        candidates.sort(key=lambda item: (self._representative_rank(item), item.id))
        return candidates[0]

    def _representative_rank(self, item: CodeItem) -> int:
        index_kind = str(item.metadata.get("index_kind") or "")
        if index_kind == "file_summary":
            return 0
        if index_kind == "file_api_manifest":
            return 1
        if index_kind == "file_manifest":
            return 2
        return 3

    def _load_catalog(self) -> FileGraphCatalog:
        if self._catalog is not None:
            return self._catalog
        store = FileGraphCatalogStore.for_graph_artifact(self.graph_store.artifact)
        if store.is_fresh_for(self.graph_store.artifact):
            self._catalog = store.load()
            return self._catalog
        if not self.graph_store.exists():
            self._catalog = FileGraphCatalog(items_by_id={}, adjacency=FileGraphCatalog.build([], []).adjacency)
            return self._catalog
        self._catalog = FileGraphCatalog.build(
            self.graph_store.stream_items(),
            self.graph_store.stream_edges(),
        )
        store.save(self._catalog)
        return self._catalog

    def _normalize(self, scores: dict[str, float]) -> dict[str, float]:
        if not scores:
            return {}
        low = min(scores.values())
        high = max(scores.values())
        if high == low:
            return {key: 1.0 for key in scores}
        return {key: (value - low) / (high - low) for key, value in scores.items()}

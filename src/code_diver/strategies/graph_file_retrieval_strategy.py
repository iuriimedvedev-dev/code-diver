from __future__ import annotations

import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from threading import RLock

from ..config import GraphFileSearchConfig
from ..domain import CodeItem, SearchResult
from ..graph import CodeGraphStore
from ..services.tokenizer import tokenize
from .file_graph_catalog import FileGraphCatalog
from .file_graph_catalog_store import FileGraphCatalogStore
from .hybrid_candidate_scorer import HybridCandidateScorer
from .hybrid_item_profile import HybridItemProfile
from .hybrid_item_profiler import HybridItemProfiler
from .hybrid_query import HybridQuery
from .hybrid_retrieval_strategy import HybridRetrievalStrategy
from .query_fusion_router import QueryFusionRouter
from .retrieval_strategy import RetrievalStrategy

logger = logging.getLogger(__name__)


def _normalize_path(path: str) -> str:
    if not path:
        return ""
    norm = os.path.normpath(path).replace("\\", "/")
    if norm == ".":
        return ""
    if norm.startswith("./"):
        norm = norm[2:]
    return norm.lstrip("/")


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
        self.fusion_router = QueryFusionRouter()
        self.profiler = HybridItemProfiler()
        self._catalog: FileGraphCatalog | None = None
        self._items_by_path: dict[str, list[CodeItem]] | None = None
        self._items_by_norm_path: dict[str, list[CodeItem]] | None = None
        self._path_resolution_cache: dict[str, CodeItem | None] = {}
        # answer_evaluator.py runs concurrent probe queries against one shared strategy
        # instance, so the profile cache must be safe for concurrent read/populate.
        self._cache_lock = RLock()
        # base_strategy tokenizes the same catalog items to build its own lexical index
        # (see HybridRetrievalStrategy._load_lexical_index). Sharing its profile dict/lock
        # by reference -- instead of keeping a private dict here -- means the lexical
        # seeding loop below reuses profiles the base strategy already computed rather than
        # re-tokenizing all ~150k items a second time (Finding 71: this doubled cold-start
        # cost on the IntelliJ-scale catalog, ~68s of pure duplicate work).
        if isinstance(base_strategy, HybridRetrievalStrategy):
            self._item_profiles: dict[str, HybridItemProfile] = base_strategy._item_profiles
            self._profile_lock = base_strategy._cache_lock
        else:
            self._item_profiles = {}
            self._profile_lock = self._cache_lock

    def search(self, query: str, limit: int) -> list[SearchResult]:
        try:
            catalog = self._load_catalog()
            if not catalog.items_by_id:
                return self.base_strategy.search(query, limit)

            config = self.fusion_router.apply_graph_file(query, self.config)
            file_scores = self._seed_scores(query, catalog, limit)
            if not file_scores:
                return self.base_strategy.search(query, limit)

            seed_file_scores = {
                path: score.total(config)
                for path, score in file_scores.items()
                if score.total(config) > 0
            }
            if not seed_file_scores:
                return self.base_strategy.search(query, limit)

            try:
                propagated = self._normalize(self._propagate(catalog, seed_file_scores))
            except Exception:
                propagated = {}

            for path, graph_score in propagated.items():
                item = self._item_for_path(catalog, path)
                if item is None:
                    continue
                file_score = file_scores.setdefault(item.path, FileScore(path=item.path, item=item))
                file_score.graph_score = max(file_score.graph_score, graph_score)

            ranked = sorted(
                file_scores.values(),
                key=lambda score: (score.total(config), score.graph_score, score.path),
                reverse=True,
            )
            results = [
                SearchResult(item=score.item, score=score.total(config))
                for score in ranked[:limit]
            ]
            if not results:
                return self.base_strategy.search(query, limit)
            return results
        except Exception:
            return self.base_strategy.search(query, limit)

    def _seed_scores(
        self,
        query: str,
        catalog: FileGraphCatalog,
        limit: int,
    ) -> dict[str, FileScore]:
        scores: dict[str, FileScore] = {}
        base_scores: dict[str, float] = {}
        base_items: dict[str, CodeItem] = {}
        for result in self.base_strategy.search(query, max(limit, self.config.seed_limit)):
            item = self._item_for_path(catalog, result.item.path)
            if item is not None:
                path = item.path
                rep_item = item
            else:
                path = _normalize_path(result.item.path) or result.item.path
                rep_item = result.item
            base_scores[path] = max(base_scores.get(path, 0.0), result.score)
            if path not in base_items:
                base_items[path] = rep_item

        vector_scores = self._normalize(base_scores)
        for path, vector_score in vector_scores.items():
            rep_item = base_items.get(path)
            if rep_item is None:
                rep_item = self._item_for_path(catalog, path)
            if rep_item is None:
                continue
            scores.setdefault(path, FileScore(path=path, item=rep_item)).vector_score = vector_score

        query_model = HybridQuery(text=query, terms=self._query_terms(query))
        scorer = HybridCandidateScorer(
            query_model,
            self.profiler,
            self._item_profiles,
            profile_lock=self._profile_lock,
        )
        lexical_candidates: list[FileScore] = []
        if self.config.lexical_seed_limit > 0:
            # Try native seed coverages (dual-path, off by default)
            native_coverages = self._try_native_seed_coverages(query_model, catalog)
            if native_coverages is not None:
                lexical_candidates = native_coverages
            else:
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
        from ..native_search import try_propagate_file_scores

        frontier_limit = (
            self.config.neighbor_limit if self.config.frontier_limit is None else self.config.frontier_limit
        )
        native = try_propagate_file_scores(
            catalog.adjacency.adjacency,
            seed_file_scores,
            depth=max(self.config.depth, 0),
            decay=self.config.decay,
            seed_limit=self.config.seed_limit,
            neighbor_limit=self.config.neighbor_limit,
            frontier_limit=frontier_limit,
        )
        if native is not None:
            return native

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
            frontier = dict(sorted(next_frontier.items(), key=lambda item: item[1], reverse=True)[:frontier_limit])
        return dict(accumulated)

    def _try_native_seed_coverages(
        self,
        query_model: HybridQuery,
        catalog: FileGraphCatalog,
    ) -> list[FileScore] | None:
        """Try native seed coverages, return FileScore list or None for Python fallback."""
        from ..native_search import try_seed_coverages

        if not query_model.terms:
            return None

        item_ids: list[str] = []
        paths: list[str] = []
        symbols: dict[str, str | None] = {}

        for item_id, item in catalog.items_by_id.items():
            item_ids.append(item_id)
            paths.append(item.path)
            sym = item.metadata.get("symbol") if item.metadata else None
            symbols[item_id] = str(sym) if sym else None

        if not item_ids:
            return None

        result = try_seed_coverages(
            self._item_profiles,
            item_ids,
            paths,
            list(query_model.terms),
            self.config.lexical_seed_limit,
            symbols,
        )
        if result is None:
            return None

        item_by_id = {item.id: item for item in catalog.items_by_id.values()}
        file_scores: list[FileScore] = []
        for item_id, lexical_score, path_score, symbol_score in result:
            item = item_by_id.get(item_id)
            if item is None:
                continue
            file_scores.append(
                FileScore(
                    path=item.path,
                    item=item,
                    lexical_score=lexical_score,
                    path_score=path_score,
                    symbol_score=symbol_score,
                )
            )
        return file_scores

    def _query_terms(self, query: str) -> tuple[str, ...]:
        stop_words = {word.lower() for word in self.config.stop_words}
        tokens = [
            token
            for token in tokenize(query)
            if len(token) >= self.config.min_token_length and token not in stop_words
        ]
        return tuple(dict.fromkeys(tokens))

    def _item_for_path(self, catalog: FileGraphCatalog, path: str) -> CodeItem | None:
        if not path:
            return None
        with self._cache_lock:
            if path in self._path_resolution_cache:
                return self._path_resolution_cache[path]
            item = self._resolve_item_for_path(catalog, path)
            self._path_resolution_cache[path] = item
            return item

    def _resolve_item_for_path(self, catalog: FileGraphCatalog, path: str) -> CodeItem | None:
        items_by_path = self._items_by_path_index(catalog)
        candidates = items_by_path.get(path)
        if candidates:
            return candidates[0]

        norm_path = _normalize_path(path)
        items_by_norm = self._items_by_norm_path_index(catalog)
        candidates = items_by_norm.get(norm_path)
        if candidates:
            return candidates[0]

        matches: list[tuple[int, str, CodeItem]] = []
        for cat_norm, cat_items in items_by_norm.items():
            if not cat_norm or not cat_items:
                continue
            if norm_path.endswith("/" + cat_norm) or cat_norm.endswith("/" + norm_path):
                diff = abs(len(norm_path) - len(cat_norm))
                matches.append((diff, cat_norm, cat_items[0]))

        if matches:
            matches.sort(key=lambda m: (m[0], m[1]))
            return matches[0][2]

        return None

    def _items_by_path_index(self, catalog: FileGraphCatalog) -> dict[str, list[CodeItem]]:
        if self._items_by_path is not None:
            return self._items_by_path
        by_path: dict[str, list[CodeItem]] = defaultdict(list)
        for item in catalog.items_by_id.values():
            by_path[item.path].append(item)
        for candidates in by_path.values():
            candidates.sort(key=lambda item: (self._representative_rank(item), item.id))
        self._items_by_path = dict(by_path)
        return self._items_by_path

    def _items_by_norm_path_index(self, catalog: FileGraphCatalog) -> dict[str, list[CodeItem]]:
        if self._items_by_norm_path is not None:
            return self._items_by_norm_path
        by_norm: dict[str, list[CodeItem]] = defaultdict(list)
        for item in catalog.items_by_id.values():
            by_norm[_normalize_path(item.path)].append(item)
        for candidates in by_norm.values():
            candidates.sort(key=lambda item: (self._representative_rank(item), item.id))
        self._items_by_norm_path = dict(by_norm)
        return self._items_by_norm_path

    def _representative_rank(self, item: CodeItem) -> int:
        index_kind = str(item.metadata.get("index_kind") or "")
        if index_kind == "file_summary":
            return 0
        if index_kind == "file_api_manifest":
            return 1
        if index_kind == "file_manifest":
            return 2
        if index_kind == "file_purpose":
            return 3
        if index_kind == "doc_summary":
            return 4
        if index_kind == "doc_manifest":
            return 5
        return 6

    def _load_catalog(self) -> FileGraphCatalog:
        if self._catalog is not None:
            return self._catalog
        store = FileGraphCatalogStore.for_graph_artifact(self.graph_store.artifact)
        if store.is_fresh_for(self.graph_store.artifact):
            self._catalog = store.load()
            self._items_by_path = None
            self._items_by_norm_path = None
            self._path_resolution_cache.clear()
            return self._catalog
        if not self.graph_store.exists():
            self._catalog = FileGraphCatalog(items_by_id={}, adjacency=FileGraphCatalog.build([], []).adjacency)
            self._items_by_path = None
            self._items_by_norm_path = None
            self._path_resolution_cache.clear()
            return self._catalog
        self._catalog = FileGraphCatalog.build(
            self.graph_store.stream_items(),
            self.graph_store.stream_edges(),
        )
        try:
            store.save(self._catalog)
        except Exception:
            logger.debug("failed to persist file graph catalog cache", exc_info=True)
        self._items_by_path = None
        self._items_by_norm_path = None
        self._path_resolution_cache.clear()
        return self._catalog

    def _normalize(self, scores: dict[str, float]) -> dict[str, float]:
        if not scores:
            return {}
        low = min(scores.values())
        high = max(scores.values())
        if high == low:
            return {key: 1.0 for key in scores}
        return {key: (value - low) / (high - low) for key, value in scores.items()}

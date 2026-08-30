from __future__ import annotations

import math

from ..domain import SearchResult
from ..math_utils import normalize
from ..providers import EmbeddingProvider
from ..settings import Defaults
from ..store import VectorStore
from .retrieval_strategy import RetrievalStrategy


class MultiIndexVectorRetrievalStrategy(RetrievalStrategy):
    def __init__(
        self,
        provider: EmbeddingProvider,
        vector_store: VectorStore,
        kind_limits: dict[str, int],
        kind_multipliers: dict[str, float] | None = None,
        path_dedup_kinds: list[str] | None = None,
    ):
        self.provider = provider
        self.vector_store = vector_store
        self.kind_limits = {kind: limit for kind, limit in kind_limits.items() if limit > 0}
        self.kind_multipliers = {
            kind: multiplier
            for kind, multiplier in (kind_multipliers or {}).items()
            if multiplier > 0
        }
        self.path_dedup_kinds = frozenset(path_dedup_kinds or ())

    def search(self, query: str, limit: int) -> list[SearchResult]:
        effective_limits = self._effective_limits(limit)
        if not effective_limits:
            return self.vector_store.search(normalize(self.provider.embed_query(query)), limit)
        query_vector = normalize(self.provider.embed_query(query))
        results: list[SearchResult] = []
        for kind, kind_limit in effective_limits.items():
            results.extend(self._kind_results(query_vector, kind, kind_limit))
        return self._ranked(results, limit)

    def _kind_results(self, query_vector: list[float], kind: str, kind_limit: int) -> list[SearchResult]:
        if kind not in self.path_dedup_kinds:
            return self.vector_store.search_by_index_kind(query_vector, kind_limit, kind)
        # A chunk lane holds many points per file, so `kind_limit` slots reach far fewer files
        # than a file-level lane does. Over-fetch, then keep each file's best point, so the
        # lane budget is spent on distinct candidate files instead of on one big file's methods.
        overfetch = kind_limit * Defaults.HYBRID_VECTOR_KIND_PATH_DEDUP_OVERFETCH
        best_by_path: dict[str, SearchResult] = {}
        for result in self.vector_store.search_by_index_kind(query_vector, overfetch, kind):
            current = best_by_path.get(result.item.path)
            if current is None or result.score > current.score:
                best_by_path[result.item.path] = result
        ranked = sorted(best_by_path.values(), key=lambda result: (result.score, result.item.path), reverse=True)
        return ranked[:kind_limit]

    def _effective_limits(self, limit: int) -> dict[str, int]:
        if self.kind_limits:
            return self.kind_limits
        return {kind: max(1, math.ceil(limit * multiplier)) for kind, multiplier in self.kind_multipliers.items()}

    def _ranked(self, results: list[SearchResult], limit: int) -> list[SearchResult]:
        by_id: dict[str, SearchResult] = {}
        for result in results:
            current = by_id.get(result.item.id)
            if current is None or result.score > current.score:
                by_id[result.item.id] = result
        ranked = sorted(by_id.values(), key=lambda result: (result.score, result.item.path), reverse=True)
        return ranked[:limit]

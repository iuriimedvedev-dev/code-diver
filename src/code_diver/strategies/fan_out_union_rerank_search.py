from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..config.cross_encoder_rerank_config import CrossEncoderRerankConfig
from ..domain import SearchResult
from ..reranking import RerankProvider
from ..reranking.cross_encoder_document_builder import build_cross_encoder_document
from .retrieval_strategy import RetrievalStrategy

logger = logging.getLogger(__name__)


class FanOutUnionRerankSearch:
    """H-76: one cross-encoder pass over the union of several probe searches.

    The champion pipeline reranks every probe separately, so N rephrasings cost N
    cross-encoder passes over largely the same candidates and the merge has to splice
    N already-truncated top-10 lists. Here the probes run on the CE-less base strategy
    (hybrid + graph-file), their candidates are unioned, and a single CE pass ranks the
    whole pool. Coverage from the probes can therefore convert into recall instead of
    evicting an equally good file from a fixed window.
    """

    def __init__(
        self,
        base_strategy: RetrievalStrategy,
        rerank_provider: RerankProvider,
        config: CrossEncoderRerankConfig,
        repository_root: Path | None = None,
        max_workers: int = 6,
        union_candidate_limit: int = 0,
    ):
        self.base_strategy = base_strategy
        self.rerank_provider = rerank_provider
        self.config = config
        self.repository_root = repository_root
        self.max_workers = max(1, max_workers)
        self.union_candidate_limit = union_candidate_limit

    def paths(self, queries: list[str], limit: int, per_query_limit: int) -> list[str]:
        """Ranked unique file paths; the first query is the original user query."""
        seen: set[str] = set()
        ordered: list[str] = []
        for result in self.search(queries, limit, per_query_limit):
            path = result.item.path
            if path in seen:
                continue
            seen.add(path)
            ordered.append(path)
            if len(ordered) >= limit:
                break
        return ordered

    def search(self, queries: list[str], limit: int, per_query_limit: int) -> list[SearchResult]:
        probes = [item for item in queries if item and item.strip()]
        if not probes:
            return []
        ranked_lists = self._probe(probes, per_query_limit)
        union = self._union(ranked_lists)
        if len(union) <= 1:
            return union
        pool_limit = self.union_candidate_limit or self.config.candidate_limit
        pool = union[: max(limit, pool_limit)]
        tail = union[len(pool) :]
        documents = [build_cross_encoder_document(item, self.config, self.repository_root) for item in pool]
        wanted = min(len(pool), max(limit * 3, 40))
        try:
            scores = self.rerank_provider.rerank(probes[0], documents, wanted)
        except Exception as exc:
            logger.warning(
                "fan-out union rerank failed over %s candidates, falling back to fused order: %s: %s",
                len(pool),
                type(exc).__name__,
                exc,
            )
            return union
        return self._ordered(pool, tail, scores)

    def _probe(self, probes: list[str], per_query_limit: int) -> list[list[SearchResult]]:
        if len(probes) == 1:
            return [self.base_strategy.search(probes[0], per_query_limit)]
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(probes))) as pool:
            return list(pool.map(lambda item: self.base_strategy.search(item, per_query_limit), probes))

    def _union(self, ranked_lists: list[list[SearchResult]]) -> list[SearchResult]:
        """Reciprocal rank fusion only decides the pool order handed to the reranker.

        The cross-encoder re-ranks the head anyway; fusion order matters for what falls
        outside the CE window and for the untouched tail.
        """
        scores: dict[str, float] = {}
        items: dict[str, SearchResult] = {}
        for ranked in ranked_lists:
            for rank, result in enumerate(ranked, start=1):
                key = result.item.id
                items.setdefault(key, result)
                scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank)
        return [items[key] for key in sorted(scores, key=lambda key: -scores[key])]

    def _ordered(self, pool: list[SearchResult], tail: list[SearchResult], scores) -> list[SearchResult]:
        selected: list[int] = []
        seen: set[int] = set()
        for score in scores:
            if score.index < 0 or score.index >= len(pool) or score.index in seen:
                continue
            selected.append(score.index)
            seen.add(score.index)
        ordered = [pool[index] for index in selected]
        ordered.extend(item for index, item in enumerate(pool) if index not in seen)
        ordered.extend(tail)
        return ordered

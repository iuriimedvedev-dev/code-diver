from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ..domain import CodeItemIndexKindResolver, SearchResult
from .retrieval_strategy import RetrievalStrategy

FUSION_RRF = "rrf"
FUSION_MAX = "max"
FUSION_UNION = "union"


class DualCollectionVectorRetrievalStrategy(RetrievalStrategy):
    """Search two vector lanes and fuse candidates at file (path) level.

    H-73: H46 and H66b fail on disjoint query classes. Union-of-pools raises the
    recall ceiling without changing either collection's documents. Fusion is OFF
    unless a secondary strategy is wired; existing single-collection behaviour is
    unchanged.
    """

    def __init__(
        self,
        primary: RetrievalStrategy,
        secondary: RetrievalStrategy,
        *,
        fusion: str = FUSION_RRF,
        rrf_k: int = 60,
    ):
        self.primary = primary
        self.secondary = secondary
        self.fusion = fusion
        self.rrf_k = rrf_k
        self._kind_resolver = CodeItemIndexKindResolver()

    def search(self, query: str, limit: int) -> list[SearchResult]:
        with ThreadPoolExecutor(max_workers=2) as pool:
            primary_future = pool.submit(self.primary.search, query, limit)
            secondary_future = pool.submit(self.secondary.search, query, limit)
            primary_results = primary_future.result()
            secondary_results = secondary_future.result()
        if self.fusion == FUSION_MAX:
            return self._max_fuse(primary_results, secondary_results, limit)
        if self.fusion == FUSION_UNION:
            return self._union_fuse(primary_results, secondary_results, limit)
        return self._rrf_fuse(primary_results, secondary_results, limit)

    def _rrf_fuse(
        self,
        primary_results: list[SearchResult],
        secondary_results: list[SearchResult],
        limit: int,
    ) -> list[SearchResult]:
        """Path-level RRF order; score carries RRF mass so shared paths outrank single-list tails."""
        path_ranks_primary = self._path_ranks(primary_results)
        path_ranks_secondary = self._path_ranks(secondary_results)
        path_scores: dict[str, float] = {}
        for path, rank in path_ranks_primary.items():
            path_scores[path] = path_scores.get(path, 0.0) + 1.0 / (self.rrf_k + rank)
        for path, rank in path_ranks_secondary.items():
            path_scores[path] = path_scores.get(path, 0.0) + 1.0 / (self.rrf_k + rank)
        items_by_path_kind = self._best_items_by_path_kind(primary_results, secondary_results)
        ordered_paths = sorted(
            path_scores,
            key=lambda path: (path_scores[path], self._best_raw_score(items_by_path_kind.get(path, {})), path),
            reverse=True,
        )
        fused: list[SearchResult] = []
        for path in ordered_paths:
            kind_items = items_by_path_kind.get(path, {})
            ranked_kinds = sorted(
                kind_items.values(),
                key=lambda entry: (entry[1], entry[0].id),
                reverse=True,
            )
            for item, item_score, _source in ranked_kinds:
                fused.append(SearchResult(item=item, score=path_scores[path] + item_score * 1e-9))
                if len(fused) >= limit:
                    return fused
        return fused

    def _max_fuse(
        self,
        primary_results: list[SearchResult],
        secondary_results: list[SearchResult],
        limit: int,
    ) -> list[SearchResult]:
        items_by_path_kind = self._best_items_by_path_kind(primary_results, secondary_results)
        ordered_paths = sorted(
            items_by_path_kind,
            key=lambda path: (self._best_raw_score(items_by_path_kind[path]), path),
            reverse=True,
        )
        fused: list[SearchResult] = []
        for path in ordered_paths:
            kind_items = items_by_path_kind.get(path, {})
            ranked_kinds = sorted(
                kind_items.values(),
                key=lambda entry: (entry[1], entry[0].id),
                reverse=True,
            )
            for item, item_score, _source in ranked_kinds:
                fused.append(SearchResult(item=item, score=item_score))
                if len(fused) >= limit:
                    return fused
        return fused

    def _union_fuse(
        self,
        primary_results: list[SearchResult],
        secondary_results: list[SearchResult],
        limit: int,
    ) -> list[SearchResult]:
        """Keep every primary hit, then append secondary-only paths.

        Do not truncate primary to make room — dropping primary tail removes gold that
        hybrid/lexical would still rank. Hybrid applies candidate_limit after scoring,
        so returning primary+secondary (may exceed `limit`) lets new paths compete
        without reshuffling the H-66b vector head.
        """
        fused: list[SearchResult] = []
        seen_path_kind: set[tuple[str, str]] = set()
        primary_paths: set[str] = set()
        for result in primary_results:
            kind = self._kind_resolver.resolve(result.item)
            key = (result.item.path, kind)
            if key in seen_path_kind:
                continue
            seen_path_kind.add(key)
            primary_paths.add(result.item.path)
            fused.append(result)

        # Cap secondary additions so we don't explode the hybrid score map.
        secondary_cap = max(limit, len(fused)) + min(limit // 2, 180)
        for result in secondary_results:
            if len(fused) >= secondary_cap:
                break
            if result.item.path in primary_paths:
                continue
            kind = self._kind_resolver.resolve(result.item)
            key = (result.item.path, kind)
            if key in seen_path_kind:
                continue
            seen_path_kind.add(key)
            fused.append(result)
        return fused

    @staticmethod
    def _best_raw_score(kind_items: dict[str, tuple]) -> float:
        if not kind_items:
            return float("-inf")
        return max(entry[1] for entry in kind_items.values())

    def _path_ranks(self, results: list[SearchResult]) -> dict[str, int]:
        """Best-score-first unique path ranks (1-based) for RRF."""
        best_score: dict[str, float] = {}
        for result in results:
            path = result.item.path
            current = best_score.get(path)
            if current is None or result.score > current:
                best_score[path] = result.score
        ordered = sorted(best_score, key=lambda path: (best_score[path], path), reverse=True)
        return {path: rank for rank, path in enumerate(ordered, start=1)}

    def _best_items_by_path_kind(
        self,
        primary_results: list[SearchResult],
        secondary_results: list[SearchResult],
    ) -> dict[str, dict[str, tuple]]:
        """Keep the best item per (path, index_kind). Primary wins score ties."""
        by_path: dict[str, dict[str, tuple]] = {}
        for source_order, results in ((0, primary_results), (1, secondary_results)):
            for result in results:
                path = result.item.path
                kind = self._kind_resolver.resolve(result.item)
                bucket = by_path.setdefault(path, {})
                current = bucket.get(kind)
                if current is None or result.score > current[1] or (
                    result.score == current[1] and source_order < current[2]
                ):
                    bucket[kind] = (result.item, result.score, source_order)
        return by_path

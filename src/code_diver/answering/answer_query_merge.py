"""Merge logic for multi-probe query fan-out, shared by `AnswerEvaluator` and any tool that
replays its probe queries (for example `scripts/replay_pool_recall.py`).

This was factored out of `AnswerEvaluator._retrieve` so the two call sites can never drift:
a change to scoring, dedup, or ordering here changes both the live pipeline and any replay
harness measuring it. Do not reimplement this logic elsewhere -- import `merge_query_results`.
"""

from __future__ import annotations

from ..domain import SearchResult


def merge_query_results(result_sets: list[list[SearchResult]], limit: int) -> list[SearchResult]:
    """Merge per-probe-query result sets into one ranked, deduplicated candidate pool.

    Each candidate's merged score is its own retrieval score plus a reciprocal-rank bonus
    within the query that surfaced it, plus a small boost that favors earlier (higher
    priority) probe queries. Candidates are deduplicated by normalized file path, keeping
    the highest-scoring occurrence across all probe queries. The result is sorted by merged
    score, descending, and truncated to `limit`.
    """
    best_by_file: dict[str, SearchResult] = {}
    for query_index, results in enumerate(result_sets):
        query_boost = 1.0 / (query_index + 1)
        for rank, result in enumerate(results, start=1):
            file_key = normalize_merge_path(result.item.path)
            rank_score = 1.0 / rank
            merged_score = float(result.score) + rank_score + (0.05 * query_boost)
            existing = best_by_file.get(file_key)
            if existing is None or merged_score > existing.score:
                best_by_file[file_key] = SearchResult(result.item, merged_score)
    return sorted(best_by_file.values(), key=lambda item: item.score, reverse=True)[:limit]


def normalize_merge_path(path: str) -> str:
    """Normalize a file path for merge-time deduplication only.

    Kept in lockstep with `AnswerEvaluator._normalize_path`; duplicated rather than shared
    because the two call sites already diverge in the codebase and this module must not
    depend on `AnswerEvaluator`.
    """
    return path.strip().lstrip("./")

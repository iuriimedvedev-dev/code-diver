from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from ..config.cross_encoder_rerank_config import CrossEncoderRerankConfig
from ..domain import SearchResult
from ..reranking import RerankProvider
from ..reranking.cross_encoder_document_builder import build_cross_encoder_document


class AnswerCandidateCrossEncoderReranker:
    """Final candidate rerank for answer evaluation, backed by a cross-encoder.

    Interchangeable with `AnswerCandidateReranker`: same `candidate_limit` property, same
    `rerank(query, candidates, limit)` returning `(results, payload)`. The payload keeps the
    generative reranker's key names -- `candidate_count`, `selected_candidates`, `duration_ms`,
    `model` -- because the report schema, the metrics, and every analysis script in `scripts/`
    read those keys and must not have to know which primitive produced them. Token and cost
    fields stay at zero: a cross-encoder emits no tokens, and reporting a fabricated count would
    corrupt the cost-per-case series.
    """

    def __init__(
        self,
        provider: RerankProvider,
        config: CrossEncoderRerankConfig,
        repository_root: Path | None = None,
    ):
        self.provider = provider
        self.config = config
        self.repository_root = repository_root

    @property
    def candidate_limit(self) -> int:
        return max(1, self.config.candidate_limit)

    def rerank(
        self, query: str, candidates: list[SearchResult], limit: int
    ) -> tuple[list[SearchResult], dict[str, Any]]:
        rerank_candidates = candidates[: self.candidate_limit]
        if len(rerank_candidates) <= 1:
            return rerank_candidates[:limit], self._empty_payload(query, len(rerank_candidates))
        documents = [self._document(candidate) for candidate in rerank_candidates]
        started = perf_counter()
        try:
            scores = self.provider.rerank(query, documents, min(limit, len(rerank_candidates)))
            duration_ms = (perf_counter() - started) * 1000
        except Exception as exc:
            payload = self._empty_payload(query, len(rerank_candidates))
            payload["duration_ms"] = (perf_counter() - started) * 1000
            payload["error"] = str(exc)
            payload["fallback"] = "base_candidate_order"
            return candidates[:limit], payload
        ordered = self._ordered_indices(scores, len(rerank_candidates))
        ranked = self._reranked(rerank_candidates, ordered, limit)
        return ranked, self._payload(query, duration_ms, ordered, rerank_candidates, scores)

    def _document(self, result: SearchResult) -> str:
        return build_cross_encoder_document(result, self.config, self.repository_root)

    def _ordered_indices(self, scores, candidate_count: int) -> list[int]:
        """Zero-based candidate positions, best first, de-duplicated and range-checked.

        A provider that echoes an out-of-range or repeated index must not be able to drop a
        candidate or duplicate one into the answer context.
        """
        ordered: list[int] = []
        seen: set[int] = set()
        for score in scores:
            index = int(score.index)
            if index < 0 or index >= candidate_count or index in seen:
                continue
            ordered.append(index)
            seen.add(index)
        return ordered

    def _reranked(
        self, candidates: list[SearchResult], ordered: list[int], limit: int
    ) -> list[SearchResult]:
        selected = set(ordered)
        reranked = [candidates[index] for index in ordered]
        reranked.extend(
            candidate for index, candidate in enumerate(candidates) if index not in selected
        )
        if self._should_preserve_top(candidates, reranked):
            reranked = [
                candidates[0],
                *(candidate for candidate in reranked if candidate.item.id != candidates[0].item.id),
            ]
        return reranked[:limit]

    def _should_preserve_top(
        self, candidates: list[SearchResult], reranked: list[SearchResult]
    ) -> bool:
        if not self.config.preserve_top_candidate or not candidates or not reranked:
            return False
        if reranked[0].item.id == candidates[0].item.id:
            return False
        if len(candidates) == 1:
            return True
        margin = candidates[0].score - candidates[1].score
        return margin >= self.config.preserve_top_score_margin

    def _payload(
        self,
        query: str,
        duration_ms: float,
        ordered: list[int],
        candidates: list[SearchResult],
        scores,
    ) -> dict[str, Any]:
        by_index = {int(score.index): float(score.score) for score in scores}
        return {
            "enabled": True,
            "provider": self.provider.name,
            "model": self.provider.model,
            "query": query,
            "duration_ms": duration_ms,
            "candidate_count": len(candidates),
            # One-based to match the generative reranker, whose prompt numbers candidates from 1.
            "selected_indices": [index + 1 for index in ordered],
            "selected_candidates": [
                {
                    "rerank_rank": rank,
                    "index": index + 1,
                    "confidence": by_index.get(index),
                    "reason": "",
                    "id": candidates[index].item.id,
                    "path": candidates[index].item.path,
                    "base_score": candidates[index].score,
                }
                for rank, index in enumerate(ordered, start=1)
            ],
            "attempt": 1,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_cost": 0.0,
        }

    def _empty_payload(self, query: str, candidate_count: int) -> dict[str, Any]:
        return {
            "enabled": bool(candidate_count),
            "provider": self.provider.name,
            "model": self.provider.model,
            "query": query,
            "duration_ms": 0.0,
            "candidate_count": candidate_count,
            "selected_indices": [],
            "selected_candidates": [],
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_cost": 0.0,
        }

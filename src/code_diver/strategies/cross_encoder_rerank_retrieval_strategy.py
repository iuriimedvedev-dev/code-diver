from __future__ import annotations

from time import perf_counter

from ..config.cross_encoder_rerank_config import CrossEncoderRerankConfig
from ..domain import SearchResult
from ..reranking import RerankProvider
from ..tracing import TraceLogger
from .retrieval_strategy import RetrievalStrategy


class CrossEncoderRerankRetrievalStrategy(RetrievalStrategy):
    def __init__(
        self,
        base_strategy: RetrievalStrategy,
        rerank_provider: RerankProvider,
        config: CrossEncoderRerankConfig,
        trace_logger: TraceLogger | None = None,
    ):
        self.base_strategy = base_strategy
        self.rerank_provider = rerank_provider
        self.config = config
        self.trace_logger = trace_logger or TraceLogger.disabled()

    def search(self, query: str, limit: int) -> list[SearchResult]:
        candidates = self.base_strategy.search(query, max(limit, self.config.candidate_limit))
        rerank_candidates = candidates[: self.config.candidate_limit]
        tail_candidates = candidates[len(rerank_candidates) :]
        if len(rerank_candidates) <= 1:
            return candidates[:limit]
        skip_margin = self._skip_rerank_margin(rerank_candidates)
        if skip_margin is not None:
            self.trace_logger.write(
                "cross_encoder_rerank_skipped",
                {
                    "provider": self.rerank_provider.name,
                    "model": self.rerank_provider.model,
                    "query": query,
                    "reason": "confident_base_top",
                    "margin": skip_margin,
                    "threshold": self.config.skip_when_top_margin_at_least,
                    "candidate_count": len(rerank_candidates),
                    "base_candidate_count": len(candidates),
                    "limit": limit,
                    "top_item_id": rerank_candidates[0].item.id,
                    "top_path": rerank_candidates[0].item.path,
                },
            )
            return candidates[:limit]
        documents = [self._document(candidate) for candidate in rerank_candidates]
        self.trace_logger.write(
            "cross_encoder_rerank_request",
            {
                "provider": self.rerank_provider.name,
                "model": self.rerank_provider.model,
                "query": query,
                "candidate_count": len(rerank_candidates),
                "base_candidate_count": len(candidates),
                "limit": limit,
                "document_chars": sum(len(document) for document in documents),
                **self._document_trace(documents),
            },
        )
        started = perf_counter()
        try:
            scores = self.rerank_provider.rerank(query, documents, min(limit, len(rerank_candidates)))
            duration_ms = (perf_counter() - started) * 1000
            self.trace_logger.write(
                "cross_encoder_rerank_response",
                {
                    "provider": self.rerank_provider.name,
                    "model": self.rerank_provider.model,
                    "query": query,
                    "duration_ms": duration_ms,
                    "scores": [{"index": score.index, "score": score.score} for score in scores],
                },
            )
            return self._reranked(rerank_candidates, tail_candidates, scores, limit)
        except Exception as exc:
            duration_ms = (perf_counter() - started) * 1000
            self.trace_logger.write(
                "cross_encoder_rerank_error",
                {
                    "provider": self.rerank_provider.name,
                    "model": self.rerank_provider.model,
                    "query": query,
                    "duration_ms": duration_ms,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return candidates[:limit]

    def _document(self, result: SearchResult) -> str:
        item = result.item
        parts = [
            f"path: {item.path}",
            f"title: {item.title}",
            f"score: {result.score:.6f}",
            "content:",
            item.content[: self.config.max_document_chars],
        ]
        return "\n".join(parts)

    def _document_trace(self, documents: list[str]) -> dict[str, object]:
        if not self.trace_logger.config.include_prompts:
            return {}
        return {"documents": documents}

    def _reranked(
        self,
        candidates: list[SearchResult],
        tail_candidates: list[SearchResult],
        scores,
        limit: int,
    ) -> list[SearchResult]:
        selected_indices = []
        seen = set()
        for score in scores:
            if score.index < 0 or score.index >= len(candidates) or score.index in seen:
                continue
            selected_indices.append(score.index)
            seen.add(score.index)
        reranked = [candidates[index] for index in selected_indices]
        reranked.extend(candidate for index, candidate in enumerate(candidates) if index not in seen)
        if self._should_preserve_top(candidates, reranked):
            reranked = [
                candidates[0],
                *(candidate for candidate in reranked if candidate.item.id != candidates[0].item.id),
            ]
        reranked.extend(tail_candidates)
        return reranked[:limit]

    def _should_preserve_top(self, candidates: list[SearchResult], reranked: list[SearchResult]) -> bool:
        if not self.config.preserve_top_candidate or not candidates or not reranked:
            return False
        if reranked[0].item.id == candidates[0].item.id:
            return False
        if len(candidates) == 1:
            return True
        margin = candidates[0].score - candidates[1].score
        return margin >= self.config.preserve_top_score_margin

    def _skip_rerank_margin(self, candidates: list[SearchResult]) -> float | None:
        threshold = self.config.skip_when_top_margin_at_least
        if threshold is None or len(candidates) < 2:
            return None
        margin = candidates[0].score - candidates[1].score
        if margin < threshold:
            return None
        return margin

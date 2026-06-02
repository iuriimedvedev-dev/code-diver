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
        if len(candidates) <= 1:
            return candidates[:limit]
        documents = [self._document(candidate) for candidate in candidates]
        self.trace_logger.write(
            "cross_encoder_rerank_request",
            {
                "provider": self.rerank_provider.name,
                "model": self.rerank_provider.model,
                "query": query,
                "candidate_count": len(candidates),
                "limit": limit,
                "document_chars": sum(len(document) for document in documents),
                **self._document_trace(documents),
            },
        )
        started = perf_counter()
        try:
            scores = self.rerank_provider.rerank(query, documents, limit)
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
            return self._reranked(candidates, scores, limit)
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

    def _reranked(self, candidates, scores, limit: int) -> list[SearchResult]:
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

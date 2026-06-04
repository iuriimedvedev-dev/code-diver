from __future__ import annotations

from time import perf_counter, sleep

from ..agent.model_cost_estimator import ModelCostEstimator
from ..config.llm_rerank_config import LlmRerankConfig
from ..domain import SearchResult
from ..generation import GenerationProvider
from ..tracing import TraceLogger
from .llm_rerank_prompt_builder import LlmRerankPromptBuilder
from .llm_rerank_response_parser import LlmRerankResponseParser
from .retrieval_strategy import RetrievalStrategy


class LlmRerankRetrievalStrategy(RetrievalStrategy):
    def __init__(
        self,
        base_strategy: RetrievalStrategy,
        generation_provider: GenerationProvider,
        config: LlmRerankConfig,
        trace_logger: TraceLogger | None = None,
    ):
        self.base_strategy = base_strategy
        self.generation_provider = generation_provider
        self.config = config
        self.trace_logger = trace_logger or TraceLogger.disabled()
        self.prompt_builder = LlmRerankPromptBuilder(config)
        self.response_parser = LlmRerankResponseParser()
        self.cost_estimator = ModelCostEstimator()

    def search(self, query: str, limit: int) -> list[SearchResult]:
        candidates = self.base_strategy.search(query, max(limit, self.config.candidate_limit))
        if len(candidates) <= 1:
            return candidates[:limit]
        rerank_limit = self._rerank_limit(limit)
        prompt = self.prompt_builder.build(query, candidates, rerank_limit)
        self.trace_logger.write(
            "llm_rerank_prompt",
            {
                "provider": self.generation_provider.name,
                "model": self.generation_provider.model,
                "query": query,
                "candidate_count": len(candidates),
                "limit": rerank_limit,
                "final_limit": limit,
                "mode": self.config.mode,
                **self.trace_logger.prompt_payload(prompt),
            },
        )
        attempts = max(1, self.config.retry_attempts)
        for attempt in range(1, attempts + 1):
            started = perf_counter()
            try:
                response = self.generation_provider.generate_json_result(prompt)
                duration_ms = (perf_counter() - started) * 1000
                selected_indices = self.response_parser.parse_indices(response.text, len(candidates))
                cost = self.cost_estimator.estimate(response.model, response.input_tokens, response.output_tokens)
                self.trace_logger.write(
                    "llm_rerank_response",
                    {
                        "provider": self.generation_provider.name,
                        "model": response.model,
                        "query": query,
                        "duration_ms": duration_ms,
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                        "total_tokens": response.total_tokens,
                        "estimated_cost": cost,
                        "selected_indices": selected_indices,
                        "mode": self.config.mode,
                        "attempt": attempt,
                        "response_chars": len(response.text),
                        "response": response.text,
                    },
                )
                return self._reranked(candidates, selected_indices[:rerank_limit], limit)
            except Exception as exc:
                duration_ms = (perf_counter() - started) * 1000
                final_attempt = attempt >= attempts
                self.trace_logger.write(
                    "llm_rerank_error",
                    {
                        "provider": self.generation_provider.name,
                        "model": self.generation_provider.model,
                        "query": query,
                        "duration_ms": duration_ms,
                        "mode": self.config.mode,
                        "attempt": attempt,
                        "max_attempts": attempts,
                        "will_retry": not final_attempt,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                if final_attempt:
                    return candidates[:limit]
                sleep(self._retry_delay_seconds(attempt))

    def _reranked(self, candidates: list[SearchResult], selected_indices: list[int], limit: int) -> list[SearchResult]:
        selected_positions = {index - 1 for index in selected_indices}
        reranked = [candidates[index - 1] for index in selected_indices]
        reranked.extend(
            candidate for index, candidate in enumerate(candidates) if index not in selected_positions
        )
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

    def _rerank_limit(self, limit: int) -> int:
        if self.config.rerank_limit <= 0:
            return limit
        return max(1, min(limit, self.config.rerank_limit))

    def _retry_delay_seconds(self, failed_attempt: int) -> float:
        delay = self.config.retry_base_delay_seconds * (2 ** max(0, failed_attempt - 1))
        return min(delay, self.config.retry_max_delay_seconds)

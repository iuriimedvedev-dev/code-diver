from __future__ import annotations

from time import perf_counter

from ..agent.model_cost_estimator import ModelCostEstimator
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
        candidate_limit: int,
        trace_logger: TraceLogger | None = None,
    ):
        self.base_strategy = base_strategy
        self.generation_provider = generation_provider
        self.candidate_limit = candidate_limit
        self.trace_logger = trace_logger or TraceLogger.disabled()
        self.prompt_builder = LlmRerankPromptBuilder()
        self.response_parser = LlmRerankResponseParser()
        self.cost_estimator = ModelCostEstimator()

    def search(self, query: str, limit: int) -> list[SearchResult]:
        candidates = self.base_strategy.search(query, max(limit, self.candidate_limit))
        if len(candidates) <= 1:
            return candidates[:limit]
        prompt = self.prompt_builder.build(query, candidates, limit)
        self.trace_logger.write(
            "llm_rerank_prompt",
            {
                "provider": self.generation_provider.name,
                "model": self.generation_provider.model,
                "query": query,
                "candidate_count": len(candidates),
                "limit": limit,
                **self.trace_logger.prompt_payload(prompt),
            },
        )
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
                    "response_chars": len(response.text),
                    "response": response.text,
                },
            )
            return self._reranked(candidates, selected_indices, limit)
        except Exception as exc:
            duration_ms = (perf_counter() - started) * 1000
            self.trace_logger.write(
                "llm_rerank_error",
                {
                    "provider": self.generation_provider.name,
                    "model": self.generation_provider.model,
                    "query": query,
                    "duration_ms": duration_ms,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return candidates[:limit]

    def _reranked(self, candidates: list[SearchResult], selected_indices: list[int], limit: int) -> list[SearchResult]:
        selected_positions = {index - 1 for index in selected_indices}
        reranked = [candidates[index - 1] for index in selected_indices]
        reranked.extend(
            candidate for index, candidate in enumerate(candidates) if index not in selected_positions
        )
        return reranked[:limit]

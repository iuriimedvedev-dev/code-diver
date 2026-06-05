from __future__ import annotations

from time import perf_counter, sleep
from typing import Any

from ..agent.model_cost_estimator import ModelCostEstimator
from ..config.llm_rerank_config import LlmRerankConfig
from ..domain import SearchResult
from ..generation import GenerationProvider, GenerationResult
from ..strategies.llm_rerank_prompt_builder import LlmRerankPromptBuilder
from ..strategies.llm_rerank_response_parser import LlmRerankResponseParser


class AnswerCandidateReranker:
    def __init__(self, provider: GenerationProvider, config: LlmRerankConfig):
        self.provider = provider
        self.config = config
        self.prompt_builder = LlmRerankPromptBuilder(config)
        self.response_parser = LlmRerankResponseParser()
        self.cost_estimator = ModelCostEstimator()

    @property
    def candidate_limit(self) -> int:
        return max(1, self.config.candidate_limit)

    def rerank(self, query: str, candidates: list[SearchResult], limit: int) -> tuple[list[SearchResult], dict[str, Any]]:
        rerank_candidates = candidates[: self.candidate_limit]
        if len(rerank_candidates) <= 1:
            return rerank_candidates[:limit], self._empty_payload(query, len(rerank_candidates))
        rerank_limit = self._rerank_limit(limit)
        prompt = self.prompt_builder.build(query, rerank_candidates, rerank_limit)
        attempts = max(1, self.config.retry_attempts)
        last_error: str | None = None
        for attempt in range(1, attempts + 1):
            started = perf_counter()
            try:
                result = self.provider.generate_json_result(prompt)
                duration_ms = (perf_counter() - started) * 1000
                selected_indices = self.response_parser.parse_indices(result.text, len(rerank_candidates))
                ranked = self._reranked(rerank_candidates, selected_indices[:rerank_limit], limit)
                return ranked, self._payload(query, result, duration_ms, selected_indices, len(rerank_candidates), attempt)
            except Exception as exc:
                last_error = str(exc)
                if attempt >= attempts:
                    break
                sleep(self._retry_delay_seconds(attempt))
        payload = self._empty_payload(query, len(rerank_candidates))
        payload["error"] = last_error
        payload["fallback"] = "base_candidate_order"
        return candidates[:limit], payload

    def _reranked(self, candidates: list[SearchResult], selected_indices: list[int], limit: int) -> list[SearchResult]:
        selected_positions = {index - 1 for index in selected_indices}
        reranked = [candidates[index - 1] for index in selected_indices]
        reranked.extend(candidate for index, candidate in enumerate(candidates) if index not in selected_positions)
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

    def _payload(
        self,
        query: str,
        result: GenerationResult,
        duration_ms: float,
        selected_indices: list[int],
        candidate_count: int,
        attempt: int,
    ) -> dict[str, Any]:
        return {
            "enabled": True,
            "provider": self.provider.name,
            "model": result.model,
            "query": query,
            "duration_ms": duration_ms,
            "candidate_count": candidate_count,
            "selected_indices": selected_indices,
            "attempt": attempt,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "total_tokens": result.total_tokens,
            "estimated_cost": self.cost_estimator.estimate(result.model, result.input_tokens, result.output_tokens),
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
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_cost": 0.0,
        }

    def _retry_delay_seconds(self, failed_attempt: int) -> float:
        delay = self.config.retry_base_delay_seconds * (2 ** max(0, failed_attempt - 1))
        return min(delay, self.config.retry_max_delay_seconds)

from __future__ import annotations

from time import perf_counter, sleep

from ..agent.model_cost_estimator import ModelCostEstimator
from ..config.llm_rerank_config import LlmRerankConfig
from ..domain import SearchResult
from ..generation import RERANK_SCHEMA, GenerationProvider
from ..tracing import TraceLogger
from .llm_rerank_prompt_builder import LlmRerankPromptBuilder
from .llm_rerank_response_parser import LlmRerankResponseParser
from .llm_rerank_selection import LlmRerankSelection
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
        # Chunking is a pre-reduction: it shortens the candidate list, then the final stage below
        # runs exactly as it always has. Keeping it out of the main path is deliberate -- the
        # single-shot behaviour has to stay identical for the champion to remain comparable.
        if self._chunking_applies(len(candidates)):
            candidates = self._chunk_survivors(query, candidates)
            if len(candidates) <= 1:
                return candidates[:limit]
        rerank_limit = self._rerank_limit(limit)
        return self._ranked(
            query,
            candidates,
            rerank_limit=rerank_limit,
            limit=limit,
            preserve_top=self.config.preserve_top_candidate,
            stage="final",
        )

    def _chunking_applies(self, candidate_count: int) -> bool:
        chunk_size = self.config.chunk_size
        # A list that already fits in one chunk gains nothing: chunking it would spend the same
        # single call and then a second one to rank the survivors of that call.
        return chunk_size is not None and chunk_size > 0 and candidate_count > chunk_size

    def _chunk_survivors(self, query: str, candidates: list[SearchResult]) -> list[SearchResult]:
        chunk_size = self.config.chunk_size or len(candidates)
        keep = self._chunk_keep()
        survivors: list[SearchResult] = []
        for start in range(0, len(candidates), chunk_size):
            chunk = candidates[start : start + chunk_size]
            # A trailing chunk no longer than `keep` has nothing to select: every member would
            # survive, so the call would be pure cost. Base order carries them through.
            if len(chunk) <= keep:
                survivors.extend(chunk)
                continue
            survivors.extend(
                self._ranked(
                    query,
                    chunk,
                    rerank_limit=keep,
                    limit=keep,
                    # `preserve_top_candidate` compares against the top of the list it is given.
                    # Inside a chunk that top is an artefact of where the split fell, so the
                    # guard belongs to the final stage only.
                    preserve_top=False,
                    stage="chunk",
                )
            )
        return survivors

    def _chunk_keep(self) -> int:
        if self.config.chunk_keep is not None:
            return max(1, self.config.chunk_keep)
        return max(1, self.config.rerank_limit)

    def _ranked(
        self,
        query: str,
        candidates: list[SearchResult],
        rerank_limit: int,
        limit: int,
        preserve_top: bool,
        stage: str,
    ) -> list[SearchResult]:
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
                "stage": stage,
                **self.trace_logger.prompt_payload(prompt),
            },
        )
        attempts = max(1, self.config.retry_attempts)
        for attempt in range(1, attempts + 1):
            started = perf_counter()
            try:
                response = self.generation_provider.generate_json_result(prompt, schema=RERANK_SCHEMA)
                duration_ms = (perf_counter() - started) * 1000
                selections = self.response_parser.parse_selections(response.text, len(candidates))
                selected_indices = [selection.index for selection in selections]
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
                        "selected_candidates": self._selected_candidates(candidates, selections),
                        "mode": self.config.mode,
                        "stage": stage,
                        "attempt": attempt,
                        "response_chars": len(response.text),
                        "response": response.text,
                    },
                )
                return self._reranked(candidates, selected_indices[:rerank_limit], limit, preserve_top)
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
                        "stage": stage,
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

    def _reranked(
        self,
        candidates: list[SearchResult],
        selected_indices: list[int],
        limit: int,
        preserve_top: bool,
    ) -> list[SearchResult]:
        selected_positions = {index - 1 for index in selected_indices}
        reranked = [candidates[index - 1] for index in selected_indices]
        reranked.extend(
            candidate for index, candidate in enumerate(candidates) if index not in selected_positions
        )
        if preserve_top and self._should_preserve_top(candidates, reranked):
            reranked = [
                candidates[0],
                *(candidate for candidate in reranked if candidate.item.id != candidates[0].item.id),
            ]
        return reranked[:limit]

    def _should_preserve_top(self, candidates: list[SearchResult], reranked: list[SearchResult]) -> bool:
        if not candidates or not reranked:
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

    def _selected_candidates(
        self,
        candidates: list[SearchResult],
        selections: list[LlmRerankSelection],
    ) -> list[dict[str, object]]:
        selected = []
        for rank, selection in enumerate(selections, start=1):
            position = selection.index - 1
            if position < 0 or position >= len(candidates):
                continue
            candidate = candidates[position]
            selected.append(
                {
                    "rerank_rank": rank,
                    "index": selection.index,
                    "confidence": selection.confidence,
                    "reason": selection.reason,
                    "id": candidate.item.id,
                    "path": candidate.item.path,
                    "base_score": candidate.score,
                }
            )
        return selected

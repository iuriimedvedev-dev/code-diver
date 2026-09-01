from __future__ import annotations

import logging
import math
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from ..config.cross_encoder_rerank_config import CrossEncoderRerankConfig
from ..domain import SearchResult
from ..reranking import RerankProvider, RerankScore
from ..reranking.cross_encoder_document_builder import build_cross_encoder_document
from ..tracing import TraceLogger
from .retrieval_strategy import RetrievalStrategy

logger = logging.getLogger(__name__)

# H-82: the llama.cpp rerank endpoint only exposes the final sigmoid probability, not the raw
# model logit, so ranking "by raw logits" inverts the sigmoid. The clamp keeps saturated
# probabilities (0.0 / 1.0 after float rounding) finite.
_LOGIT_CLAMP_EPSILON = 1e-7


def _logit(probability: float) -> float:
    clamped = min(max(probability, _LOGIT_CLAMP_EPSILON), 1.0 - _LOGIT_CLAMP_EPSILON)
    return math.log(clamped / (1.0 - clamped))


class CrossEncoderRerankRetrievalStrategy(RetrievalStrategy):
    def __init__(
        self,
        base_strategy: RetrievalStrategy,
        rerank_provider: RerankProvider,
        config: CrossEncoderRerankConfig,
        trace_logger: TraceLogger | None = None,
        repository_root: Path | None = None,
    ):
        self.base_strategy = base_strategy
        self.rerank_provider = rerank_provider
        self.config = config
        self.trace_logger = trace_logger or TraceLogger.disabled()
        self.repository_root = repository_root
        # A rerank failure degrades silently to base order. Counted so a run can report how
        # many of its results were never actually reranked.
        self.rerank_failure_count = 0

    def search(self, query: str, limit: int) -> list[SearchResult]:
        fetch_limit = max(limit, self.config.candidate_limit)
        if self.config.widen_when_uncertain_enabled:
            fetch_limit = max(fetch_limit, self.config.widen_candidate_limit)
        candidates = self.base_strategy.search(query, fetch_limit)
        effective_candidate_limit = self._effective_candidate_limit(query, candidates)
        rerank_candidates = candidates[:effective_candidate_limit]
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
            scores = self.rerank_provider.rerank(query, documents, self._top_n(limit, rerank_candidates))
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
            scores = self._with_second_pass(query, rerank_candidates, scores)
            scores = self._ranking_adjusted(rerank_candidates, scores)
            return self._reranked(rerank_candidates, tail_candidates, scores, limit)
        except Exception as exc:
            duration_ms = (perf_counter() - started) * 1000
            self.rerank_failure_count += 1
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
            # Falling back to base order is a silent quality change: the caller gets results
            # that look reranked but are not. Trace is usually disabled, so warn unconditionally
            # -- otherwise an unreranked run is indistinguishable from a reranked one.
            logger.warning(
                "cross-encoder rerank failed (%s of %s candidates, failure #%d), "
                "falling back to base order: %s: %s",
                len(rerank_candidates),
                len(candidates),
                self.rerank_failure_count,
                type(exc).__name__,
                exc,
            )
            return candidates[:limit]

    def _document(self, result: SearchResult) -> str:
        return build_cross_encoder_document(result, self.config, self.repository_root)

    def _top_n(self, limit: int, rerank_candidates: list[SearchResult]) -> int:
        """How many scored indices to request from the provider.

        The historical request asks only for the final cut (min(limit, candidates)). H-82 and
        H-83 both need a score for every candidate: the tie at the cut boundary sits just past
        rank `limit`, and the second pass selects its retry set from the full score list. With
        every flag off the historical top_n is reproduced exactly.
        """
        needs_full_scores = (
            self.config.rank_by_raw_logits
            or self.config.tie_break_by_fused_score
            or self.config.second_pass_enabled
        )
        if needs_full_scores:
            return len(rerank_candidates)
        return min(limit, len(rerank_candidates))

    def _with_second_pass(
        self,
        query: str,
        candidates: list[SearchResult],
        scores: list[RerankScore],
    ) -> list[RerankScore]:
        """H-83: rescore first-pass losers with a larger document budget, keep max(first, second).

        The first pass truncates documents at `max_document_chars` (850 in the champion), which
        cuts the evidence out of large files and leaves the correct candidate near zero
        (WHERE-79: FoldingModelImpl 0.088, PluginManagerCore 0.194). Raising the window for ALL
        candidates was measured to be worse (more convincing distractors at 1600 chars / 80
        candidates), so only candidates scoring below `second_pass_score_floor` are rebuilt at
        `second_pass_max_document_chars` and rescored; high scorers keep their first-pass score
        untouched. Cost: one extra provider call whose batch is the sub-floor subset -- often
        most of the window on hard queries -- so `second_pass_candidate_cap` can bound it.
        A second-pass failure falls back to the first-pass scores instead of the base order.
        """
        if not self.config.second_pass_enabled:
            return scores
        floor = self.config.second_pass_score_floor
        retry_scores = [
            score for score in scores if 0 <= score.index < len(candidates) and score.score < floor
        ]
        cap = self.config.second_pass_candidate_cap
        if cap > 0 and len(retry_scores) > cap:
            # The base fusion already ranked the window; truncation victims worth rescuing are
            # the ones it trusted most, so the cap keeps the best base ranks (lowest indices).
            retry_scores = sorted(retry_scores, key=lambda score: score.index)[:cap]
        if not retry_scores:
            return scores
        expanded_config = replace(self.config, max_document_chars=self.config.second_pass_max_document_chars)
        retry_indices = [score.index for score in retry_scores]
        documents = [
            build_cross_encoder_document(candidates[index], expanded_config, self.repository_root)
            for index in retry_indices
        ]
        started = perf_counter()
        try:
            second_scores = self.rerank_provider.rerank(query, documents, len(documents))
        except Exception as exc:
            duration_ms = (perf_counter() - started) * 1000
            self.trace_logger.write(
                "cross_encoder_rerank_second_pass_error",
                {
                    "provider": self.rerank_provider.name,
                    "model": self.rerank_provider.model,
                    "query": query,
                    "duration_ms": duration_ms,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            logger.warning(
                "cross-encoder second pass failed (%s candidates), keeping first-pass scores: %s: %s",
                len(documents),
                type(exc).__name__,
                exc,
            )
            return scores
        duration_ms = (perf_counter() - started) * 1000
        best_second: dict[int, float] = {}
        for score in second_scores:
            if score.index < 0 or score.index >= len(retry_indices):
                continue
            original_index = retry_indices[score.index]
            known = best_second.get(original_index)
            if known is None or score.score > known:
                best_second[original_index] = score.score
        merged = [
            RerankScore(index=score.index, score=max(score.score, best_second[score.index]))
            if score.index in best_second
            else score
            for score in scores
        ]
        merged.sort(key=lambda score: score.score, reverse=True)
        self.trace_logger.write(
            "cross_encoder_rerank_second_pass",
            {
                "provider": self.rerank_provider.name,
                "model": self.rerank_provider.model,
                "query": query,
                "duration_ms": duration_ms,
                "score_floor": floor,
                "max_document_chars": self.config.second_pass_max_document_chars,
                "candidate_count": len(retry_indices),
                "improved_count": sum(
                    1
                    for score in scores
                    if score.index in best_second and best_second[score.index] > score.score
                ),
                "scores": [
                    {"index": index, "score": best_second[index]} for index in sorted(best_second)
                ],
            },
        )
        return merged

    def _ranking_adjusted(
        self,
        candidates: list[SearchResult],
        scores: list[RerankScore],
    ) -> list[RerankScore]:
        """H-82: undo sigmoid squashing and break near-ties deterministically.

        The provider only returns sigmoid probabilities, so at the saturated top the ranking
        degenerates into float-precision ties broken by arbitrary insertion order (WHERE-79:
        SafeDeleteProcessor lost rank 12 vs cut@10 at 0.9979 vs 0.9979). `rank_by_raw_logits`
        maps scores through the inverse sigmoid -- monotone, so genuinely distinct probabilities
        keep their order, but the clamp separates values only saturation made equal-looking.
        `tie_break_by_fused_score` then orders candidates whose CE scores are within
        `tie_break_epsilon` of each other by the incoming fused base score, so ties fall back to
        the graph-file stage's opinion instead of arbitrary order. Both flags off returns the
        scores unchanged.
        """
        if not self.config.rank_by_raw_logits and not self.config.tie_break_by_fused_score:
            return scores
        adjusted = list(scores)
        if self.config.rank_by_raw_logits:
            adjusted = [RerankScore(index=score.index, score=_logit(score.score)) for score in adjusted]
        adjusted.sort(key=lambda score: score.score, reverse=True)
        if self.config.tie_break_by_fused_score:
            adjusted = self._fused_tie_broken(candidates, adjusted)
        return adjusted

    def _fused_tie_broken(
        self,
        candidates: list[SearchResult],
        scores: list[RerankScore],
    ) -> list[RerankScore]:
        """Reorder runs of near-equal CE scores by the fused base score, descending.

        Expects `scores` sorted descending. Adjacent scores within `tie_break_epsilon` chain
        into one tie group, so a saturated plateau is treated as a single tie.
        """
        if len(scores) < 2:
            return list(scores)
        epsilon = self.config.tie_break_epsilon
        result: list[RerankScore] = []
        group = [scores[0]]
        for score in scores[1:]:
            if abs(group[-1].score - score.score) <= epsilon:
                group.append(score)
                continue
            result.extend(self._fused_order(candidates, group))
            group = [score]
        result.extend(self._fused_order(candidates, group))
        return result

    def _fused_order(self, candidates: list[SearchResult], group: list[RerankScore]) -> list[RerankScore]:
        if len(group) < 2:
            return group

        def fused_score(score: RerankScore) -> float:
            if 0 <= score.index < len(candidates):
                return candidates[score.index].score
            return float("-inf")

        return sorted(group, key=fused_score, reverse=True)

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
        preserved = self._preserved_prefix_size(candidates, reranked)
        if preserved:
            prefix = candidates[:preserved]
            prefix_ids = {candidate.item.id for candidate in prefix}
            reranked = [
                *prefix,
                *(candidate for candidate in reranked if candidate.item.id not in prefix_ids),
            ]
        reranked.extend(tail_candidates)
        return reranked[:limit]

    def _preserved_prefix_size(self, candidates: list[SearchResult], reranked: list[SearchResult]) -> int:
        """How many leading base candidates keep their base order in front of the rerank.

        H-79: `preserve_top_candidate` only ever protected base rank 1, but the cross-encoder
        also demotes correct files sitting at base rank 2-3 (measured on WHERE-79:
        where-go-to-declaration-navigation 7 -> 12, where-code-folding 9 -> 28). `preserve_top_depth`
        widens the protected prefix. It defaults to 1, which reproduces the previous top-1-only
        behaviour exactly, so the option is off unless a config asks for it.

        The margin gate keeps its meaning: it compares the last protected candidate with the
        first unprotected one, i.e. it only trusts the base order when the base ranking itself
        is confident at the cut point.
        """
        if not self.config.preserve_top_candidate or not candidates or not reranked:
            return 0
        depth = min(max(self.config.preserve_top_depth, 1), len(candidates))
        base_prefix = [candidate.item.id for candidate in candidates[:depth]]
        if [candidate.item.id for candidate in reranked[:depth]] == base_prefix:
            return 0
        if len(candidates) <= depth:
            return depth
        margin = candidates[depth - 1].score - candidates[depth].score
        return depth if margin >= self.config.preserve_top_score_margin else 0

    def _effective_candidate_limit(self, query: str, candidates: list[SearchResult]) -> int:
        """Widen the reranked window for queries where the base fusion ranking is "flat".

        H49 / H-B: `candidate_limit` (typically 34) is a hard cutoff on the base fusion order --
        anything below it is appended untouched and the cross-encoder never sees it, no matter
        how good it is semantically. On realistic developer questions, weak path/symbol/lexical
        signal often leaves the base ranking with no confident leader near the top, which
        correlates with the correct file being buried past the cutoff (Finding: 5/6 sampled
        zero-recall where-cases had this shape). This gate looks only at the base fusion scores
        already returned by `base_strategy.search` (no extra cost) and widens the window when the
        margin between rank 1 and rank `widen_margin_check_rank` is smaller than
        `widen_score_margin_below`, i.e. the base ranking has no clear winner. Mechanical queries,
        which have a unique discriminating path/symbol hit, keep a wide top-1 margin and are left
        at the normal `candidate_limit`.
        """
        base_limit = self.config.candidate_limit
        if not self.config.widen_when_uncertain_enabled:
            return base_limit
        check_rank = self.config.widen_margin_check_rank
        if check_rank < 2 or len(candidates) < check_rank:
            return base_limit
        margin = candidates[0].score - candidates[check_rank - 1].score
        if margin >= self.config.widen_score_margin_below:
            return base_limit
        widened_limit = min(self.config.widen_candidate_limit, len(candidates))
        self.trace_logger.write(
            "cross_encoder_rerank_widened",
            {
                "provider": self.rerank_provider.name,
                "model": self.rerank_provider.model,
                "query": query,
                "reason": "flat_base_ranking",
                "margin": margin,
                "threshold": self.config.widen_score_margin_below,
                "check_rank": check_rank,
                "base_candidate_limit": base_limit,
                "widened_candidate_limit": widened_limit,
            },
        )
        return widened_limit

    def _skip_rerank_margin(self, candidates: list[SearchResult]) -> float | None:
        threshold = self.config.skip_when_top_margin_at_least
        if threshold is None or len(candidates) < 2:
            return None
        margin = candidates[0].score - candidates[1].score
        if margin < threshold:
            return None
        return margin

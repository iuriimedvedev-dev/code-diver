from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from ..config.cross_encoder_rerank_config import CrossEncoderRerankConfig
from ..domain import SearchResult
from ..ranking import CeMetaCandidate, CeMetaFeatureExtractor, CeMetaFeatureRow
from ..reranking import HubPriorMode, HubPriorScorer, RerankProvider, RerankScore
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
    # H-91: The LightGBM Booster is eagerly loaded at construction time (before any httpx
    # client is created) and stored on the class, so all instances share the same Booster.
    # This avoids the segfault caused by LightGBM's C++ global initialiser conflicting
    # with an active httpx event loop.
    _ce_meta_ranker_booster: Any | None = None

    def __init__(
        self,
        base_strategy: RetrievalStrategy,
        rerank_provider: RerankProvider,
        config: CrossEncoderRerankConfig,
        trace_logger: TraceLogger | None = None,
        repository_root: Path | None = None,
        hub_prior_scorer: HubPriorScorer | None = None,
        ce_meta_feature_sink: Callable[[str, list[CeMetaFeatureRow]], None] | None = None,
    ):
        self.base_strategy = base_strategy
        self.rerank_provider = rerank_provider
        self.config = config
        self.trace_logger = trace_logger or TraceLogger.disabled()
        self.repository_root = repository_root
        # H-87: only consulted when config.hub_prior_enabled. Without an injected scorer the
        # default has no fan-in lookup, so only the filename-role prior can contribute.
        self.hub_prior_scorer = hub_prior_scorer or HubPriorScorer()
        # H-91: CE-stage meta-ranker feature exporter.
        self.ce_meta_feature_sink = ce_meta_feature_sink
        self.ce_meta_feature_extractor = CeMetaFeatureExtractor(self.hub_prior_scorer)
        # H-91: CE-stage meta-ranker (LightGBM). Loaded eagerly at construction time
        # because LightGBM's C++ initialisation can segfault when called from inside
        # an httpx event loop (the evaluator's thread pool + async HTTP client create
        # a thread state that conflicts with the C extension's global initialiser).
        self._ce_meta_ranker: Any = None
        self._ce_meta_ranker_loaded = False
        self._ce_meta_ranker_eagerly_loaded(config)
        self._ce_meta_ranker_loaded = False
        # A rerank failure degrades silently to base order. Counted so a run can report how
        # many of its results were never actually reranked.
        self.rerank_failure_count = 0

    @staticmethod
    def _ce_meta_ranker_eagerly_loaded(config: CrossEncoderRerankConfig) -> None:
        """Pre-load the LightGBM Booster at construction time.

        The Booster is constructed here, before any httpx client is created, to avoid
        the segfault caused by LightGBM's C++ global initialiser conflicting with an
        active httpx event loop.
        """
        if not config.ce_meta_ranker_enabled:
            return
        if not config.ce_meta_model_path:
            logger.warning(
                "CE meta-ranker enabled but ce_meta_model_path is empty; falling back to hub prior."
            )
            return
        model_path = Path(config.ce_meta_model_path)
        if not model_path.exists():
            logger.warning(
                "CE meta-ranker model not found at %s; falling back to hub prior.",
                model_path,
            )
            return
        # Resolve the actual model file: if the path is a JSON manifest, read
        # the ``model_file`` field and resolve relative to the manifest directory.
        resolved = model_path
        if model_path.suffix == ".json":
            import json
            try:
                manifest = json.loads(model_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning(
                    "CE meta-ranker manifest %s cannot be read: %s; falling back to hub prior.",
                    model_path,
                    exc,
                )
                return
            model_file = manifest.get("model_file", "")
            if model_file:
                candidate = model_path.parent / model_file
                if candidate.exists():
                    resolved = candidate
                else:
                    logger.warning(
                        "CE meta-ranker manifest %s references model_file=%r which does not "
                        "exist at %s; falling back to hub prior.",
                        model_path,
                        model_file,
                        candidate,
                    )
                    return
            else:
                logger.warning(
                    "CE meta-ranker manifest %s has no model_file field; falling back to hub prior.",
                    model_path,
                )
                return
        try:
            import lightgbm
            booster = lightgbm.Booster(model_file=str(resolved))
            CrossEncoderRerankRetrievalStrategy._ce_meta_ranker_booster = booster
            logger.info(
                "CE meta-ranker Booster loaded eagerly: %s (%d trees)",
                resolved,
                booster.num_trees(),
            )
        except Exception as exc:
            logger.warning(
                "CE meta-ranker model %s could not be loaded: %s; falling back to hub prior.",
                resolved,
                exc,
            )

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
                "document_lengths": [len(doc) for doc in documents],
                "candidates": [
                    {"index": index, "path": candidate.item.path, "base_score": candidate.score}
                    for index, candidate in enumerate(rerank_candidates)
                ],
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
            # H-91: when the CE-stage meta-ranker is enabled, the learned model score
            # replaces the hub_prior additive formula. Hub prior is still available as a
            # fallback when the model is missing or fails.
            if self.config.ce_meta_ranker_enabled:
                scores = self._ce_meta_ranker_adjusted(query, rerank_candidates, scores)
            else:
                scores = self._hub_prior_adjusted(query, rerank_candidates, scores)
            # H-91: CE-stage meta-ranker feature export. Must happen after all adjustments so
            # the exported feature rows reflect the final state the meta-ranker will see.
            if self.ce_meta_feature_sink is not None:
                self._export_ce_meta_features(query, rerank_candidates, scores)
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
            or self.config.hub_prior_enabled
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

    def _hub_prior_adjusted(
        self,
        query: str,
        candidates: list[SearchResult],
        scores: list[RerankScore],
    ) -> list[RerankScore]:
        """H-87: fold the file-side hub prior into the final CE ordering.

        WHERE-style queries target hub files (Processor/ManagerImpl/ServiceImpl), but at the
        saturated CE top the hub and its sibling peripherals (Handler/Dialog/Action, .xml/.md)
        sit within ~0.015 of each other and the arbitrary order pushes the hub past the cut.
        `additive` ranks by ce_score + prior everywhere. `band` keeps clear CE wins intact:
        adjacent scores within `hub_prior_band_width` chain into one band (same grouping as
        the H-82 tie-break) and only inside a band does ce_score + prior decide. Off returns
        the scores unchanged. `SearchResult.score` stays the base score either way.
        """
        if not self.config.hub_prior_enabled or not scores:
            return scores

        # Pin the head if requested. The incoming scores are already ordered by CE (including
        # H-82 logit conversion and tie-breaking).
        protect_top = self.config.hub_prior_protect_top
        # H-90: dynamic protect_top based on CE margin. When the gap between top-1 and top-4
        # is >= hub_prior_protect_margin, the CE is confident enough to protect only 1 instead
        # of the configured protect_top. 0.0 = off, use fixed protect_top.
        if self.config.hub_prior_protect_margin > 0 and len(scores) >= 4:
            gap = scores[0].score - scores[3].score
            if gap >= self.config.hub_prior_protect_margin:
                protect_top = 1
        if protect_top > 0:
            head = scores[:protect_top]
            tail = scores[protect_top:]
        else:
            head = []
            tail = scores

        if not tail:
            return scores

        mode = HubPriorMode(self.config.hub_prior_mode)
        priors = self.hub_prior_scorer.priors(
            (candidates[score.index].item.path for score in scores if 0 <= score.index < len(candidates)),
            role_weight=self.config.hub_prior_role_weight,
            fanin_weight=self.config.hub_prior_fanin_weight,
        )

        def prior_of(score: RerankScore) -> float:
            if 0 <= score.index < len(candidates):
                return priors.get(candidates[score.index].item.path, 0.0)
            return 0.0

        def prior_adjusted(group: list[RerankScore]) -> list[RerankScore]:
            return sorted(group, key=lambda score: score.score + prior_of(score), reverse=True)

        if mode is HubPriorMode.ADDITIVE:
            # Stable sort: exact ties keep whatever order the earlier stages (H-82) settled on.
            adjusted_tail = prior_adjusted(list(tail))
        else:
            ordered_tail = sorted(tail, key=lambda score: score.score, reverse=True)
            adjusted_tail = self._banded(ordered_tail, self.config.hub_prior_band_width, prior_adjusted)

        adjusted = head + adjusted_tail
        if self.trace_logger.config.enabled:
            self.trace_logger.write(
                "cross_encoder_hub_prior",
                {
                    "provider": self.rerank_provider.name,
                    "model": self.rerank_provider.model,
                    "query": query,
                    "mode": mode.value,
                    "role_weight": self.config.hub_prior_role_weight,
                    "fanin_weight": self.config.hub_prior_fanin_weight,
                    "band_width": self.config.hub_prior_band_width,
                    "protect_top": protect_top,
                    "candidates": [
                        {
                            "index": score.index,
                            "path": candidates[score.index].item.path,
                            "ce_score": score.score,
                            "prior": prior_of(score),
                        }
                        for score in adjusted
                        if 0 <= score.index < len(candidates)
                    ],
                },
            )
        return adjusted

    def _export_ce_meta_features(
        self,
        query: str,
        candidates: list[SearchResult],
        scores: list[RerankScore],
    ) -> None:
        """H-91: build CE-stage feature rows and push them into the feature sink."""
        if self.ce_meta_feature_sink is None:
            return
        # Build a score-by-index map for O(1) lookup.
        score_by_index = {score.index: score for score in scores}
        meta_candidates = [
            CeMetaCandidate(
                item_id=candidates[score.index].item.id,
                path=candidates[score.index].item.path,
                ce_score=score.score,
                ce_rank=rank,
                base_fused_score=candidates[score.index].score,
                base_fused_rank=rank,
            )
            for rank, score in enumerate(scores)
            if 0 <= score.index < len(candidates)
        ]
        rows = self.ce_meta_feature_extractor.extract(query, meta_candidates)
        self.ce_meta_feature_sink(query, rows)

    def _ce_meta_ranker_load(self) -> None:
        """Use the eagerly loaded LightGBM Booster."""
        if self._ce_meta_ranker_loaded:
            return
        self._ce_meta_ranker_loaded = True
        booster = type(self)._ce_meta_ranker_booster
        if booster is None:
            logger.warning(
                "CE meta-ranker enabled but no Booster was loaded at construction time; "
                "falling back to hub prior."
            )
            return
        self._ce_meta_ranker = booster

    def _ce_meta_ranker_adjusted(
        self,
        query: str,
        candidates: list[SearchResult],
        scores: list[RerankScore],
    ) -> list[RerankScore]:
        """H-91: rank CE candidates by the learned meta-ranker score.

        Builds CE-stage feature rows, predicts a score for each candidate with the
        LightGBM model, and replaces the priority order. When the model is unavailable
        or fails, falls back to hub_prior_adjusted.
        """
        self._ce_meta_ranker_load()
        if self._ce_meta_ranker is None:
            return self._hub_prior_adjusted(query, candidates, scores)

        # Build meta-candidates in the same order as the scores.
        meta_candidates = [
            CeMetaCandidate(
                item_id=candidates[score.index].item.id,
                path=candidates[score.index].item.path,
                ce_score=score.score,
                ce_rank=rank,
                base_fused_score=candidates[score.index].score,
                base_fused_rank=rank,
            )
            for rank, score in enumerate(scores)
            if 0 <= score.index < len(candidates)
        ]
        rows = self.ce_meta_feature_extractor.extract(query, meta_candidates)
        if not rows:
            return scores

        try:
            feature_matrix = [list(row.features) for row in rows]
            predicted = self._ce_meta_ranker.predict(feature_matrix)
        except Exception as exc:
            logger.warning("CE meta-ranker predict failed: %s; falling back to hub prior.", exc)
            return self._hub_prior_adjusted(query, candidates, scores)

        # Re-rank by predicted score, descending.
        indexed = list(enumerate(predicted))
        ranked = sorted(indexed, key=lambda entry: entry[1], reverse=True)
        result = [scores[index] for index, _ in ranked]

        if self.trace_logger.config.enabled:
            self.trace_logger.write(
                "cross_encoder_ce_meta_ranker",
                {
                    "provider": self.rerank_provider.name,
                    "model": self.rerank_provider.model,
                    "query": query,
                    "ce_meta_model": self.config.ce_meta_model_path,
                    "candidates": [
                        {
                            "index": scores[ranked_index].index,
                            "path": candidates[scores[ranked_index].index].item.path,
                            "ce_score": scores[ranked_index].score,
                            "meta_score": float(predicted[ranked_index]),
                        }
                        for ranked_index, (orig_index, _) in enumerate(ranked)
                        if 0 <= scores[ranked_index].index < len(candidates)
                    ],
                },
            )
        return result

    @staticmethod
    def _banded(
        scores: list[RerankScore],
        band_width: float,
        reorder: Callable[[list[RerankScore]], list[RerankScore]],
    ) -> list[RerankScore]:
        """Apply `reorder` inside each run of adjacent scores no further than `band_width` apart.

        Expects `scores` sorted descending. Mirrors `_fused_tie_broken`: adjacent near-equal
        scores chain into one band, so a saturated plateau is one band while a clear gap is
        never crossed.
        """
        if len(scores) < 2:
            return list(scores)
        result: list[RerankScore] = []
        band = [scores[0]]
        for score in scores[1:]:
            if abs(band[-1].score - score.score) <= band_width:
                band.append(score)
                continue
            result.extend(reorder(band))
            band = [score]
        result.extend(reorder(band))
        return result

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

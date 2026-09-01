from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .ltr_feature_row import LTR_FEATURE_NAMES, LtrFeatureRow

_TEST_PATH_MARKERS = ("/test/", "/tests/", "/testdata/", "test/", "tests/")


@dataclass(frozen=True, slots=True)
class LtrCandidate:
    """The raw per-file signals available where the base ordering is decided."""

    item_id: str
    path: str
    vector_score: float = 0.0
    lexical_score: float = 0.0
    path_score: float = 0.0
    symbol_score: float = 0.0
    graph_score: float = 0.0
    fused_score: float = 0.0


class LtrFeatureExtractor:
    """Turns ranked candidates into fixed-width feature rows.

    Pure and deterministic: the same candidate list and query always produce the same
    numbers, which is what makes an exported training set replayable and what the
    inference path relies on to match the training distribution.
    """

    def extract(self, query_term_count: int, candidates: Sequence[LtrCandidate]) -> list[LtrFeatureRow]:
        if not candidates:
            return []
        top_score = max(candidate.fused_score for candidate in candidates)
        rows = [
            LtrFeatureRow(
                item_id=candidate.item_id,
                path=candidate.path,
                features=self._features(query_term_count, candidate, rank, top_score),
            )
            for rank, candidate in enumerate(candidates, start=1)
        ]
        return rows

    def _features(
        self,
        query_term_count: int,
        candidate: LtrCandidate,
        rank: int,
        top_score: float,
    ) -> tuple[float, ...]:
        signals = (
            candidate.vector_score,
            candidate.lexical_score,
            candidate.path_score,
            candidate.symbol_score,
            candidate.graph_score,
        )
        features = (
            *signals,
            candidate.fused_score,
            top_score - candidate.fused_score,
            1.0 / rank,
            float(sum(1 for signal in signals if signal > 0)),
            float(candidate.path.count("/")),
            float(len(candidate.path.rsplit("/", 1)[-1])),
            1.0 if self._is_test_path(candidate.path) else 0.0,
            float(query_term_count),
        )
        if len(features) != len(LTR_FEATURE_NAMES):
            raise ValueError(
                f"LTR feature vector width {len(features)} does not match "
                f"{len(LTR_FEATURE_NAMES)} declared feature names."
            )
        return features

    def _is_test_path(self, path: str) -> bool:
        lowered = path.lower()
        return any(marker in lowered for marker in _TEST_PATH_MARKERS)

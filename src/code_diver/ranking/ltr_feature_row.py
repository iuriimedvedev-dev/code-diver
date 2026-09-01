from __future__ import annotations

from dataclasses import dataclass

# The feature order is part of the model artifact contract: a trained model is only
# usable with the exact list it was trained on. `ltr_ranker_model` refuses an artifact
# whose manifest disagrees with this tuple instead of silently scoring shuffled inputs.
LTR_FEATURE_NAMES: tuple[str, ...] = (
    "vector_score",
    "lexical_score",
    "path_score",
    "symbol_score",
    "graph_score",
    "fused_score",
    "fused_score_gap_to_top",
    "base_rank_reciprocal",
    "signal_count",
    "path_depth",
    "path_name_length",
    "is_test_path",
    "query_term_count",
)


@dataclass(frozen=True, slots=True)
class LtrFeatureRow:
    """One (query, candidate) row: the features the ranker sees for a single file."""

    item_id: str
    path: str
    features: tuple[float, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "path": self.path,
            "features": list(self.features),
        }

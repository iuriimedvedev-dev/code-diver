from __future__ import annotations

from dataclasses import dataclass

# The feature order is part of the model artifact contract: a trained model is only
# usable with the exact list it was trained on.
CE_META_FEATURE_NAMES: tuple[str, ...] = (
    "ce_score",
    "ce_score_rank",
    "fan_in_prior",
    "role_prior",
    "base_fused_score",
    "base_fused_rank",
    "lexical_overlap",
    "dir_depth",
    "path_name_length",
    "is_test_path",
    "file_ext_java",
    "file_ext_kt",
    "file_ext_xml",
    "file_ext_md",
    "query_term_count",
    "dir_proximity",
)


@dataclass(frozen=True, slots=True)
class CeMetaFeatureRow:
    """One (query, candidate) row: the features the CE-stage meta-ranker sees for a single file."""

    item_id: str
    path: str
    features: tuple[float, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "path": self.path,
            "features": list(self.features),
        }
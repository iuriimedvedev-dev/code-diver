from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_diver.config import GraphFileSearchConfig
from code_diver.config.config_loader import ConfigLoader
from code_diver.domain import CodeItem, SearchResult
from code_diver.graph import CodeGraph, CodeGraphStore
from code_diver.ranking import (
    LTR_FEATURE_NAMES,
    LtrFeatureCollector,
    LtrFeatureExtractor,
    LtrFeatureSinkAttacher,
    LtrQuerySplitter,
    LtrRankerModel,
)
from code_diver.ranking.ltr_feature_extractor import LtrCandidate
from code_diver.strategies import GraphFileRetrievalStrategy, RetrievalStrategy

pytestmark = pytest.mark.unit


class FakeRetrievalStrategy(RetrievalStrategy):
    def __init__(self, results: list[SearchResult]):
        self.results = results

    def search(self, query: str, limit: int) -> list[SearchResult]:
        return self.results[:limit]


def test_feature_extraction_is_deterministic_and_matches_the_manifest_width() -> None:
    candidates = [
        LtrCandidate("a", "src/users/service.py", 0.9, 0.4, 0.2, 0.1, 0.0, 0.61),
        LtrCandidate("b", "src/tests/test_users.py", 0.3, 0.0, 0.0, 0.0, 0.5, 0.22),
    ]
    extractor = LtrFeatureExtractor()

    first = extractor.extract(3, candidates)
    second = extractor.extract(3, candidates)

    assert [row.features for row in first] == [row.features for row in second]
    assert all(len(row.features) == len(LTR_FEATURE_NAMES) for row in first)


def test_feature_extraction_reports_rank_and_gap_relative_to_the_top_candidate() -> None:
    rows = LtrFeatureExtractor().extract(
        2,
        [
            LtrCandidate("a", "src/a.py", fused_score=0.8),
            LtrCandidate("b", "src/b.py", fused_score=0.5),
        ],
    )
    features = dict(zip(LTR_FEATURE_NAMES, rows[1].features, strict=True))

    assert features["base_rank_reciprocal"] == pytest.approx(0.5)
    assert features["fused_score_gap_to_top"] == pytest.approx(0.3)


def test_test_paths_are_flagged_so_the_model_can_learn_to_demote_them() -> None:
    rows = LtrFeatureExtractor().extract(
        1,
        [
            LtrCandidate("a", "src/main/users.py"),
            LtrCandidate("b", "src/test/users_test.py"),
        ],
    )
    index = LTR_FEATURE_NAMES.index("is_test_path")

    assert rows[0].features[index] == 0.0
    assert rows[1].features[index] == 1.0


def test_query_split_never_puts_a_query_on_both_sides() -> None:
    query_ids = [f"case-{index}" for index in range(200)]

    split = LtrQuerySplitter().split(query_ids, test_fraction=0.5, seed=7)

    assert not split.overlap()
    assert set(split.train_query_ids) | set(split.test_query_ids) == set(query_ids)
    assert split.train_query_ids and split.test_query_ids


def test_query_split_is_stable_for_the_same_seed_and_changes_with_the_seed() -> None:
    query_ids = [f"case-{index}" for index in range(200)]
    splitter = LtrQuerySplitter()

    assert splitter.split(query_ids, seed=1) == splitter.split(query_ids, seed=1)
    assert splitter.split(query_ids, seed=1) != splitter.split(query_ids, seed=2)


def test_query_split_ignores_duplicate_query_ids() -> None:
    split = LtrQuerySplitter().split(["a", "a", "b", "b", "c"], test_fraction=0.5, seed=0)

    assert sorted([*split.train_query_ids, *split.test_query_ids]) == ["a", "b", "c"]


def test_query_split_rejects_a_degenerate_fraction() -> None:
    with pytest.raises(ValueError):
        LtrQuerySplitter().split(["a", "b"], test_fraction=0.0)


def test_config_without_the_flag_leaves_the_learned_ranker_off(tmp_path: Path) -> None:
    config_path = tmp_path / "code-diver.yml"
    config_path.write_text("graph_file_search:\n  seed_limit: 150\n", encoding="utf-8")

    config = ConfigLoader().load(config_path)

    assert config.graph_file_search.ltr_ranker_enabled is False
    assert config.graph_file_search.ltr_model_path is None


def test_config_can_turn_the_learned_ranker_on(tmp_path: Path) -> None:
    config_path = tmp_path / "code-diver.yml"
    config_path.write_text(
        "graph_file_search:\n  ltr_ranker_enabled: true\n  ltr_model_path: artifacts/ranker.json\n",
        encoding="utf-8",
    )

    config = ConfigLoader().load(config_path)

    assert config.graph_file_search.ltr_ranker_enabled is True
    assert config.graph_file_search.ltr_model_path == "artifacts/ranker.json"


def test_missing_artifact_loads_as_no_model(tmp_path: Path) -> None:
    assert LtrRankerModel.load(None) is None
    assert LtrRankerModel.load(tmp_path / "absent.json") is None


def test_artifact_with_a_different_feature_list_is_refused(tmp_path: Path) -> None:
    manifest = tmp_path / "ranker.json"
    manifest.write_text(
        json.dumps({"format": "linear", "feature_names": ["only_one"], "weights": [1.0]}),
        encoding="utf-8",
    )

    assert LtrRankerModel.load(manifest) is None


def test_learned_ranker_off_by_default_keeps_the_hand_tuned_order(tmp_path: Path) -> None:
    strategy, expected = _strategy(tmp_path, GraphFileSearchConfig(seed_limit=5, lexical_seed_limit=5))

    results = strategy.search("update user", limit=5)

    assert [result.item.path for result in results] == expected


def test_learned_ranker_reverses_the_order_when_the_model_says_so(tmp_path: Path) -> None:
    artifact = _linear_artifact(tmp_path, weight_of="fused_score", weight=-1.0)
    baseline, expected = _strategy(tmp_path, GraphFileSearchConfig(seed_limit=5, lexical_seed_limit=5))
    strategy, _ = _strategy(
        tmp_path,
        GraphFileSearchConfig(
            seed_limit=5,
            lexical_seed_limit=5,
            ltr_ranker_enabled=True,
            ltr_model_path=str(artifact),
        ),
    )

    results = strategy.search("update user", limit=5)

    assert [result.item.path for result in baseline.search("update user", limit=5)] == expected
    assert [result.item.path for result in results] == list(reversed(expected))


def test_learned_ranker_falls_back_to_the_hand_tuned_order_without_an_artifact(tmp_path: Path) -> None:
    strategy, expected = _strategy(
        tmp_path,
        GraphFileSearchConfig(
            seed_limit=5,
            lexical_seed_limit=5,
            ltr_ranker_enabled=True,
            ltr_model_path=str(tmp_path / "absent.json"),
        ),
    )

    results = strategy.search("update user", limit=5)

    assert [result.item.path for result in results] == expected


def test_feature_sink_captures_one_row_per_candidate(tmp_path: Path) -> None:
    collector = LtrFeatureCollector()
    strategy, expected = _strategy(tmp_path, GraphFileSearchConfig(seed_limit=5, lexical_seed_limit=5))
    assert LtrFeatureSinkAttacher().attach(strategy, collector.collect)

    results = strategy.search("update user", limit=5)

    assert [result.item.path for result in results] == expected
    assert [row.path for row in collector.rows_for("update user")] == expected


def _strategy(
    tmp_path: Path,
    config: GraphFileSearchConfig,
) -> tuple[GraphFileRetrievalStrategy, list[str]]:
    items = [
        CodeItem(
            id=f"item-{index}",
            path=path,
            title=f"{path}::file_manifest",
            content=f"file: {path}\nsymbols:\n- function update_user",
            metadata={"index_kind": "file_manifest"},
        )
        for index, path in enumerate(("src/users/service.py", "src/api/users.py", "src/billing.py"))
    ]
    store = CodeGraphStore(tmp_path / f"graph-{id(config)}.json")
    store.save(CodeGraph(items={item.id: item for item in items}, edges=[]))
    base = FakeRetrievalStrategy(
        [SearchResult(items[0], 0.95), SearchResult(items[1], 0.80), SearchResult(items[2], 0.10)]
    )
    strategy = GraphFileRetrievalStrategy(base, store, config)
    return strategy, [item.path for item in items]


def _linear_artifact(tmp_path: Path, weight_of: str, weight: float) -> Path:
    weights = [0.0] * len(LTR_FEATURE_NAMES)
    weights[LTR_FEATURE_NAMES.index(weight_of)] = weight
    manifest = tmp_path / "stub_ranker.json"
    manifest.write_text(
        json.dumps(
            {
                "format": "linear",
                "feature_names": list(LTR_FEATURE_NAMES),
                "weights": weights,
                "bias": 0.0,
            }
        ),
        encoding="utf-8",
    )
    return manifest

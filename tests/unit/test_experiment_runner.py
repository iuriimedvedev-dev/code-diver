from __future__ import annotations

import pytest

from code_diver.config import AppConfig
from code_diver.config.cross_encoder_rerank_config import CrossEncoderRerankConfig
from code_diver.config.experiment_hypothesis_config import ExperimentHypothesisConfig
from code_diver.domain import CodeItem, EvalCase, SearchResult
from code_diver.experiments import ExperimentRunner
from code_diver.strategies import RetrievalStrategy

pytestmark = pytest.mark.unit


class CapturingFactory:
    def __init__(self) -> None:
        self.configs: list[AppConfig] = []

    def create(self, strategy: str, config: AppConfig, provider: object, vector_store: object) -> RetrievalStrategy:
        self.configs.append(config)
        return StaticStrategy()


class StaticStrategy(RetrievalStrategy):
    def search(self, query: str, limit: int) -> list[SearchResult]:
        return [
            SearchResult(
                CodeItem(id="target.py#1", path="target.py", title="target.py", content=""),
                1.0,
            )
        ]


class StatsVectorStore:
    def metadata(self) -> dict[str, object]:
        return {"dimensions": 8}

    def count_items(self) -> int:
        return 5


def test_experiment_runner_applies_cross_encoder_rerank_hypothesis_override() -> None:
    factory = CapturingFactory()
    config = AppConfig()
    config.experiments.hypotheses = [
        ExperimentHypothesisConfig(
            name="top5",
            strategy="cross_encoder_rerank",
            cross_encoder_rerank=CrossEncoderRerankConfig(candidate_limit=5),
        )
    ]

    ExperimentRunner(factory, provider=object(), vector_store=object()).run(
        "run",
        config,
        [EvalCase(id="case", query="query", expected=["target.py"])],
    )

    assert factory.configs[0].cross_encoder_rerank.candidate_limit == 5


def test_experiment_runner_adds_index_size_metrics() -> None:
    factory = CapturingFactory()
    config = AppConfig()
    config.experiments.hypotheses = [ExperimentHypothesisConfig(name="hybrid", strategy="hybrid")]

    run = ExperimentRunner(factory, provider=object(), vector_store=StatsVectorStore()).run(
        "run",
        config,
        [EvalCase(id="case", query="query", expected=["target.py"])],
    )

    metrics = run.strategy_results[0].metrics
    assert metrics["index_items"] == 5
    assert metrics["index_vector_dimensions"] == 8
    assert metrics["index_vector_bytes_estimate"] == 160
    assert metrics["index_vector_mb_estimate"] == 0.00016

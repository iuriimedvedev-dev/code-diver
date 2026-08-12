from __future__ import annotations

import pytest

from code_diver.config import AppConfig
from code_diver.domain import EvalResult
from code_diver.experiments import ExperimentRun, StrategyExperimentResult
from code_diver.metrics import ExperimentMetricsMapper

pytestmark = pytest.mark.unit


def test_experiment_metrics_mapper_exports_rich_case_metrics() -> None:
    run = ExperimentRun(
        run_id="run",
        suite="suite",
        strategy_results=[
            StrategyExperimentResult(
                strategy="hybrid",
                metrics={"hit_rate@5": 1.0, "degraded": False},
                duration_ms=12.0,
                results=[
                    EvalResult(
                        case_id="case",
                        query="where is auth",
                        expected=["src/auth.py"],
                        retrieved=["src/auth.py#handler"],
                        hit=True,
                        reciprocal_rank=1.0,
                        precision=1.0,
                        recall=1.0,
                        retrieved_files=["src/auth.py"],
                        bucket="workflow",
                        top_result_kind="symbol",
                        first_relevant_kind="symbol",
                        file_hit=True,
                        file_reciprocal_rank=1.0,
                        file_precision_at_r=1.0,
                        file_recall=1.0,
                        ndcg=1.0,
                        average_precision=1.0,
                    )
                ],
            )
        ],
    )

    _, case_rows = ExperimentMetricsMapper().to_rows(run, AppConfig(), None)

    row = case_rows[0]
    assert row.retrieved_files == ["src/auth.py"]
    assert row.file_hit == 1
    assert row.file_recall == 1.0
    assert row.ndcg == 1.0
    assert row.average_precision == 1.0
    assert row.bucket == "workflow"
    assert row.top_result_kind == "symbol"
    assert row.first_relevant_kind == "symbol"
    assert row.expected_count == 1
    assert row.retrieved_count == 1
    assert row.retrieved_file_count == 1

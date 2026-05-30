from __future__ import annotations

import pytest

from code_diver.agent.model_cost_estimator import ModelCostEstimator


pytestmark = pytest.mark.unit


def test_model_cost_estimator_uses_model_specific_prices() -> None:
    estimator = ModelCostEstimator()

    gemini_cost = estimator.estimate("gemini-2.5-flash", input_tokens=1_000_000, output_tokens=1_000_000)
    opus_cost = estimator.estimate("claude-opus-4-8", input_tokens=1_000_000, output_tokens=1_000_000)

    assert gemini_cost == pytest.approx(2.8)
    assert opus_cost == pytest.approx(90.0)


def test_model_cost_estimator_treats_local_models_as_zero_marginal_api_cost() -> None:
    estimator = ModelCostEstimator()

    assert estimator.estimate("local-chat", input_tokens=10_000, output_tokens=10_000) == 0.0
    assert estimator.estimate("ollama/mxbai", input_tokens=10_000, output_tokens=10_000) == 0.0


def test_model_cost_estimator_falls_back_to_default_research_estimate() -> None:
    estimator = ModelCostEstimator()

    assert estimator.estimate("unknown-api-model", input_tokens=1_000_000, output_tokens=1_000_000) == pytest.approx(
        10.5
    )

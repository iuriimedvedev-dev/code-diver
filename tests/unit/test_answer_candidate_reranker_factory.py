from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.answering import (
    AnswerCandidateCrossEncoderReranker,
    AnswerCandidateReranker,
    AnswerCandidateRerankerFactory,
)
from code_diver.config import ConfigLoader

pytestmark = pytest.mark.unit


class FakeGenerationProvider:
    name = "fake_generation"
    model = "answer-model"


def _config(tmp_path: Path, body: str):
    config_path = tmp_path / "code-diver.yml"
    config_path.write_text(body.strip(), encoding="utf-8")
    return ConfigLoader().load(config_path)


def _champion_body(strategy: str) -> str:
    return f"""
generation:
  provider: openai_compatible
  model: answer-model
  url: http://127.0.0.1:8012/v1/chat/completions
search:
  strategy: {strategy}
  limit: 10
llm_rerank:
  candidate_limit: 34
cross_encoder_rerank:
  url: http://127.0.0.1:8081/v1/rerank
  candidate_limit: 34
"""


def test_the_champion_strategy_still_gets_the_generative_reranker(tmp_path: Path) -> None:
    config = _config(tmp_path, _champion_body("graph_file_rerank"))
    answer_provider = FakeGenerationProvider()

    reranker = AnswerCandidateRerankerFactory().create(config, answer_provider)

    assert isinstance(reranker, AnswerCandidateReranker)
    # No `llm_rerank.generation` override: reuse the answer provider, do not open a second client.
    assert reranker.provider is answer_provider


def test_a_cross_encoder_strategy_gets_the_cross_encoder_reranker(tmp_path: Path) -> None:
    config = _config(tmp_path, _champion_body("graph_file_cross_encoder"))

    reranker = AnswerCandidateRerankerFactory().create(config, FakeGenerationProvider())

    assert isinstance(reranker, AnswerCandidateCrossEncoderReranker)
    assert reranker.candidate_limit == 34


def test_the_hybrid_cross_encoder_strategy_also_gets_the_cross_encoder(tmp_path: Path) -> None:
    config = _config(tmp_path, _champion_body("cross_encoder_rerank"))

    reranker = AnswerCandidateRerankerFactory().create(config, FakeGenerationProvider())

    assert isinstance(reranker, AnswerCandidateCrossEncoderReranker)


def test_the_rerank_generation_override_reaches_the_final_candidate_rerank(tmp_path: Path) -> None:
    # The defect behind Finding 35: this override was honoured by the retrieval-strategy wrapper
    # but not here, so an arm that named a separate rerank model silently reranked with the
    # answer model and reproduced the champion.
    config = _config(
        tmp_path,
        """
generation:
  provider: openai_compatible
  model: answer-model
  url: http://127.0.0.1:8012/v1/chat/completions
search:
  strategy: graph_file_rerank
llm_rerank:
  candidate_limit: 34
  generation:
    model: rerank-model
    url: http://127.0.0.1:8013/v1/chat/completions
""",
    )
    answer_provider = FakeGenerationProvider()

    reranker = AnswerCandidateRerankerFactory().create(config, answer_provider)

    assert isinstance(reranker, AnswerCandidateReranker)
    assert reranker.provider is not answer_provider
    assert reranker.provider.model == "rerank-model"


def test_the_report_records_the_reranker_that_will_actually_run(tmp_path: Path) -> None:
    # The guard against Finding 35 recurring: a report whose settings block names the rerank
    # model cannot silently be a replicate of its own control.
    from code_diver.cli import final_rerank_settings

    config = _config(tmp_path, _champion_body("graph_file_cross_encoder"))

    settings = final_rerank_settings(
        AnswerCandidateRerankerFactory().create(config, FakeGenerationProvider())
    )

    assert settings["final_rerank_kind"] == "AnswerCandidateCrossEncoderReranker"
    assert settings["final_rerank_model"] == "Qwen3-Reranker-0.6B"
    assert settings["final_rerank_candidate_limit"] == 34


def test_a_disabled_final_rerank_is_recorded_as_such() -> None:
    from code_diver.cli import final_rerank_settings

    assert final_rerank_settings(None) == {"final_rerank_kind": None}

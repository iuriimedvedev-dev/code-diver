from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.config import ConfigLoader
from code_diver.strategies.retrieval_strategy_factory import RetrievalStrategyFactory

pytestmark = pytest.mark.unit


def _config(tmp_path: Path, rerank_block: str):
    config_path = tmp_path / "code-diver.yml"
    config_path.write_text(
        f"""
generation:
  provider: openai_compatible
  model: answer-model
  url: http://127.0.0.1:8012/v1/chat/completions
llm_rerank:
{rerank_block}
""".strip(),
        encoding="utf-8",
    )
    return ConfigLoader().load(config_path)


def test_rerank_generation_config_is_the_same_object_without_an_override(tmp_path: Path) -> None:
    config = _config(tmp_path, "  candidate_limit: 34")

    assert RetrievalStrategyFactory()._rerank_generation_config(config) is config


def test_rerank_generation_config_swaps_the_generation_block(tmp_path: Path) -> None:
    config = _config(tmp_path, "  generation:\n    model: rerank-model")

    swapped = RetrievalStrategyFactory()._rerank_generation_config(config)

    assert swapped.generation.model == "rerank-model"
    assert config.generation.model == "answer-model"
    assert swapped.llm_rerank is config.llm_rerank

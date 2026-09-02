from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.config import ConfigLoader, MultiQueryConfig
from code_diver.strategies.cross_encoder_rerank_retrieval_strategy import (
    CrossEncoderRerankRetrievalStrategy,
)
from code_diver.strategies.graph_file_retrieval_strategy import GraphFileRetrievalStrategy
from code_diver.strategies.hybrid_retrieval_strategy import HybridRetrievalStrategy
from code_diver.strategies.llm_rerank_retrieval_strategy import LlmRerankRetrievalStrategy
from code_diver.strategies.multi_query_rrf_strategy import MultiQueryRrfStrategy
from code_diver.strategies.retrieval_strategy_factory import RetrievalStrategyFactory

pytestmark = pytest.mark.unit


def _config(tmp_path: Path, strategy: str):
    config_path = tmp_path / "code-diver.yml"
    config_path.write_text(
        f"""
search:
  strategy: {strategy}
  limit: 10
cross_encoder_rerank:
  candidate_limit: 34
  url: http://127.0.0.1:8080/v1/rerank
graph:
  artifact: {tmp_path / "graph.json"}
""".strip(),
        encoding="utf-8",
    )
    return ConfigLoader().load(config_path)


def _built(tmp_path: Path, strategy: str):
    config = _config(tmp_path, strategy)
    return RetrievalStrategyFactory().create(strategy, config, object(), object())


def test_graph_file_cross_encoder_reranks_graph_file_candidates(tmp_path: Path) -> None:
    strategy = _built(tmp_path, "graph_file_cross_encoder")

    assert isinstance(strategy, CrossEncoderRerankRetrievalStrategy)
    # The point of the id: same base as the champion, only the rerank primitive differs.
    assert isinstance(strategy.base_strategy, GraphFileRetrievalStrategy)


def test_graph_file_rerank_keeps_its_graph_file_base(tmp_path: Path) -> None:
    strategy = _built(tmp_path, "graph_file_rerank")

    assert isinstance(strategy, LlmRerankRetrievalStrategy)
    assert isinstance(strategy.base_strategy, GraphFileRetrievalStrategy)


def test_cross_encoder_rerank_still_sits_on_plain_hybrid(tmp_path: Path) -> None:
    strategy = _built(tmp_path, "cross_encoder_rerank")

    assert isinstance(strategy, CrossEncoderRerankRetrievalStrategy)
    assert isinstance(strategy.base_strategy, HybridRetrievalStrategy)


def test_union_rerank_fuses_graph_file_candidates_before_one_cross_encoder(tmp_path: Path) -> None:
    config = _config(tmp_path, "graph_file_cross_encoder")
    config.multi_query = MultiQueryConfig(enabled=True, union_rerank=True)

    strategy = RetrievalStrategyFactory().create(
        "graph_file_cross_encoder", config, object(), object()
    )

    assert isinstance(strategy, CrossEncoderRerankRetrievalStrategy)
    assert isinstance(strategy.base_strategy, MultiQueryRrfStrategy)
    assert isinstance(strategy.base_strategy.underlying, GraphFileRetrievalStrategy)
    assert strategy.base_strategy.fusion_pool_size == config.cross_encoder_rerank.candidate_limit

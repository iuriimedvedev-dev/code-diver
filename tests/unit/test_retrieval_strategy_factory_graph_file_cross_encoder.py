from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.config import ConfigLoader, MultiQueryConfig
from code_diver.domain import CodeItem, SearchResult
from code_diver.reranking.rerank_score import RerankScore
from code_diver.strategies.cross_encoder_rerank_retrieval_strategy import (
    CrossEncoderRerankRetrievalStrategy,
)
from code_diver.strategies.graph_file_retrieval_strategy import GraphFileRetrievalStrategy
from code_diver.strategies.hybrid_retrieval_strategy import HybridRetrievalStrategy
from code_diver.strategies.llm_rerank_retrieval_strategy import LlmRerankRetrievalStrategy
from code_diver.strategies.multi_query_rrf_strategy import MultiQueryRrfStrategy
from code_diver.strategies.retrieval_strategy import RetrievalStrategy
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


class _FakeGraphFileStrategy(RetrievalStrategy):
    def __init__(self, results: dict[str, list[SearchResult]]) -> None:
        self.results = results
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> list[SearchResult]:
        self.calls.append((query, limit))
        return self.results.get(query, [])[:limit]


class _FakeCrossEncoder:
    name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    def rerank(self, query: str, documents: list[str], limit: int) -> list[RerankScore]:
        self.calls.append((query, len(documents), limit))
        return [RerankScore(index=index, score=float(len(documents) - index)) for index in range(len(documents))]


def _result(path: str, score: float) -> SearchResult:
    return SearchResult(CodeItem(id=path, path=path, title=path, content=path), score)


def test_union_rerank_executes_ce_less_variants_and_one_outer_rerank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, "graph_file_cross_encoder")
    config.search.limit = 2
    config.cross_encoder_rerank.candidate_limit = 3
    config.multi_query = MultiQueryConfig(enabled=True, union_rerank=True, max_variants=2, parallel_variants=False)
    graph_file = _FakeGraphFileStrategy(
        {
            "where is foo bar?": [_result("a.py", 0.9), _result("b.py", 0.8), _result("c.py", 0.7)],
            "foo bar": [_result("c.py", 0.9), _result("d.py", 0.8), _result("e.py", 0.7)],
        }
    )
    reranker = _FakeCrossEncoder()
    monkeypatch.setattr(
        RetrievalStrategyFactory,
        "_create_graph_file_base",
        lambda self, config, provider, store: graph_file,
    )
    monkeypatch.setattr(
        "code_diver.strategies.retrieval_strategy_factory.RerankProviderFactory.create",
        lambda self, config: reranker,
    )

    strategy = RetrievalStrategyFactory().create("graph_file_cross_encoder", config, object(), object())
    results = strategy.search("where is foo bar?", config.search.limit)

    assert graph_file.calls == [("where is foo bar?", 3), ("foo bar", 3)]
    assert reranker.calls == [("where is foo bar?", 3, 2)]
    assert len(results) == 2
    assert [result.item.path for result in results] == ["c.py", "a.py"]


def test_union_rerank_false_keeps_v1_cross_encoder_inside_multi_query(tmp_path: Path) -> None:
    config = _config(tmp_path, "graph_file_cross_encoder")
    config.multi_query = MultiQueryConfig(enabled=True, union_rerank=False)

    strategy = RetrievalStrategyFactory().create(
        "graph_file_cross_encoder", config, object(), object()
    )

    assert isinstance(strategy, MultiQueryRrfStrategy)
    assert isinstance(strategy.underlying, CrossEncoderRerankRetrievalStrategy)
    assert isinstance(strategy.underlying.base_strategy, GraphFileRetrievalStrategy)

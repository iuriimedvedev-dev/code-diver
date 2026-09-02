from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.config import AppConfig, ConfigLoader, MultiQueryConfig
from code_diver.domain import CodeItem, SearchResult
from code_diver.reranking.rerank_score import RerankScore
from code_diver.strategies.cross_encoder_rerank_retrieval_strategy import (
    CrossEncoderRerankRetrievalStrategy,
)
from code_diver.strategies.graph_file_retrieval_strategy import GraphFileRetrievalStrategy
from code_diver.strategies.multi_query_rrf_strategy import MultiQueryRrfStrategy
from code_diver.strategies.retrieval_strategy import RetrievalStrategy
from code_diver.strategies.retrieval_strategy_factory import RetrievalStrategyFactory

pytestmark = pytest.mark.unit


def _config(tmp_path: Path, strategy: str = "graph_file_cross_encoder") -> AppConfig:
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


def _result(path: str, score: float = 1.0) -> SearchResult:
    return SearchResult(CodeItem(id=path, path=path, title=path, content=""), score)


class FakeStrategy(RetrievalStrategy):
    def __init__(self, responses: dict[str, list[SearchResult]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> list[SearchResult]:
        self.calls.append((query, limit))
        return self.responses.get(query, [])[:limit]


class FakeCrossEncoder:
    name = "fake"
    model = "fake-model"

    def rerank(self, query: str, documents: list[str], limit: int) -> list[RerankScore]:
        return [RerankScore(index=index, score=float(len(documents) - index)) for index in range(len(documents))]


def _factory(monkeypatch: pytest.MonkeyPatch) -> RetrievalStrategyFactory:
    monkeypatch.setattr(
        "code_diver.strategies.retrieval_strategy_factory.RerankProviderFactory.create",
        lambda self, config: FakeCrossEncoder(),
    )
    return RetrievalStrategyFactory()


def test_union_rerank_default_off_config_wiring_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    config.multi_query = MultiQueryConfig(enabled=True, union_rerank=False)

    strategy = _factory(monkeypatch).create(
        "graph_file_cross_encoder", config, object(), object()
    )

    assert isinstance(strategy, MultiQueryRrfStrategy)
    assert isinstance(strategy.underlying, CrossEncoderRerankRetrievalStrategy)
    assert isinstance(strategy.underlying.base_strategy, GraphFileRetrievalStrategy)
    assert strategy.fusion_pool_size is None


def test_union_rerank_true_pulls_ce_outside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    config.multi_query = MultiQueryConfig(enabled=True, union_rerank=True)

    strategy = _factory(monkeypatch).create(
        "graph_file_cross_encoder", config, object(), object()
    )

    assert isinstance(strategy, CrossEncoderRerankRetrievalStrategy)
    assert isinstance(strategy.base_strategy, MultiQueryRrfStrategy)
    assert not isinstance(strategy.base_strategy.underlying, CrossEncoderRerankRetrievalStrategy)


def test_union_rerank_true_sets_fusion_pool_size_to_candidate_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    config.multi_query = MultiQueryConfig(enabled=True, union_rerank=True)

    strategy = _factory(monkeypatch).create(
        "graph_file_cross_encoder", config, object(), object()
    )

    assert isinstance(strategy, CrossEncoderRerankRetrievalStrategy)
    assert isinstance(strategy.base_strategy, MultiQueryRrfStrategy)
    assert strategy.base_strategy.fusion_pool_size == config.cross_encoder_rerank.candidate_limit


def test_multi_query_rrf_fuses_to_effective_limit() -> None:
    responses = {
        "q": [_result("a"), _result("b")],
        "rewrite": [_result("b"), _result("c")],
    }
    generator = type("Generator", (), {"variants": lambda self, query, maximum: ["q", "rewrite"]})()

    pooled_base = FakeStrategy(responses)
    pooled = MultiQueryRrfStrategy(
        pooled_base,
        MultiQueryConfig(parallel_variants=False),
        generator=generator,
        fusion_pool_size=3,
    )
    pooled_values = pooled.search("q", 1)
    assert pooled_base.calls == [("q", 3), ("rewrite", 3)]
    assert len(pooled_values) == 3

    plain_base = FakeStrategy({"q": [_result("a"), _result("b")], "rewrite": [_result("b")]})
    plain = MultiQueryRrfStrategy(
        plain_base,
        MultiQueryConfig(parallel_variants=False),
        generator=generator,
    )
    plain_values = plain.search("q", 1)
    assert plain_base.calls == [("q", 1), ("rewrite", 1)]
    assert len(plain_values) == 1
    assert len(plain.search("q", 3)) == 2
    assert plain_base.calls[-2:] == [("q", 3), ("rewrite", 3)]


def test_multi_query_disabled_bit_exact_passthrough(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = FakeStrategy({})
    monkeypatch.setattr(RetrievalStrategyFactory, "_create_base", lambda self, strategy, config, provider, store: base)
    config = AppConfig(root=tmp_path, multi_query=MultiQueryConfig(enabled=False))

    result = RetrievalStrategyFactory().create("vector", config, object(), object())

    assert result is base
    assert not isinstance(result, MultiQueryRrfStrategy)
    assert not isinstance(result, CrossEncoderRerankRetrievalStrategy)


def test_champion_yaml_still_loads_with_multi_query_disabled() -> None:
    config = ConfigLoader().load(Path("configs/intellij/intellij-h66b-champion.yml"))

    assert config is not None
    assert not config.multi_query.enabled
    assert config.multi_query.union_rerank is False

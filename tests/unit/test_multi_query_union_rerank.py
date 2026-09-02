from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, Mock, call, patch

import pytest

from code_diver.config import AppConfig, MultiQueryConfig
from code_diver.domain import CodeItem, SearchResult
from code_diver.strategies.cross_encoder_rerank_retrieval_strategy import (
    CrossEncoderRerankRetrievalStrategy,
)
from code_diver.strategies.graph_file_retrieval_strategy import GraphFileRetrievalStrategy
from code_diver.strategies.multi_query_rrf_strategy import MultiQueryRrfStrategy
from code_diver.strategies.retrieval_strategy import RetrievalStrategy
from code_diver.strategies.retrieval_strategy_factory import RetrievalStrategyFactory

pytestmark = pytest.mark.unit


def _result(path: str, score: float = 1.0) -> SearchResult:
    return SearchResult(CodeItem(id=path, path=path, title=path, content=""), score)


def _factory_config(tmp_path: Path, *, union_rerank: bool) -> AppConfig:
    return AppConfig(
        root=tmp_path,
        multi_query=MultiQueryConfig(enabled=True, union_rerank=union_rerank),
    )


def test_multi_query_config_union_rerank_defaults_to_false() -> None:
    config = MultiQueryConfig()

    assert config.enabled is False
    assert config.union_rerank is False


def test_factory_keeps_cross_encoder_inside_multi_query_by_default(tmp_path: Path) -> None:
    config = _factory_config(tmp_path, union_rerank=False)
    provider = Mock()
    vector_store = Mock()

    with patch(
        "code_diver.strategies.retrieval_strategy_factory.RerankProviderFactory.create",
        return_value=Mock(name="rerank_provider"),
    ):
        strategy = RetrievalStrategyFactory().create(
            "graph_file_cross_encoder", config, provider, vector_store
        )

    assert isinstance(strategy, MultiQueryRrfStrategy)
    assert isinstance(strategy.underlying, CrossEncoderRerankRetrievalStrategy)
    assert isinstance(strategy.underlying.base_strategy, GraphFileRetrievalStrategy)
    assert strategy.fusion_pool_size is None


def test_factory_union_rerank_wraps_multi_query_before_one_cross_encoder(tmp_path: Path) -> None:
    config = _factory_config(tmp_path, union_rerank=True)
    config.cross_encoder_rerank.candidate_limit = 7

    with patch(
        "code_diver.strategies.retrieval_strategy_factory.RerankProviderFactory.create",
        return_value=MagicMock(name="rerank_provider"),
    ):
        strategy = RetrievalStrategyFactory().create(
            "graph_file_cross_encoder", config, Mock(), Mock()
        )

    assert isinstance(strategy, CrossEncoderRerankRetrievalStrategy)
    assert isinstance(strategy.base_strategy, MultiQueryRrfStrategy)
    assert not isinstance(strategy.base_strategy.underlying, CrossEncoderRerankRetrievalStrategy)
    assert isinstance(strategy.base_strategy.underlying, GraphFileRetrievalStrategy)
    assert strategy.base_strategy.fusion_pool_size == config.cross_encoder_rerank.candidate_limit


def test_rrf_overfetches_each_variant_and_respects_effective_limit() -> None:
    underlying = MagicMock(spec=RetrievalStrategy)
    underlying.search.side_effect = lambda query, limit: {
        "query": [_result("a"), _result("b"), _result("c")][:limit],
        "rewrite": [_result("d"), _result("e"), _result("f")][:limit],
    }[query]
    generator = Mock()
    generator.variants.return_value = ["query", "rewrite"]
    strategy = MultiQueryRrfStrategy(
        underlying,
        MultiQueryConfig(parallel_variants=False),
        generator=generator,
        fusion_pool_size=3,
    )

    results = strategy.search("query", 1)

    assert underlying.search.call_args_list == [
        call("query", 3),
        call("rewrite", 3),
    ]
    assert len(results) == 3


def test_rrf_without_fusion_pool_requests_exact_limit() -> None:
    underlying = MagicMock(spec=RetrievalStrategy)
    underlying.search.side_effect = lambda query, limit: [_result(query)][:limit]
    generator = Mock()
    generator.variants.return_value = ["query", "rewrite"]
    strategy = MultiQueryRrfStrategy(
        underlying,
        MultiQueryConfig(parallel_variants=False),
        generator=generator,
    )

    results = strategy.search("query", 2)

    assert underlying.search.call_args_list == [
        call("query", 2),
        call("rewrite", 2),
    ]
    assert len(results) == 2


def test_factory_disabled_multi_query_is_bit_exact_passthrough(tmp_path: Path) -> None:
    config = AppConfig(root=tmp_path, multi_query=MultiQueryConfig(enabled=False))
    base = Mock(spec=RetrievalStrategy)
    factory = RetrievalStrategyFactory()

    with patch.object(factory, "_create_base", return_value=base) as create_base:
        result = factory.create("vector", config, Mock(), Mock())

    assert result is base
    assert not isinstance(result, MultiQueryRrfStrategy)
    create_base.assert_called_once()

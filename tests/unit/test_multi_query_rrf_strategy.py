from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.config import AppConfig, ConfigLoader, MultiQueryConfig
from code_diver.domain import CodeItem, SearchResult
from code_diver.strategies.multi_query_rrf_strategy import (
    MultiQueryRrfStrategy,
    MultiQueryVariantGenerator,
)
from code_diver.strategies.retrieval_strategy import RetrievalStrategy
from code_diver.strategies.retrieval_strategy_factory import RetrievalStrategyFactory

pytestmark = pytest.mark.unit


def _result(path: str, score: float = 1.0) -> SearchResult:
    return SearchResult(CodeItem(id=path, path=path, title=path, content=""), score)


class FakeStrategy(RetrievalStrategy):
    def __init__(self, responses: dict[str, list[SearchResult]], cap: int | None = None) -> None:
        self.responses = responses
        self.cap = cap
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> list[SearchResult]:
        self.calls.append((query, limit))
        values = self.responses.get(query, [])
        return values[: self.cap if self.cap is not None else limit]


def test_weighted_rrf_exact_math() -> None:
    base = FakeStrategy({"q": [_result("a", 5), _result("b", 3)], "rewrite": [_result("b", 2), _result("c", 1)]})
    strategy = MultiQueryRrfStrategy(
        base,
        MultiQueryConfig(max_variants=2, rrf_k=1, original_query_weight=2, parallel_variants=False),
        generator=type("Generator", (), {"variants": lambda self, query, maximum: ["q", "rewrite"]})(),
    )
    values = strategy.search("q", 3)
    assert [value.item.path for value in values] == ["b", "a", "c"]
    assert values[0].score == pytest.approx(2 / 3 + 1 / 2 + 3e-9)
    assert values[1].score == pytest.approx(2 / 2 + 5e-9)


def test_original_weight_can_outrank_rewrite() -> None:
    base = FakeStrategy({"original": [_result("a")], "rewrite": [_result("b"), _result("a")]})
    strategy = MultiQueryRrfStrategy(
        base,
        MultiQueryConfig(max_variants=2, original_query_weight=3, parallel_variants=False),
        generator=type("Generator", (), {"variants": lambda self, query, maximum: ["original", "rewrite"]})(),
    )
    assert strategy.search("original", 2)[0].item.path == "a"


def test_one_variant_is_identity_passthrough() -> None:
    base = FakeStrategy({"q": [_result("a")]})
    strategy = MultiQueryRrfStrategy(
        base,
        MultiQueryConfig(max_variants=1),
        generator=type("Generator", (), {"variants": lambda self, query, maximum: [query]})(),
    )
    assert strategy.search("q", 1) == base.responses["q"]
    assert base.calls == [("q", 1)]


def test_fusion_pool_overfetches_each_variant_and_fusion_pool() -> None:
    base = FakeStrategy(
        {"q": [_result("a"), _result("b")], "rewrite": [_result("b"), _result("c")]}
    )
    generator = type("Generator", (), {"variants": lambda self, query, maximum: ["q", "rewrite"]})()
    strategy = MultiQueryRrfStrategy(
        base,
        MultiQueryConfig(parallel_variants=False),
        generator=generator,
        fusion_pool_size=3,
    )

    values = strategy.search("q", 1)

    assert base.calls == [("q", 3), ("rewrite", 3)]
    assert len(values) == 3


def test_factory_disabled_and_enabled_wrapping(tmp_path: Path) -> None:
    disabled = AppConfig(root=tmp_path)
    plain = RetrievalStrategyFactory().create("vector", disabled, object(), object())
    assert not isinstance(plain, MultiQueryRrfStrategy)

    enabled = AppConfig(root=tmp_path, multi_query=MultiQueryConfig(enabled=True))
    wrapped = RetrievalStrategyFactory().create("vector", enabled, object(), object())
    assert isinstance(wrapped, MultiQueryRrfStrategy)


def test_factory_union_rerank_only_changes_graph_file_cross_encoder(tmp_path: Path) -> None:
    config = AppConfig(
        root=tmp_path,
        multi_query=MultiQueryConfig(enabled=True, union_rerank=True),
    )

    vector = RetrievalStrategyFactory().create("vector", config, object(), object())

    assert isinstance(vector, MultiQueryRrfStrategy)
    assert not isinstance(vector.underlying, MultiQueryRrfStrategy)


def test_loader_reads_multi_query_config(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text(
        "multi_query:\n  enabled: true\n  max_variants: 3\n  rrf_k: 12\n"
        "  original_query_weight: 1.5\n  llm_rewrites_enabled: true\n"
        "  parallel_variants: false\n  max_variant_workers: 2\n",
        encoding="utf-8",
    )
    config = ConfigLoader().load(path)
    assert config.multi_query == MultiQueryConfig(True, 3, 12, 1.5, True, False, 2)


def test_deterministic_rewrite_behaviors() -> None:
    generator = MultiQueryVariantGenerator()
    assert generator.variants("How do I find usages in the codebase?", 4)[0] == "How do I find usages in the codebase?"
    assert generator._statement("Where is the debugger in the IDE?") == "debugger"
    assert generator._statement("Where is the extract method refactoring implemented?") == "extract method refactoring implemented"
    assert generator._aliased("find usages and settings") == "usage search and options"
    assert generator._symbol_guess("extract method refactoring implemented") == "ExtractMethodRefactoring"
    assert generator._symbol_guess("find foo bar baz qux quux") == "FooBarBazQux"
    assert generator.variants("find usages", 2) == ["find usages", "usage search"]
    assert generator.variants("", 4) == []


def test_parallel_and_sequential_results_are_identical() -> None:
    responses = {"q": [_result("a", 2)], "q alias": [_result("b", 1)]}
    generator = type("Generator", (), {"variants": lambda self, query, maximum: ["q", "q alias"]})()
    sequential = MultiQueryRrfStrategy(FakeStrategy(responses), MultiQueryConfig(parallel_variants=False), generator=generator)
    parallel = MultiQueryRrfStrategy(FakeStrategy(responses), MultiQueryConfig(parallel_variants=True), generator=generator)
    assert sequential.search("q", 2) == parallel.search("q", 2)


def test_duplicate_path_counted_once_per_ranked_list() -> None:
    base = FakeStrategy(
        {"q": [_result("same", 1), _result("other", 9), _result("same", 0.5)], "rewrite": [_result("same", 2)]}
    )
    generator = type("Generator", (), {"variants": lambda self, query, maximum: ["q", "rewrite"]})()
    strategy = MultiQueryRrfStrategy(base, MultiQueryConfig(parallel_variants=False), generator=generator)
    values = strategy.search("q", 3)
    assert [value.item.path for value in values] == ["same", "other"]
    assert values[0].score == pytest.approx(2 / 61 + 1 / 61 + 1e-9)
    assert values[1].score == pytest.approx(2 / 62 + 9e-9)

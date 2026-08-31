from __future__ import annotations

import time

from code_diver.config.cross_encoder_rerank_config import CrossEncoderRerankConfig
from code_diver.domain import CodeItem, SearchResult
from code_diver.reranking.rerank_score import RerankScore
from code_diver.strategies.fan_out_union_rerank_search import FanOutUnionRerankSearch


def result(identifier: str, path: str, score: float) -> SearchResult:
    return SearchResult(CodeItem(id=identifier, path=path, title=path, content=path), score)


class StubStrategy:
    def __init__(self, by_query: dict[str, list[SearchResult]]):
        self.by_query = by_query
        self.queries: list[str] = []

    def search(self, query: str, limit: int) -> list[SearchResult]:
        self.queries.append(query)
        return self.by_query.get(query, [])[:limit]


class DelayedStrategy(StubStrategy):
    def __init__(self, by_query: dict[str, list[SearchResult]], delay: float = 0.03):
        super().__init__(by_query)
        self.delay = delay

    def search(self, query: str, limit: int) -> list[SearchResult]:
        time.sleep(self.delay)
        return super().search(query, limit)


class StubRerankProvider:
    name = "stub"
    model = "stub"

    def __init__(self, order_by_path: list[str] | None = None, fail: bool = False):
        self.order_by_path = order_by_path or []
        self.fail = fail
        self.calls: list[tuple[str, int]] = []

    def rerank(self, query: str, documents: list[str], limit: int) -> list[RerankScore]:
        self.calls.append((query, len(documents)))
        if self.fail:
            raise RuntimeError("rerank down")
        scored = []
        for index, document in enumerate(documents):
            rank = next(
                (position for position, path in enumerate(self.order_by_path) if path in document),
                len(self.order_by_path) + index,
            )
            scored.append(RerankScore(index=index, score=-float(rank)))
        scored.sort(key=lambda item: -item.score)
        return scored[:limit]


def make_search(strategy: StubStrategy, provider: StubRerankProvider) -> FanOutUnionRerankSearch:
    return FanOutUnionRerankSearch(
        strategy,
        provider,
        CrossEncoderRerankConfig(candidate_limit=50),
        union_candidate_limit=50,
    )


def test_union_covers_paths_found_only_by_a_rephrasing():
    strategy = StubStrategy(
        {
            "original": [result("a1", "a.py", 0.9), result("b1", "b.py", 0.5)],
            "rephrased": [result("c1", "c.py", 0.8)],
        }
    )
    provider = StubRerankProvider(order_by_path=["c.py", "a.py", "b.py"])
    paths = make_search(strategy, provider).paths(["original", "rephrased"], 3, 10)

    assert paths == ["c.py", "a.py", "b.py"]
    assert strategy.queries == ["original", "rephrased"]


def test_single_cross_encoder_pass_over_the_whole_union():
    strategy = StubStrategy(
        {
            "q1": [result("a1", "a.py", 0.9)],
            "q2": [result("b1", "b.py", 0.8)],
            "q3": [result("c1", "c.py", 0.7)],
        }
    )
    provider = StubRerankProvider(order_by_path=["a.py", "b.py", "c.py"])
    make_search(strategy, provider).paths(["q1", "q2", "q3"], 3, 10)

    assert len(provider.calls) == 1
    assert provider.calls[0] == ("q1", 3)


def test_paths_are_deduplicated_across_chunks_of_the_same_file():
    strategy = StubStrategy(
        {
            "q1": [result("a1", "a.py", 0.9), result("a2", "a.py", 0.8)],
            "q2": [result("b1", "b.py", 0.7)],
        }
    )
    provider = StubRerankProvider(order_by_path=["a.py", "a.py", "b.py"])
    paths = make_search(strategy, provider).paths(["q1", "q2"], 10, 10)

    assert paths == ["a.py", "b.py"]


def test_rerank_failure_falls_back_to_fused_union_order():
    strategy = StubStrategy(
        {
            "q1": [result("a1", "a.py", 0.9), result("b1", "b.py", 0.5)],
            "q2": [result("b1", "b.py", 0.9)],
        }
    )
    paths = make_search(strategy, StubRerankProvider(fail=True)).paths(["q1", "q2"], 10, 10)

    assert paths == ["b.py", "a.py"]


def test_empty_queries_return_no_paths():
    strategy = StubStrategy({})
    assert make_search(strategy, StubRerankProvider()).paths(["  "], 10, 10) == []


def test_parallel_probe_searches_reduce_elapsed_time_and_preserve_query_order():
    strategy = DelayedStrategy({query: [result(query, f"{query}.py", 1.0)] for query in ("q1", "q2", "q3")})
    search = FanOutUnionRerankSearch(
        strategy,
        StubRerankProvider(),
        CrossEncoderRerankConfig(candidate_limit=50),
        union_candidate_limit=50,
        max_workers=3,
        parallel_probes=True,
    )

    started = time.perf_counter()
    ranked = search._probe(["q1", "q2", "q3"], 10)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.08
    assert [items[0].item.path for items in ranked] == ["q1.py", "q2.py", "q3.py"]


def test_serial_probe_searches_preserve_order_and_honor_serial_mode():
    strategy = DelayedStrategy({query: [result(query, f"{query}.py", 1.0)] for query in ("q1", "q2", "q3")})
    search = FanOutUnionRerankSearch(
        strategy,
        StubRerankProvider(),
        CrossEncoderRerankConfig(candidate_limit=50),
        union_candidate_limit=50,
        max_workers=3,
        parallel_probes=False,
    )

    started = time.perf_counter()
    ranked = search._probe(["q1", "q2", "q3"], 10)
    elapsed = time.perf_counter() - started

    assert elapsed >= 0.08
    assert strategy.queries == ["q1", "q2", "q3"]
    assert [items[0].item.path for items in ranked] == ["q1.py", "q2.py", "q3.py"]

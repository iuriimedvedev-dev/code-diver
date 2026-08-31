from __future__ import annotations

import pytest

from code_diver.domain import CodeItem, SearchResult
from code_diver.strategies.dual_collection_vector_retrieval_strategy import DualCollectionVectorRetrievalStrategy

pytestmark = pytest.mark.unit


class FakeLane:
    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> list[SearchResult]:
        self.calls.append((query, limit))
        return self.results[:limit]


def _item(path: str, kind: str, suffix: str = "a") -> CodeItem:
    return CodeItem(
        id=f"{path}::{kind}#{suffix}",
        path=path,
        title=f"{path}::{kind}",
        content=f"{kind}:{suffix}",
        metadata={"index_kind": kind},
    )


def test_rrf_file_fusion_unions_disjoint_paths_and_keeps_kinds() -> None:
    primary = FakeLane(
        [
            SearchResult(item=_item("src/a.py", "file_summary", "p"), score=0.9),
            SearchResult(item=_item("src/a.py", "file_manifest", "p"), score=0.8),
            SearchResult(item=_item("src/only_primary.py", "file_summary", "p"), score=0.7),
        ]
    )
    secondary = FakeLane(
        [
            SearchResult(item=_item("src/b.py", "file_summary", "s"), score=0.95),
            SearchResult(item=_item("src/only_secondary.py", "file_summary", "s"), score=0.6),
            SearchResult(item=_item("src/a.py", "file_summary", "s"), score=0.5),
        ]
    )
    strategy = DualCollectionVectorRetrievalStrategy(primary, secondary, fusion="rrf", rrf_k=60)

    results = strategy.search("where is auth?", limit=10)

    assert primary.calls == [("where is auth?", 10)]
    assert secondary.calls == [("where is auth?", 10)]
    paths = [result.item.path for result in results]
    # Both collections contribute unique paths.
    assert "src/only_primary.py" in paths
    assert "src/only_secondary.py" in paths
    assert "src/a.py" in paths
    assert "src/b.py" in paths
    # Overlapping path keeps both kinds; primary wins the summary tie on equal treatment by score pick.
    a_results = [result for result in results if result.item.path == "src/a.py"]
    assert {result.item.metadata["index_kind"] for result in a_results} == {"file_summary", "file_manifest"}
    summary = next(result for result in a_results if result.item.metadata["index_kind"] == "file_summary")
    assert summary.item.id.endswith("#p")
    # Shared path outranks single-list tails via double RRF credit.
    assert paths.index("src/a.py") < paths.index("src/only_secondary.py")


def test_max_fusion_prefers_higher_raw_score_path() -> None:
    primary = FakeLane([SearchResult(item=_item("src/low.py", "file_summary", "p"), score=0.4)])
    secondary = FakeLane([SearchResult(item=_item("src/high.py", "file_summary", "s"), score=0.9)])
    strategy = DualCollectionVectorRetrievalStrategy(primary, secondary, fusion="max", rrf_k=60)

    results = strategy.search("query", limit=5)

    assert [result.item.path for result in results] == ["src/high.py", "src/low.py"]


def test_rrf_boosts_shared_path_via_double_credit() -> None:
    primary = FakeLane(
        [
            SearchResult(item=_item("src/shared.py", "file_summary", "p"), score=0.55),
            SearchResult(item=_item("src/only_p.py", "file_summary", "p"), score=0.99),
        ]
    )
    secondary = FakeLane(
        [
            SearchResult(item=_item("src/shared.py", "file_summary", "s"), score=0.50),
            SearchResult(item=_item("src/only_s.py", "file_summary", "s"), score=0.40),
        ]
    )
    strategy = DualCollectionVectorRetrievalStrategy(primary, secondary, fusion="rrf", rrf_k=60)

    results = strategy.search("q", limit=5)

    assert results[0].item.path == "src/shared.py"
    # primary ranks only_p first (0.99 > 0.55) so shared is rank 2 there; rank 1 on secondary.
    expected = 1.0 / (60 + 2) + 1.0 / (60 + 1) + 0.55 * 1e-9
    assert results[0].score == pytest.approx(expected, abs=1e-9)
    assert {result.item.path for result in results} == {"src/shared.py", "src/only_p.py", "src/only_s.py"}


def test_union_preserves_primary_order_and_appends_new_paths() -> None:
    primary = FakeLane(
        [
            SearchResult(item=_item("src/a.py", "file_summary", "p"), score=0.9),
            SearchResult(item=_item("src/b.py", "file_summary", "p"), score=0.8),
        ]
    )
    secondary = FakeLane(
        [
            SearchResult(item=_item("src/a.py", "file_summary", "s"), score=0.95),
            SearchResult(item=_item("src/c.py", "file_summary", "s"), score=0.7),
            SearchResult(item=_item("src/c.py", "file_manifest", "s"), score=0.6),
        ]
    )
    strategy = DualCollectionVectorRetrievalStrategy(primary, secondary, fusion="union", rrf_k=60)

    results = strategy.search("q", limit=10)

    assert [result.item.path for result in results] == ["src/a.py", "src/b.py", "src/c.py", "src/c.py"]
    assert results[0].item.id.endswith("#p")
    assert results[0].score == 0.9
    assert results[2].item.metadata["index_kind"] == "file_summary"
    assert results[3].item.metadata["index_kind"] == "file_manifest"


def test_union_keeps_all_primary_and_appends_secondary_even_past_limit() -> None:
    primary = FakeLane(
        [SearchResult(item=_item(f"src/p{i}.py", "file_summary", "p"), score=1.0 - i * 0.01) for i in range(8)]
    )
    secondary = FakeLane(
        [SearchResult(item=_item(f"src/s{i}.py", "file_summary", "s"), score=0.5 - i * 0.01) for i in range(4)]
    )
    strategy = DualCollectionVectorRetrievalStrategy(primary, secondary, fusion="union", rrf_k=60)

    results = strategy.search("q", limit=8)

    paths = [result.item.path for result in results]
    assert paths[:8] == [f"src/p{i}.py" for i in range(8)]
    assert any(path.startswith("src/s") for path in paths)
    assert len(results) > 8

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from code_diver.domain import CodeItem
from code_diver.strategies.hybrid_item_profiler import HybridItemProfiler
from code_diver.strategies.hybrid_lexical_index import HybridLexicalIndex


def make_index() -> HybridLexicalIndex:
    items = [
        CodeItem(
            id=f"id-{index}",
            path=f"src/module_{index}.py",
            title=f"open project {index}",
            content="def open_project(): return manager.open(path)",
            metadata={},
        )
        for index in range(5)
    ]
    return HybridLexicalIndex(items, HybridItemProfiler())


def test_bm25_scores_do_not_rebuild_native_snapshot_per_query(monkeypatch):
    index = make_index()
    calls = {"count": 0}
    original = index._tf_as_dict

    def counted():
        calls["count"] += 1
        return original()

    monkeypatch.setattr(index, "_tf_as_dict", counted)
    monkeypatch.setattr("code_diver.native_search.native_module", lambda: None)

    index.bm25_scores(("open", "project"), k1=1.2, b=0.75)
    index.bm25_scores(("manager",), k1=1.2, b=0.75)

    assert calls["count"] == 0


def test_native_inputs_snapshot_is_built_once_and_is_stable():
    index = make_index()
    first = index._native_inputs()
    second = index._native_inputs()
    assert first is second
    assert first[0] == index._tf_as_dict()
    assert first[1] == index._dl_as_dict()


def test_native_inputs_is_thread_safe_under_concurrent_scoring():
    index = make_index()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda _: index.bm25_scores(("open", "project"), k1=1.2, b=0.75), range(8))
        )
    assert all(item == results[0] for item in results)
    assert results[0]

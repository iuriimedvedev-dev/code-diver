from __future__ import annotations

import time
from threading import Lock

import pytest

from code_diver.agent.h3_search_tool_handler import H3SearchToolHandler
from code_diver.domain import CodeItem, CodeItemIndexKindResolver, SearchResult

pytestmark = pytest.mark.unit


class Embedder:
    def __init__(self) -> None:
        self.calls = 0

    def embed_query(self, query: str) -> list[float]:
        self.calls += 1
        return [1.0]


class KindStore:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.lock = Lock()

    def search_by_index_kind(self, vector: list[float], limit: int, kind: str) -> list[SearchResult]:
        with self.lock:
            self.started.append(kind)
        time.sleep(0.03)
        item = CodeItem(id=kind, path=f"{kind}.py", title=kind, content=kind)
        return [SearchResult(item, 1.0)]


def make_handler(provider: Embedder, store: KindStore) -> H3SearchToolHandler:
    handler = H3SearchToolHandler.__new__(H3SearchToolHandler)
    handler.provider = provider
    handler.vector_store = store
    handler.kind_resolver = CodeItemIndexKindResolver()
    handler.parallel_vector_lanes = True
    return handler


def test_fast_h3_parallel_flag_reuses_one_embedding_and_keeps_lane_order() -> None:
    provider = Embedder()
    store = KindStore()
    handler = make_handler(provider, store)

    started = time.perf_counter()
    raw, groups, calls = handler._fast_profile_groups("auth", 10)
    elapsed = time.perf_counter() - started

    assert provider.calls == 1
    assert calls == 2
    assert [group[0][0]["source"] for group in groups] == ["h3:fast_manifest", "h3:fast_summary"]
    assert [row["source"] for row in raw] == ["h3:fast_manifest", "h3:fast_summary"]
    assert set(store.started) == {"file_manifest", "file_summary"}
    assert elapsed < 0.055

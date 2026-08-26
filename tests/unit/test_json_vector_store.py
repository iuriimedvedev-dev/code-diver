from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.domain import CodeItem
from code_diver.store import IndexStoreError, JsonVectorStore

pytestmark = pytest.mark.unit


def test_json_vector_store_round_trips_metadata_and_search(tmp_path: Path) -> None:
    store = JsonVectorStore(tmp_path / "index.json")
    items = [
        CodeItem(id="a", path="a.py", title="A", content="alpha"),
        CodeItem(id="b", path="b.py", title="B", content="beta"),
    ]

    store.save(root=tmp_path, provider="hash", model="test", dimensions=2, items=items, vectors=[[1, 0], [0, 1]])

    assert store.exists()
    assert store.metadata() == {"provider": "hash", "model": "test", "dimensions": 2}
    assert store.search([0, 1], limit=1)[0].item.id == "b"


def test_json_vector_store_rejects_item_vector_mismatch(tmp_path: Path) -> None:
    store = JsonVectorStore(tmp_path / "index.json")

    with pytest.raises(IndexStoreError, match="Item/vector mismatch"):
        store.save(
            root=tmp_path,
            provider="hash",
            model="test",
            dimensions=2,
            items=[CodeItem(id="a", path="a.py", title="A", content="alpha")],
            vectors=[],
        )


def test_json_vector_store_save_invalidates_search_cache(tmp_path: Path) -> None:
    store = JsonVectorStore(tmp_path / "index.json")
    first = CodeItem(id="first", path="first.py", title="First", content="first")
    second = CodeItem(id="second", path="second.py", title="Second", content="second")

    store.save(root=tmp_path, provider="hash", model="test", dimensions=2, items=[first], vectors=[[1, 0]])
    assert store.search([1, 0], limit=1)[0].item.id == "first"

    store.save(root=tmp_path, provider="hash", model="test", dimensions=2, items=[second], vectors=[[0, 1]])

    assert store.search([0, 1], limit=1)[0].item.id == "second"
    assert store.count_items() == 1


def test_json_vector_store_kind_search_reuses_partition_and_vectors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = JsonVectorStore(tmp_path / "index.json")
    symbol = CodeItem(id="symbol", path="symbol.py", title="Symbol", content="symbol", metadata={"index_kind": "symbol"})
    summary = CodeItem(
        id="summary", path="summary.py", title="Summary", content="summary", metadata={"index_kind": "file_summary"}
    )
    store.save(root=tmp_path, provider="hash", model="test", dimensions=2, items=[symbol, summary], vectors=[[1, 0], [0, 1]])

    loads = 0
    original_load = store._load

    def counting_load() -> dict[str, object]:
        nonlocal loads
        loads += 1
        return original_load()

    monkeypatch.setattr(store, "_load", counting_load)
    assert store.search_by_index_kind([1, 0], limit=1, index_kind="symbol")[0].item.id == "symbol"
    loads_after_first_search = loads
    assert store.search_by_index_kind([1, 0], limit=1, index_kind="symbol")[0].item.id == "symbol"
    assert loads == loads_after_first_search

    replacement = CodeItem(
        id="replacement", path="replacement.py", title="Replacement", content="replacement", metadata={"index_kind": "symbol"}
    )
    store.save(root=tmp_path, provider="hash", model="test", dimensions=2, items=[replacement], vectors=[[0, 1]])

    assert store.search_by_index_kind([0, 1], limit=1, index_kind="symbol")[0].item.id == "replacement"

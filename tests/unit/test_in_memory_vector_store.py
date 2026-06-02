from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.domain import CodeItem
from code_diver.store import InMemoryVectorStore, IndexStoreError


pytestmark = pytest.mark.unit


def test_in_memory_vector_store_searches_saved_vectors() -> None:
    store = InMemoryVectorStore()
    items = [
        CodeItem(id="a", path="a.py", title="A", content="alpha"),
        CodeItem(id="b", path="b.py", title="B", content="beta"),
    ]

    store.save(
        root=Path("."),
        provider="test",
        model="embedding",
        dimensions=2,
        items=items,
        vectors=[[1.0, 0.0], [0.0, 1.0]],
    )

    results = store.search([0.9, 0.1], limit=2)

    assert store.exists() is True
    assert store.count_items() == 2
    assert store.metadata() == {"provider": "test", "model": "embedding", "dimensions": 2}
    assert [result.item.id for result in results] == ["a", "b"]


def test_in_memory_vector_store_rejects_item_vector_mismatch() -> None:
    store = InMemoryVectorStore()

    with pytest.raises(IndexStoreError, match="Item/vector mismatch"):
        store.save(root=Path("."), provider="test", model="embedding", dimensions=2, items=[], vectors=[[1.0]])

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

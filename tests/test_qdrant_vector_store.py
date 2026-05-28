from __future__ import annotations

import pytest

from code_diver.domain import CodeItem
from code_diver.store import QdrantVectorStore


pytestmark = pytest.mark.unit


def test_qdrant_vector_store_searches_in_memory_collection(tmp_path) -> None:
    store = QdrantVectorStore(location=":memory:", collection="test_code_diver")
    items = [
        CodeItem(id="auth.py#1", path="auth.py", title="auth", content="authenticate user password"),
        CodeItem(id="billing.py#1", path="billing.py", title="billing", content="charge invoice"),
    ]
    vectors = [[1.0, 0.0], [0.0, 1.0]]

    store.save(root=tmp_path, provider="hash", model="test", dimensions=2, items=items, vectors=vectors)

    assert store.exists()
    assert store.metadata()["model"] == "test"
    results = store.search([1.0, 0.0], limit=1)
    assert results[0].item.path == "auth.py"

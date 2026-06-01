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


def test_qdrant_vector_store_searches_embedded_path_collection(tmp_path) -> None:
    store = QdrantVectorStore(location=str(tmp_path / "qdrant"), collection="test_code_diver_path")
    items = [CodeItem(id="auth.py#1", path="auth.py", title="auth", content="authenticate user")]

    store.save(root=tmp_path, provider="hash", model="test", dimensions=2, items=items, vectors=[[1.0, 0.0]])

    assert store.exists()
    assert store.search([1.0, 0.0], limit=1)[0].item.path == "auth.py"


def test_qdrant_vector_store_searches_by_index_kind(tmp_path) -> None:
    store = QdrantVectorStore(location=":memory:", collection="test_code_diver_kind")
    items = [
        CodeItem(
            id="chunk",
            path="auth.py",
            title="auth chunk",
            content="authorize",
            metadata={"index_kind": "chunk"},
        ),
        CodeItem(
            id="summary",
            path="auth.py",
            title="auth summary",
            content="authorize",
            metadata={"index_kind": "file_summary"},
        ),
    ]

    store.save(root=tmp_path, provider="hash", model="test", dimensions=2, items=items, vectors=[[1.0, 0.0], [1.0, 0.0]])

    results = store.search_by_index_kind([1.0, 0.0], limit=5, index_kind="file_summary")

    assert [result.item.id for result in results] == ["summary"]

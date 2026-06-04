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


def test_qdrant_vector_store_keeps_previous_index_when_staging_replace_fails(tmp_path, monkeypatch) -> None:
    store = QdrantVectorStore(location=":memory:", collection="test_code_diver_staging")
    old_items = [CodeItem(id="old.py#1", path="old.py", title="old", content="old auth")]
    new_items = [CodeItem(id="new.py#1", path="new.py", title="new", content="new auth")]

    store.save(root=tmp_path, provider="hash", model="old", dimensions=2, items=old_items, vectors=[[1.0, 0.0]])

    original_upsert = store._upsert_points_to_collection

    def fail_for_new_collection(collection, *args, **kwargs):
        if collection != store.collection:
            raise RuntimeError("staging write failed")
        return original_upsert(collection, *args, **kwargs)

    monkeypatch.setattr(store, "_upsert_points_to_collection", fail_for_new_collection)

    with pytest.raises(RuntimeError, match="staging write failed"):
        store.save(root=tmp_path, provider="hash", model="new", dimensions=2, items=new_items, vectors=[[0.0, 1.0]])

    assert store.metadata()["model"] == "old"
    assert store.search([1.0, 0.0], limit=1)[0].item.path == "old.py"


def test_qdrant_vector_store_deletes_collections_by_prefix(tmp_path) -> None:
    store = QdrantVectorStore(location=":memory:", collection="code_diver__repo_a__emb_qwen")
    item = CodeItem(id="a.py#1", path="a.py", title="a", content="auth")
    store.save(root=tmp_path, provider="hash", model="a", dimensions=2, items=[item], vectors=[[1.0, 0.0]])
    store.collection = "code_diver__repo_b__emb_qwen"
    other = CodeItem(id="b.py#1", path="b.py", title="b", content="billing")
    store.save(root=tmp_path, provider="hash", model="b", dimensions=2, items=[other], vectors=[[0.0, 1.0]])

    deleted = store.delete_collections_with_prefix("code_diver__repo_a")

    assert "code_diver__repo_a__emb_qwen" in deleted
    store.collection = "code_diver__repo_a__emb_qwen"
    assert store.exists() is False
    store.collection = "code_diver__repo_b__emb_qwen"
    assert store.exists() is True

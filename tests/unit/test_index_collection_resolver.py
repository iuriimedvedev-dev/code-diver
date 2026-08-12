from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.config import AppConfig
from code_diver.config.embedding_config import EmbeddingConfig
from code_diver.config.qdrant_config import QdrantConfig
from code_diver.config.storage_config import StorageConfig
from code_diver.services import IndexCollectionResolver

pytestmark = pytest.mark.unit


def test_index_collection_resolver_namespaces_default_qdrant_collection(tmp_path: Path) -> None:
    config = AppConfig(
        root=tmp_path,
        storage=StorageConfig(provider="qdrant", qdrant=QdrantConfig(collection="code_diver")),
        embedding=EmbeddingConfig(
            provider="openai_compatible",
            model="mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ",
            dimensions=None,
            max_input_chars=400,
        ),
    )

    resolved = IndexCollectionResolver().resolve(config)

    assert resolved.storage.qdrant.collection.startswith(f"code_diver__repo_{tmp_path.name.lower()}_")
    assert "__emb_openai_compatible_mlx_community_qwen3_embedding_0_6b_" in resolved.storage.qdrant.collection
    assert resolved.storage.qdrant.collection != config.storage.qdrant.collection


def test_index_collection_resolver_preserves_explicit_collection(tmp_path: Path) -> None:
    config = AppConfig(
        root=tmp_path,
        storage=StorageConfig(provider="qdrant", qdrant=QdrantConfig(collection="manual_collection")),
    )

    resolved = IndexCollectionResolver().resolve(config)

    assert resolved.storage.qdrant.collection == "manual_collection"


def test_index_collection_resolver_skips_non_qdrant_storage(tmp_path: Path) -> None:
    config = AppConfig(root=tmp_path)

    resolved = IndexCollectionResolver().resolve(config)

    assert resolved is config

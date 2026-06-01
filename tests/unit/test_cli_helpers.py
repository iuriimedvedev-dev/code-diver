from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.cli import config_for_indexing_hypothesis, make_embedding_provider, make_search_tool_handler
from code_diver.config import AppConfig
from code_diver.config.embedding_config import EmbeddingConfig
from code_diver.config.graph_config import GraphConfig
from code_diver.config.qdrant_config import QdrantConfig
from code_diver.config.storage_config import StorageConfig
from code_diver.domain import CodeItem, SearchResult


pytestmark = pytest.mark.unit


class FakeStrategy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> list[SearchResult]:
        self.calls.append((query, limit))
        return [
            SearchResult(
                item=CodeItem(
                    id="src/app.py#abc",
                    path="src/app.py",
                    title="src/app.py:1-10",
                    content="def app(): pass",
                    start_line=1,
                    end_line=10,
                    metadata={"index_kind": "chunk"},
                ),
                score=0.9,
            )
        ]


def test_config_for_indexing_hypothesis_isolates_qdrant_json_and_graph_artifacts(tmp_path: Path) -> None:
    config = AppConfig(
        artifact=tmp_path / "index.json",
        storage=StorageConfig(qdrant=QdrantConfig(collection="base_collection")),
        graph=GraphConfig(artifact=tmp_path / "graph.json"),
    )

    isolated = config_for_indexing_hypothesis(config, "ai_index_rg_only", "run123")

    assert isolated.storage.qdrant.collection == "base_collection_ai_index_rg_only_run123"
    assert isolated.artifact == tmp_path / "index_ai_index_rg_only_run123.json"
    assert isolated.graph.artifact == tmp_path / "graph_ai_index_rg_only_run123.json"
    assert config.artifact == tmp_path / "index.json"
    assert config.graph.artifact == tmp_path / "graph.json"


def test_make_search_tool_handler_reuses_injected_strategy() -> None:
    strategy = FakeStrategy()
    handler = make_search_tool_handler(strategy)

    payload = handler("where is app?", 5)
    second_payload = handler("where is cli?", 3)

    assert '"path": "src/app.py"' in payload
    assert '"indexKind": "chunk"' in payload
    assert '"score": 0.9' in second_payload
    assert strategy.calls == [("where is app?", 5), ("where is cli?", 3)]


def test_openai_compatible_provider_does_not_inherit_store_dimensions() -> None:
    config = AppConfig(
        embedding=EmbeddingConfig(
            provider="openai_compatible",
            model="local-embed",
            dimensions=None,
            api_key="local",
            url="http://127.0.0.1:8001/v1/embeddings",
        )
    )

    provider = make_embedding_provider(config, {"dimensions": 1024})

    assert provider.dimensions == 0
    assert provider.send_dimensions is False

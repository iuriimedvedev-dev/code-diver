from __future__ import annotations

from pathlib import Path
from argparse import Namespace

import pytest

from code_diver.cli import (
    cmd_monitor,
    config_for_indexing_hypothesis,
    current_repo_collection_prefix,
    direct_search_eval_result,
    direct_search_metrics,
    make_embedding_provider,
    make_ephemeral_search_tool_handler,
    make_search_tool_handler,
    prepare_index_collection,
)
from code_diver.config import AppConfig
from code_diver.config.embedding_config import EmbeddingConfig
from code_diver.config.graph_config import GraphConfig
from code_diver.config.scanner_config import ScannerConfig
from code_diver.config.qdrant_config import QdrantConfig
from code_diver.config.storage_config import StorageConfig
from code_diver.config.trace_config import TraceConfig
from code_diver.domain import CodeItem, EvalCase, SearchResult


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


class FakeEmbeddingProvider:
    name = "test"
    model = "keyword"
    dimensions = 3

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, query: str) -> list[float]:
        return self._embed(query)

    def _embed(self, text: str) -> list[float]:
        lowered = text.lower()
        return [
            float("update" in lowered),
            float("delete" in lowered),
            float("user" in lowered),
        ]


class FakeClosableVectorStore:
    def __init__(self, exists: bool) -> None:
        self._exists = exists
        self.deleted_prefixes: list[str] = []
        self.closed = False

    def exists(self) -> bool:
        return self._exists

    def delete_collections_with_prefix(self, prefix: str) -> list[str]:
        self.deleted_prefixes.append(prefix)
        return [prefix]

    def close(self) -> None:
        self.closed = True


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


def test_prepare_index_collection_rejects_existing_collection_without_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeClosableVectorStore(exists=True)
    config = AppConfig(
        root=tmp_path,
        storage=StorageConfig(provider="qdrant", qdrant=QdrantConfig(collection="code_diver__repo_demo__emb_qwen")),
    )
    monkeypatch.setattr("code_diver.cli.make_vector_store", lambda config: store)

    with pytest.raises(RuntimeError, match="--update-index"):
        prepare_index_collection(Namespace(update_index=False, override_repo=False, reindex=False), config, progress=False)

    assert store.closed is True


def test_prepare_index_collection_allows_update_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeClosableVectorStore(exists=True)
    config = AppConfig(root=tmp_path, storage=StorageConfig(provider="qdrant"))
    monkeypatch.setattr("code_diver.cli.make_vector_store", lambda config: store)

    prepare_index_collection(Namespace(update_index=True, override_repo=False, reindex=False), config, progress=False)

    assert store.deleted_prefixes == []
    assert store.closed is True


def test_prepare_index_collection_override_deletes_repo_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeClosableVectorStore(exists=True)
    config = AppConfig(
        root=tmp_path,
        storage=StorageConfig(provider="qdrant", qdrant=QdrantConfig(collection="code_diver__repo_demo__emb_qwen")),
    )
    monkeypatch.setattr("code_diver.cli.make_vector_store", lambda config: store)

    prepare_index_collection(Namespace(update_index=False, override_repo=True, reindex=False), config, progress=False)

    assert store.deleted_prefixes == ["code_diver__repo_demo"]
    assert store.closed is True


def test_current_repo_collection_prefix_falls_back_to_collection_name() -> None:
    config = AppConfig(storage=StorageConfig(qdrant=QdrantConfig(collection="manual_collection")))

    assert current_repo_collection_prefix(config) == "manual_collection"


def test_make_search_tool_handler_reuses_injected_strategy() -> None:
    strategy = FakeStrategy()
    handler = make_search_tool_handler(strategy)

    payload = handler("where is app?", 5)
    second_payload = handler("where is cli?", 3)

    assert '"path": "src/app.py"' in payload
    assert '"indexKind": "chunk"' in payload
    assert '"score": 0.9' in second_payload
    assert strategy.calls == [("where is app?", 5), ("where is cli?", 3)]


def test_make_ephemeral_search_tool_handler_returns_timing_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "src" / "users.py"
    source.parent.mkdir()
    source.write_text(
        "class UserController:\n"
        "    def update_user(self, user_id):\n"
        "        return user_id\n",
        encoding="utf-8",
    )
    config = AppConfig(
        root=tmp_path,
        scanner=ScannerConfig(include=["**/*.py"], line_chunks=False, structural_chunks=True, symbol_chunks=True),
    )
    monkeypatch.setattr("code_diver.cli.make_embedding_provider", lambda config, metadata=None: FakeEmbeddingProvider())

    payload = make_ephemeral_search_tool_handler(config)("update user", ["src/users.py"], 3, {})

    assert payload["candidates"][0]["path"] == "src/users.py"
    assert payload["candidates"][0]["breadcrumb"].startswith("[file: src/users.py]")
    assert payload["metrics"]["temporary_vectors"] > 0
    assert payload["metrics"]["ephemeral_build_ms"] >= 0.0
    assert payload["metrics"]["ephemeral_query_ms"] >= 0.0


def test_direct_search_eval_result_classifies_query_bucket() -> None:
    result = direct_search_eval_result(
        EvalCase(id="case", query="where is command dispatched", expected=["src/commands.py"]),
        ["src/commands.py#handler"],
        10,
    )

    assert result.bucket != "unknown"


def test_direct_search_eval_result_matches_glob_expected_file_patterns() -> None:
    result = direct_search_eval_result(
        EvalCase(id="case", query="where is plugin descriptor", expected=["glob:**/resources/META-INF/plugin.xml"]),
        ["plugins/htmltools/resources/META-INF/plugin.xml"],
        10,
    )

    assert result.hit is True
    assert result.file_hit is True


def test_direct_search_metrics_report_file_hit_at_k_after_file_deduplication() -> None:
    result = direct_search_eval_result(
        EvalCase(id="case", query="find target", expected=["src/target.py"]),
        ["src/wrong.py#1", "src/wrong.py#2", "src/wrong.py#3", "src/target.py#1"],
        4,
    )

    metrics = direct_search_metrics([result], [1.0], 4)

    assert metrics["hit_rate@3"] == 0.0
    assert metrics["file_hit_rate@3"] == 1.0
    assert metrics["hit_rate@5"] == 1.0
    assert metrics["file_hit_rate@5"] == 1.0


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


def test_cmd_monitor_requires_explicit_trace_when_tracing_is_disabled(capsys) -> None:
    config = AppConfig(trace=TraceConfig(enabled=False, artifact=Path("old-trace.jsonl"), include_prompts=False))

    exit_code = cmd_monitor(Namespace(trace=None, refresh=0.1, max_events=10), config)

    assert exit_code == 1
    assert "Tracing is disabled" in capsys.readouterr().out

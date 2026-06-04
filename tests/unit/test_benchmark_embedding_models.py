from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from code_diver.config import AppConfig
from code_diver.config.graph_config import GraphConfig
from code_diver.config.qdrant_config import QdrantConfig
from code_diver.config.storage_config import StorageConfig
from code_diver.config.trace_config import TraceConfig

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "benchmark_embedding_models.py"
_SPEC = importlib.util.spec_from_file_location("benchmark_embedding_models", _SCRIPT_PATH)
assert _SPEC is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_MODULE)
EmbeddingBenchmarkRunner = _MODULE.EmbeddingBenchmarkRunner


pytestmark = pytest.mark.unit


def test_embedding_benchmark_isolates_json_artifacts_per_model(tmp_path: Path) -> None:
    runner = EmbeddingBenchmarkRunner.__new__(EmbeddingBenchmarkRunner)
    runner.base_config = AppConfig(
        artifact=tmp_path / "index.json",
        storage=StorageConfig(qdrant=QdrantConfig(collection="base_collection")),
        graph=GraphConfig(artifact=tmp_path / "graph.json"),
        trace=TraceConfig(artifact=tmp_path / "trace.jsonl"),
    )
    runner.run_id = "run123"

    config = runner._config_for_model(
        {
            "name": "embedding_a",
            "provider": "hash",
            "model": "hash",
        }
    )

    assert config.artifact == tmp_path / "index_embedding_a_run123.json"
    assert config.graph.artifact == tmp_path / "graph_embedding_a_run123.json"
    assert config.trace.artifact == tmp_path / "trace_embedding_a_run123.jsonl"
    assert config.storage.qdrant.collection == "base_collection_embedding_a_run123"
    assert runner.base_config.artifact == tmp_path / "index.json"

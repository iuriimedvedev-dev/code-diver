from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.config import ConfigLoader


pytestmark = pytest.mark.unit


def test_config_loader_maps_yaml_to_typed_config(tmp_path: Path) -> None:
    config_path = tmp_path / "code-diver.yml"
    config_path.write_text(
        f"""
root: {tmp_path}/repo
artifact: {tmp_path}/index.json
storage:
  provider: qdrant
  qdrant:
    location: ":memory:"
    collection: custom_collection
embedding:
  provider: openai_compatible
  model: local-embed
  url: http://127.0.0.1:1234/v1/embeddings
  project: embed-project
  location: europe-west4
  dimensions: 64
  workers: 3
  max_input_chars: 4096
generation:
  provider: openai_compatible
  model: local-chat
  url: http://127.0.0.1:1234/v1/chat/completions
  project: gen-project
  location: us-central1
  fallback_models: [gemini-2.5-flash]
  temperature: 0.2
  thinking_budget: 256
  api_version: v1alpha
  timeout_ms: 12345
indexing:
  mode: ai
  ai:
    max_files: 5
    max_items: 8
    max_context_chars: 1000
    discovery_patterns: ["class ", "interface "]
pi:
  binary: npx
  launcher_args: [-y, "@earendil-works/pi-coding-agent"]
  fallback_models: [google/gemini-3-flash-preview, google/gemini-2.5-flash]
  tools: [read, code_diver_search]
  toolsets:
    grep_only: [code_diver_tree, code_diver_rg, code_diver_read]
scanner:
  include: ["*.py"]
  chunk_lines: 10
  symbol_chunks: true
search:
  strategy: recursive
  limit: 7
recursive_search:
  rounds: 3
  branch_limit: 2
  limit: 4
graph:
  artifact: {tmp_path}/graph.json
  expansion_depth: 2
  ast_enabled: false
trace:
  enabled: true
  artifact: {tmp_path}/trace.jsonl
  include_prompts: false
ui:
  editor:
    command: vim
    args: ["+{{line}}", "{{path}}"]
evaluation:
  dataset: {tmp_path}/eval.jsonl
experiments:
  suite: custom-suite
  strategies: [vector, graph]
  hypotheses:
    - name: grep_only
      toolset: grep_only
      description: grep without vectors
    - name: vector_qdrant
      strategy: vector
      tools: [code_diver_search, code_diver_read]
metrics:
  enabled: true
  url: http://clickhouse:8123
  database: metrics_db
  username: writer
  password: secret
  docker_container: clickhouse-dev
  metrics_table: metrics_table
  cases_table: cases_table
  timeout_seconds: 3
  retention_days: 7
plugins:
  - plugin.py
""".strip(),
        encoding="utf-8",
    )

    config = ConfigLoader().load(config_path)

    assert config.root == tmp_path / "repo"
    assert config.storage.provider == "qdrant"
    assert config.storage.qdrant.location == ":memory:"
    assert config.storage.qdrant.collection == "custom_collection"
    assert config.embedding.provider == "openai_compatible"
    assert config.embedding.model == "local-embed"
    assert config.embedding.url == "http://127.0.0.1:1234/v1/embeddings"
    assert config.embedding.project == "embed-project"
    assert config.embedding.location == "europe-west4"
    assert config.embedding.dimensions == 64
    assert config.embedding.workers == 3
    assert config.embedding.max_input_chars == 4096
    assert config.generation.provider == "openai_compatible"
    assert config.generation.model == "local-chat"
    assert config.generation.url == "http://127.0.0.1:1234/v1/chat/completions"
    assert config.generation.project == "gen-project"
    assert config.generation.location == "us-central1"
    assert config.generation.fallback_models == ["gemini-2.5-flash"]
    assert config.generation.temperature == 0.2
    assert config.generation.thinking_budget == 256
    assert config.generation.api_version == "v1alpha"
    assert config.generation.timeout_ms == 12345
    assert config.indexing.mode == "ai"
    assert config.indexing.ai.max_files == 5
    assert config.indexing.ai.max_items == 8
    assert config.indexing.ai.max_context_chars == 1000
    assert config.indexing.ai.discovery_patterns == ["class ", "interface "]
    assert config.pi.binary == "npx"
    assert config.pi.launcher_args == ["-y", "@earendil-works/pi-coding-agent"]
    assert config.pi.fallback_models == ["google/gemini-3-flash-preview", "google/gemini-2.5-flash"]
    assert config.pi.tools == ["read", "code_diver_search"]
    assert config.pi.toolsets["grep_only"] == ["code_diver_tree", "code_diver_rg", "code_diver_read"]
    assert config.scanner.include == ["*.py"]
    assert config.scanner.chunk_lines == 10
    assert config.scanner.symbol_chunks is True
    assert config.search.strategy == "recursive"
    assert config.search.limit == 7
    assert config.recursive_search.rounds == 3
    assert config.recursive_search.branch_limit == 2
    assert config.recursive_search.limit == 4
    assert config.graph.artifact == tmp_path / "graph.json"
    assert config.graph.expansion_depth == 2
    assert config.graph.ast_enabled is False
    assert config.trace.enabled is True
    assert config.trace.artifact == tmp_path / "trace.jsonl"
    assert config.trace.include_prompts is False
    assert config.ui.editor.command == "vim"
    assert config.ui.editor.args == ["+{line}", "{path}"]
    assert config.evaluation.dataset == tmp_path / "eval.jsonl"
    assert config.experiments.suite == "custom-suite"
    assert config.experiments.strategies == ["vector", "graph"]
    assert config.experiments.hypotheses[0].name == "grep_only"
    assert config.experiments.hypotheses[0].toolset == "grep_only"
    assert config.experiments.hypotheses[1].strategy == "vector"
    assert config.experiments.hypotheses[1].tools == ["code_diver_search", "code_diver_read"]
    assert config.metrics.enabled is True
    assert config.metrics.url == "http://clickhouse:8123"
    assert config.metrics.database == "metrics_db"
    assert config.metrics.username == "writer"
    assert config.metrics.password == "secret"
    assert config.metrics.docker_container == "clickhouse-dev"
    assert config.metrics.metrics_table == "metrics_table"
    assert config.metrics.cases_table == "cases_table"
    assert config.metrics.timeout_seconds == 3
    assert config.metrics.retention_days == 7
    assert config.plugins == ["plugin.py"]


def test_config_loader_rejects_non_mapping_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "code-diver.yml"
    config_path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    with pytest.raises(ValueError, match="YAML mapping"):
        ConfigLoader().load(config_path)


def test_config_loader_rejects_invalid_list_shape(tmp_path: Path) -> None:
    config_path = tmp_path / "code-diver.yml"
    config_path.write_text("plugins: plugin.py\n", encoding="utf-8")

    with pytest.raises(ValueError, match="YAML list"):
        ConfigLoader().load(config_path)

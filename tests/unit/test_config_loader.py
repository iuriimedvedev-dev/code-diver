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
  document_prefix: "task: code retrieval | document: "
  query_prefix: "task: code retrieval | query: "
  workers: 3
  max_input_chars: 4096
generation:
  provider: openai_compatible
  model: local-chat
  url: http://127.0.0.1:1234/v1/chat/completions
  urls:
    - http://127.0.0.1:8016/v1/chat/completions
    - http://127.0.0.1:8017/v1/chat/completions
  project: gen-project
  location: us-central1
  fallback_models: [gemini-2.5-flash]
  temperature: 0.2
  thinking_budget: 256
  api_version: v1alpha
  timeout_ms: 12345
  response_format: false
  extra_body:
    enable_thinking: false
  retry_attempts: 7
  retry_base_delay_seconds: 1.5
  retry_max_delay_seconds: 33
indexing:
  mode: ai
  ai:
    max_files: 5
    max_items: 8
    max_context_chars: 1000
    discovery_patterns: ["class ", "interface "]
pi:
  binary: npm
  launcher_args: [exec, "--", pi]
  fallback_models: [google/gemini-3-flash-preview, google/gemini-2.5-flash]
  timeout_seconds: 77
  session_dir: {tmp_path}/pi-sessions
  tools: [read, code_diver_search]
  toolsets:
    grep_only: [code_diver_tree, code_diver_rg, code_diver_read]
scanner:
  include: ["*.py"]
  line_chunks: false
  chunk_lines: 10
  structural_chunks: true
  symbol_chunks: true
  symbol_body: false
  file_summary_chunks: true
  file_manifest_chunks: true
  file_api_manifest_chunks: true
  documentation_summary_chunks: true
  documentation_manifest_chunks: true
  documentation_chunk_chunks: true
  max_symbols_per_file: 5
search:
  strategy: recursive
  limit: 7
recursive_search:
  rounds: 3
  branch_limit: 2
  limit: 4
hybrid_search:
  candidate_limit: 44
  lexical_candidate_limit: 33
  vector_weight: 0.51
  lexical_weight: 0.22
  path_weight: 0.13
  symbol_weight: 0.07
  symbol_match_weight: 0.08
  graph_weight: 0.09
  file_vote_weight: 0.04
  graph_scope: file
  vector_kind_limits:
    chunk: 20
    symbol: 10
  vector_kind_multipliers:
    file_summary: 0.25
  graph_depth: 2
  graph_neighbor_limit: 11
  lexical_scoring: bm25
  fusion: rrf
  rrf_k: 42
  bm25_k1: 1.5
  bm25_b: 0.4
  routing_enabled: true
  preserve_vector_top: true
  vector_top_score_margin: 0.07
  item_kind_weights:
    file_summary: 1.2
    symbol: 1.1
  min_token_length: 4
  query_expansion_enabled: true
  query_expansion_aliases:
    auth: [authorization, token]
  stop_words: [where, handled]
llm_rerank:
  candidate_limit: 22
  rerank_limit: 3
  max_preview_chars: 333
  mode: file_first
  include_reasons: false
  preserve_top_candidate: true
  preserve_top_score_margin: 0.2
  retry_attempts: 4
  retry_base_delay_seconds: 0.5
  retry_max_delay_seconds: 5
  repository_context_path: {tmp_path}/repo-context.md
  repository_context_max_chars: 1234
cross_encoder_rerank:
  provider: llama_cpp
  model: qwen3-reranker-0.6b-q4
  url: http://127.0.0.1:8080/v1/rerank
  api_key: local-key
  candidate_limit: 17
  max_document_chars: 444
  timeout_ms: 12345
  preserve_top_candidate: true
  preserve_top_score_margin: 0.3
  skip_when_top_margin_at_least: 0.05
graph:
  artifact: {tmp_path}/graph.json
  expansion_depth: 2
  ast_enabled: false
  reference_edges_enabled: false
  call_edges_enabled: false
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
  workers: 6
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
    - name: hybrid_lexical
      strategy: hybrid
      hybrid_search:
        vector_weight: 0.3
        lexical_weight: 0.5
    - name: hybrid_rerank
      strategy: hybrid_rerank
      generation:
        provider: vertex
        model: gemini-3.1-flash-lite
        fallback_models: []
        thinking_budget: 256
      llm_rerank:
        candidate_limit: 12
        mode: precision
    - name: cross_encoder_rerank
      strategy: cross_encoder_rerank
      cross_encoder_rerank:
        model: qwen3-reranker-4b-q4
        candidate_limit: 24
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
    assert config.embedding.document_prefix == "task: code retrieval | document: "
    assert config.embedding.query_prefix == "task: code retrieval | query: "
    assert config.embedding.workers == 3
    assert config.embedding.max_input_chars == 4096
    assert config.generation.provider == "openai_compatible"
    assert config.generation.model == "local-chat"
    assert config.generation.url == "http://127.0.0.1:1234/v1/chat/completions"
    assert config.generation.urls == [
        "http://127.0.0.1:8016/v1/chat/completions",
        "http://127.0.0.1:8017/v1/chat/completions",
    ]
    assert config.generation.project == "gen-project"
    assert config.generation.location == "us-central1"
    assert config.generation.fallback_models == ["gemini-2.5-flash"]
    assert config.generation.temperature == 0.2
    assert config.generation.thinking_budget == 256
    assert config.generation.api_version == "v1alpha"
    assert config.generation.timeout_ms == 12345
    assert config.generation.response_format is False
    assert config.generation.extra_body == {"enable_thinking": False}
    assert config.generation.retry_attempts == 7
    assert config.generation.retry_base_delay_seconds == 1.5
    assert config.generation.retry_max_delay_seconds == 33
    assert config.indexing.mode == "ai"
    assert config.indexing.ai.max_files == 5
    assert config.indexing.ai.max_items == 8
    assert config.indexing.ai.max_context_chars == 1000
    assert config.indexing.ai.discovery_patterns == ["class ", "interface "]
    assert config.pi.binary == "npm"
    assert config.pi.launcher_args == ["exec", "--", "pi"]
    assert config.pi.fallback_models == ["google/gemini-3-flash-preview", "google/gemini-2.5-flash"]
    assert config.pi.timeout_seconds == 77
    assert config.pi.session_dir == tmp_path / "pi-sessions"
    assert config.pi.tools == ["read", "code_diver_search"]
    assert config.pi.toolsets["grep_only"] == ["code_diver_tree", "code_diver_rg", "code_diver_read"]
    assert config.scanner.include == ["*.py"]
    assert config.scanner.line_chunks is False
    assert config.scanner.chunk_lines == 10
    assert config.scanner.structural_chunks is True
    assert config.scanner.symbol_chunks is True
    assert config.scanner.symbol_body is False
    assert config.scanner.file_summary_chunks is True
    assert config.scanner.file_manifest_chunks is True
    assert config.scanner.file_api_manifest_chunks is True
    assert config.scanner.documentation_summary_chunks is True
    assert config.scanner.documentation_manifest_chunks is True
    assert config.scanner.documentation_chunk_chunks is True
    assert config.scanner.max_symbols_per_file == 5
    assert config.search.strategy == "recursive"
    assert config.search.limit == 7
    assert config.recursive_search.rounds == 3
    assert config.recursive_search.branch_limit == 2
    assert config.recursive_search.limit == 4
    assert config.hybrid_search.candidate_limit == 44
    assert config.hybrid_search.lexical_candidate_limit == 33
    assert config.hybrid_search.vector_weight == 0.51
    assert config.hybrid_search.lexical_weight == 0.22
    assert config.hybrid_search.path_weight == 0.13
    assert config.hybrid_search.symbol_weight == 0.07
    assert config.hybrid_search.symbol_match_weight == 0.08
    assert config.hybrid_search.graph_weight == 0.09
    assert config.hybrid_search.file_vote_weight == 0.04
    assert config.hybrid_search.graph_scope == "file"
    assert config.hybrid_search.vector_kind_limits == {"chunk": 20, "symbol": 10}
    assert config.hybrid_search.vector_kind_multipliers == {"file_summary": 0.25}
    assert config.hybrid_search.graph_depth == 2
    assert config.hybrid_search.graph_neighbor_limit == 11
    assert config.hybrid_search.lexical_scoring == "bm25"
    assert config.hybrid_search.fusion == "rrf"
    assert config.hybrid_search.rrf_k == 42
    assert config.hybrid_search.bm25_k1 == 1.5
    assert config.hybrid_search.bm25_b == 0.4
    assert config.hybrid_search.routing_enabled is True
    assert config.hybrid_search.preserve_vector_top is True
    assert config.hybrid_search.vector_top_score_margin == 0.07
    assert config.hybrid_search.item_kind_weights == {"file_summary": 1.2, "symbol": 1.1}
    assert config.hybrid_search.min_token_length == 4
    assert config.hybrid_search.query_expansion_enabled is True
    assert config.hybrid_search.query_expansion_aliases == {"auth": ["authorization", "token"]}
    assert config.hybrid_search.stop_words == ["where", "handled"]
    assert config.llm_rerank.candidate_limit == 22
    assert config.llm_rerank.rerank_limit == 3
    assert config.llm_rerank.max_preview_chars == 333
    assert config.llm_rerank.mode == "file_first"
    assert config.llm_rerank.include_reasons is False
    assert config.llm_rerank.preserve_top_candidate is True
    assert config.llm_rerank.preserve_top_score_margin == 0.2
    assert config.llm_rerank.retry_attempts == 4
    assert config.llm_rerank.retry_base_delay_seconds == 0.5
    assert config.llm_rerank.retry_max_delay_seconds == 5
    assert config.llm_rerank.repository_context_path == tmp_path / "repo-context.md"
    assert config.llm_rerank.repository_context_max_chars == 1234
    assert config.cross_encoder_rerank.provider == "llama_cpp"
    assert config.cross_encoder_rerank.model == "qwen3-reranker-0.6b-q4"
    assert config.cross_encoder_rerank.url == "http://127.0.0.1:8080/v1/rerank"
    assert config.cross_encoder_rerank.api_key == "local-key"
    assert config.cross_encoder_rerank.candidate_limit == 17
    assert config.cross_encoder_rerank.max_document_chars == 444
    assert config.cross_encoder_rerank.timeout_ms == 12345
    assert config.cross_encoder_rerank.preserve_top_candidate is True
    assert config.cross_encoder_rerank.preserve_top_score_margin == 0.3
    assert config.cross_encoder_rerank.skip_when_top_margin_at_least == 0.05
    assert config.graph.artifact == tmp_path / "graph.json"
    assert config.graph.expansion_depth == 2
    assert config.graph.ast_enabled is False
    assert config.graph.reference_edges_enabled is False
    assert config.graph.call_edges_enabled is False
    assert config.trace.enabled is True
    assert config.trace.artifact == tmp_path / "trace.jsonl"
    assert config.trace.include_prompts is False
    assert config.ui.editor.command == "vim"
    assert config.ui.editor.args == ["+{line}", "{path}"]
    assert config.evaluation.dataset == tmp_path / "eval.jsonl"
    assert config.evaluation.workers == 6
    assert config.experiments.suite == "custom-suite"
    assert config.experiments.strategies == ["vector", "graph"]
    assert config.experiments.hypotheses[0].name == "grep_only"
    assert config.experiments.hypotheses[0].toolset == "grep_only"
    assert config.experiments.hypotheses[1].strategy == "vector"
    assert config.experiments.hypotheses[1].tools == ["code_diver_search", "code_diver_read"]
    assert config.experiments.hypotheses[2].name == "hybrid_lexical"
    assert config.experiments.hypotheses[2].hybrid_search is not None
    assert config.experiments.hypotheses[2].hybrid_search.vector_weight == 0.3
    assert config.experiments.hypotheses[2].hybrid_search.lexical_weight == 0.5
    assert config.experiments.hypotheses[3].llm_rerank is not None
    assert config.experiments.hypotheses[3].generation is not None
    assert config.experiments.hypotheses[3].generation.provider == "vertex"
    assert config.experiments.hypotheses[3].generation.model == "gemini-3.1-flash-lite"
    assert config.experiments.hypotheses[3].generation.fallback_models == []
    assert config.experiments.hypotheses[3].generation.thinking_budget == 256
    assert config.experiments.hypotheses[3].llm_rerank.candidate_limit == 12
    assert config.experiments.hypotheses[3].llm_rerank.mode == "precision"
    assert config.experiments.hypotheses[4].strategy == "cross_encoder_rerank"
    assert config.experiments.hypotheses[4].cross_encoder_rerank is not None
    assert config.experiments.hypotheses[4].cross_encoder_rerank.model == "qwen3-reranker-4b-q4"
    assert config.experiments.hypotheses[4].cross_encoder_rerank.candidate_limit == 24
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


def test_config_loader_does_not_force_default_model_for_custom_embedding_provider(tmp_path: Path) -> None:
    config_path = tmp_path / "code-diver.yml"
    config_path.write_text(
        """
embedding:
  provider: hash
  dimensions: 128
""".strip(),
        encoding="utf-8",
    )

    config = ConfigLoader().load(config_path)

    assert config.embedding.provider == "hash"
    assert config.embedding.model is None
    assert config.embedding.dimensions == 128


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


def test_config_loader_hypothesis_overrides_inherit_base_sections(tmp_path: Path) -> None:
    config_path = tmp_path / "code-diver.yml"
    config_path.write_text(
        """
generation:
  provider: vertex
  model: gemini-base
  location: europe-west4
  fallback_models: [fallback-a]
  timeout_ms: 111
hybrid_search:
  candidate_limit: 80
  vector_weight: 0.6
  lexical_weight: 0.2
llm_rerank:
  candidate_limit: 30
  mode: file_first
cross_encoder_rerank:
  provider: llama_cpp
  model: qwen3-reranker-4b
  url: http://127.0.0.1:8080/v1/rerank
  candidate_limit: 10
  timeout_ms: 30000
experiments:
  hypotheses:
    - name: partial
      strategy: cross_encoder_rerank
      generation:
        model: gemini-override
      rerank_generation:
        provider: openai_compatible
        model: qwen-rerank-local
        url: http://127.0.0.1:8012/v1/chat/completions
        fallback_models: []
        thinking_budget:
        max_tokens: 1024
      hybrid_search:
        lexical_weight: 0.4
      llm_rerank:
        candidate_limit: 12
      cross_encoder_rerank:
        candidate_limit: 5
""".strip(),
        encoding="utf-8",
    )

    config = ConfigLoader().load(config_path)
    hypothesis = config.experiments.hypotheses[0]

    assert hypothesis.generation is not None
    assert hypothesis.generation.provider == "vertex"
    assert hypothesis.generation.model == "gemini-override"
    assert hypothesis.generation.location == "europe-west4"
    assert hypothesis.generation.fallback_models == ["fallback-a"]
    assert hypothesis.generation.timeout_ms == 111
    assert hypothesis.rerank_generation is not None
    assert hypothesis.rerank_generation.provider == "openai_compatible"
    assert hypothesis.rerank_generation.model == "qwen-rerank-local"
    assert hypothesis.rerank_generation.url == "http://127.0.0.1:8012/v1/chat/completions"
    assert hypothesis.rerank_generation.fallback_models == []
    assert hypothesis.rerank_generation.thinking_budget is None
    assert hypothesis.rerank_generation.max_tokens == 1024
    assert hypothesis.hybrid_search is not None
    assert hypothesis.hybrid_search.candidate_limit == 80
    assert hypothesis.hybrid_search.vector_weight == 0.6
    assert hypothesis.hybrid_search.lexical_weight == 0.4
    assert hypothesis.llm_rerank is not None
    assert hypothesis.llm_rerank.candidate_limit == 12
    assert hypothesis.llm_rerank.mode == "file_first"
    assert hypothesis.cross_encoder_rerank is not None
    assert hypothesis.cross_encoder_rerank.provider == "llama_cpp"
    assert hypothesis.cross_encoder_rerank.model == "qwen3-reranker-4b"
    assert hypothesis.cross_encoder_rerank.url == "http://127.0.0.1:8080/v1/rerank"
    assert hypothesis.cross_encoder_rerank.candidate_limit == 5
    assert hypothesis.cross_encoder_rerank.timeout_ms == 30000


def test_config_loader_preserves_named_generation_response_format(tmp_path: Path) -> None:
    config_path = tmp_path / "code-diver.yml"
    config_path.write_text(
        """
generation:
  provider: openai_compatible
  model: local-chat
  response_format: json_schema
""".strip(),
        encoding="utf-8",
    )

    config = ConfigLoader().load(config_path)

    assert config.generation.response_format == "json_schema"


def test_config_loader_uses_clickhouse_password_env_when_not_configured(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CLICKHOUSE_PASSWORD", "from-env")
    config_path = tmp_path / "code-diver.yml"
    config_path.write_text(
        """
metrics:
  enabled: true
  username: writer
""".strip(),
        encoding="utf-8",
    )

    config = ConfigLoader().load(config_path)

    assert config.metrics.password == "from-env"


def test_llm_rerank_generation_defaults_to_the_app_generation_block(tmp_path: Path) -> None:
    config_path = tmp_path / "code-diver.yml"
    config_path.write_text(
        """
generation:
  provider: openai_compatible
  model: answer-model
  url: http://127.0.0.1:8012/v1/chat/completions
llm_rerank:
  candidate_limit: 34
""".strip(),
        encoding="utf-8",
    )

    config = ConfigLoader().load(config_path)

    assert config.llm_rerank.generation is None


def test_llm_rerank_generation_overrides_only_the_named_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "code-diver.yml"
    config_path.write_text(
        """
generation:
  provider: openai_compatible
  model: answer-model
  url: http://127.0.0.1:8012/v1/chat/completions
  temperature: 0.3
llm_rerank:
  generation:
    model: rerank-model
""".strip(),
        encoding="utf-8",
    )

    config = ConfigLoader().load(config_path)

    rerank_generation = config.llm_rerank.generation
    assert rerank_generation is not None
    assert rerank_generation.model == "rerank-model"
    assert rerank_generation.provider == "openai_compatible"
    assert rerank_generation.url == "http://127.0.0.1:8012/v1/chat/completions"
    assert rerank_generation.temperature == 0.3
    assert config.generation.model == "answer-model"


def test_graph_file_frontier_limit_is_unset_by_default(tmp_path: Path) -> None:
    config_path = tmp_path / "code-diver.yml"
    config_path.write_text(
        """
graph_file_search:
  neighbor_limit: 40
""".strip(),
        encoding="utf-8",
    )

    config = ConfigLoader().load(config_path)

    assert config.graph_file_search.neighbor_limit == 40
    assert config.graph_file_search.frontier_limit is None


def test_graph_file_frontier_limit_is_independent_of_neighbor_limit(tmp_path: Path) -> None:
    config_path = tmp_path / "code-diver.yml"
    config_path.write_text(
        """
graph_file_search:
  neighbor_limit: 40
  frontier_limit: 12
""".strip(),
        encoding="utf-8",
    )

    config = ConfigLoader().load(config_path)

    assert config.graph_file_search.neighbor_limit == 40
    assert config.graph_file_search.frontier_limit == 12


def test_llm_rerank_chunking_is_unset_by_default(tmp_path: Path) -> None:
    config_path = tmp_path / "code-diver.yml"
    config_path.write_text(
        """
llm_rerank:
  candidate_limit: 34
""".strip(),
        encoding="utf-8",
    )

    config = ConfigLoader().load(config_path)

    assert config.llm_rerank.chunk_size is None
    assert config.llm_rerank.chunk_keep is None


def test_llm_rerank_chunk_keep_is_independent_of_rerank_limit(tmp_path: Path) -> None:
    """Two different quantities: how many a chunk contributes vs. how many the run outputs."""
    config_path = tmp_path / "code-diver.yml"
    config_path.write_text(
        """
llm_rerank:
  candidate_limit: 60
  rerank_limit: 10
  chunk_size: 20
  chunk_keep: 7
""".strip(),
        encoding="utf-8",
    )

    config = ConfigLoader().load(config_path)

    assert config.llm_rerank.chunk_size == 20
    assert config.llm_rerank.chunk_keep == 7
    assert config.llm_rerank.rerank_limit == 10

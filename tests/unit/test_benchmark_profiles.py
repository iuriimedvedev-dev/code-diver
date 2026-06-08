from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from code_diver.benchmarks import BenchmarkAssetService, BenchmarkPreparation, BenchmarkProfile, BenchmarkProfileRegistry
from code_diver.cli import (
    apply_builtin_h5,
    apply_embedding_profile,
    apply_runtime_config,
    build_parser,
    normalize_argv,
    resolve_benchmark_profile,
)
from code_diver.config import AppConfig
from code_diver.config.graph_config import GraphConfig
from code_diver.config.storage_config import StorageConfig
from code_diver.config.trace_config import TraceConfig
from code_diver.runtime import RuntimeConfig


pytestmark = pytest.mark.unit


def test_benchmark_registry_exposes_reproducible_profiles() -> None:
    registry = BenchmarkProfileRegistry()

    assert registry.names() == [
        "codesearchnet-mteb-python-1000",
        "codesearchnet-mteb-python-hash-smoke",
        "intellij-1000-answer-sets",
        "sample",
    ]
    codesearch = registry.get("codesearchnet-mteb-python-1000")
    assert codesearch.preparation is not None
    assert codesearch.preparation.dataset_name == "mteb/CodeSearchNetRetrieval"
    assert codesearch.config_path == Path("configs/codesearchnet-mteb-python-h5-embeddinggemma-quality.yml")
    assert registry.get("codesearchnet-mteb-python-hash-smoke").config_path == Path(
        "configs/codesearchnet-mteb-python-hash.yml"
    )
    assert registry.get("intellij-1000-answer-sets").dataset.name == "intellij_eval_1000.answer_sets.jsonl"


def test_benchmark_registry_reports_available_names() -> None:
    with pytest.raises(ValueError, match="codesearchnet-mteb-python-1000"):
        BenchmarkProfileRegistry().get("missing")


def test_evaluate_parser_accepts_benchmark_profile() -> None:
    args = build_parser().parse_args(["evaluate", "--benchmark", "sample", "--json"])

    assert args.benchmark == "sample"
    assert resolve_benchmark_profile(args).name == "sample"


def test_evaluate_parser_accepts_local_dataset_generation() -> None:
    args = build_parser().parse_args(["evaluate", "--generate-dataset", "--cases", "25", "--json"])

    assert args.generate_dataset is True
    assert args.cases == 25


def test_evaluate_search_tools_parser_accepts_case_limit() -> None:
    args = build_parser(include_advanced=True).parse_args(
        ["evaluate-search-tools", "--cases", "25", "--limit", "10", "--workers", "4", "--json"]
    )

    assert args.cases == 25
    assert args.limit == 10
    assert args.workers == 4


def test_evaluate_explanations_parser_accepts_benchmark_and_judge() -> None:
    args = build_parser(include_advanced=True).parse_args(
        [
            "evaluate-explanations",
            "--benchmark",
            "codexglue-code-to-text-python",
            "--cases",
            "5",
            "--judge",
            "--judge-prompt",
            "prompts/custom-judge.md",
            "--judge-config",
            "configs/judge.yml",
            "--judge-model",
            "gemini-3.1-flash-lite",
            "--json",
        ]
    )

    assert args.benchmark == "codexglue-code-to-text-python"
    assert args.cases == 5
    assert args.judge is True
    assert str(args.judge_prompt) == "prompts/custom-judge.md"
    assert str(args.judge_config) == "configs/judge.yml"
    assert args.judge_model == "gemini-3.1-flash-lite"


def test_evaluate_answers_parser_accepts_benchmark_and_judge() -> None:
    args = build_parser(include_advanced=True).parse_args(
        [
            "evaluate-answers",
            "--benchmark",
            "swe-qa-pro",
            "--repo",
            "owner/repo",
            "--cases",
            "3",
            "--limit",
            "5",
            "--context-files",
            "4",
            "--context-lines",
            "120",
            "--agentic-queries",
            "--query-count",
            "3",
            "--query-workers",
            "2",
            "--agentic-query-search-strategy",
            "hybrid",
            "--agentic-query-rerank",
            "--judge",
            "--judge-model",
            "gemini-3.1-flash-lite",
            "--json",
        ]
    )

    assert args.benchmark == "swe-qa-pro"
    assert args.repo == "owner/repo"
    assert args.cases == 3
    assert args.limit == 5
    assert args.context_files == 4
    assert args.context_lines == 120
    assert args.agentic_queries is True
    assert args.query_count == 3
    assert args.query_workers == 2
    assert args.agentic_query_search_strategy == "hybrid"
    assert args.agentic_query_rerank is True
    assert args.judge is True
    assert args.judge_model == "gemini-3.1-flash-lite"


def test_evaluate_answers_parser_uses_dynamic_context_default() -> None:
    args = build_parser(include_advanced=True).parse_args(["evaluate-answers", "--dataset", "answers.jsonl"])

    assert args.context_files is None


def test_resolve_benchmark_profile_returns_none_when_not_requested() -> None:
    assert resolve_benchmark_profile(Namespace(benchmark=None)) is None


def test_index_parser_accepts_repository_root() -> None:
    args = build_parser().parse_args(["index", "/tmp/repo"])

    assert str(args.index_root) == "/tmp/repo"


def test_index_parser_accepts_clear_all() -> None:
    args = build_parser().parse_args(["index", "clear", "--all"])

    assert str(args.index_root) == "clear"
    assert args.all is True


def test_index_parser_rejects_conflicting_index_modes() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["index", "--update-index", "--override-repo"])


def test_index_parser_rejects_embedding_profile() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["index", "--embedding", "qwen3-0.6b", "/tmp/repo"])


def test_init_parser_accepts_runtime_backend() -> None:
    args = build_parser().parse_args(
        [
            "init",
            "--platform",
            "nvidia-cuda",
            "--embedding",
            "qwen3-0.6b-vllm",
            "--runtime",
            "external",
            "--skip-install",
            "--yes",
        ]
    )

    assert args.platform == "nvidia-cuda"
    assert args.embedding == "qwen3-0.6b-vllm"
    assert args.runtime == "external"
    assert args.skip_install is True
    assert args.yes is True


def test_init_parser_accepts_embeddinggemma_profile() -> None:
    args = build_parser().parse_args(
        [
            "init",
            "--platform",
            "apple-metal",
            "--embedding",
            "embeddinggemma-300m",
            "--runtime",
            "host-uv",
            "--skip-install",
            "--yes",
        ]
    )

    assert args.embedding == "embeddinggemma-300m"


def test_embedding_profile_overrides_embedding_config() -> None:
    config = apply_embedding_profile(AppConfig(), "qwen3-4b", announce=False)

    assert config.embedding.provider == "openai_compatible"
    assert config.embedding.model == "mlx-community/Qwen3-Embedding-4B-4bit-DWQ"
    assert config.embedding.url == "http://127.0.0.1:8001/v1/embeddings"
    assert config.embedding.batch_size == 128
    assert config.embedding.workers == 1
    assert config.embedding.max_input_chars == 400


def test_embeddinggemma_profile_uses_code_retrieval_prompts() -> None:
    config = apply_embedding_profile(AppConfig(), "embeddinggemma-300m", announce=False)

    assert config.embedding.provider == "openai_compatible"
    assert config.embedding.model == "google/embeddinggemma-300m"
    assert config.embedding.dimensions == 768
    assert config.embedding.document_prefix == "title: none | text: "
    assert config.embedding.query_prefix == "task: code retrieval | query: "
    assert config.embedding.max_input_chars == 1200


def test_default_config_path_applies_runtime_embedding_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRuntimeConfigStore:
        def exists(self) -> bool:
            return True

        def load(self) -> RuntimeConfig:
            return RuntimeConfig("qwen3-0.6b", Path(".runtime"), platform="apple-metal")

    monkeypatch.setattr("code_diver.cli.RuntimeConfigStore", FakeRuntimeConfigStore)
    args = Namespace(config=Path("code-diver.yml"), command="search", root=None, index_root=None, embedding=None)

    config = apply_runtime_config(args, AppConfig(storage=StorageConfig(provider="qdrant")))

    assert config.embedding.provider == "openai_compatible"
    assert config.embedding.model == "mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ"
    assert config.embedding.batch_size == 128
    assert config.embedding.workers == 1
    assert config.embedding.max_input_chars == 400
    assert "qwen3_embedding_0_6b" in config.storage.qdrant.collection


def test_non_default_config_path_keeps_experiment_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRuntimeConfigStore:
        def exists(self) -> bool:
            return True

        def load(self) -> RuntimeConfig:
            return RuntimeConfig("qwen3-0.6b", Path(".runtime"), platform="apple-metal")

    monkeypatch.setattr("code_diver.cli.RuntimeConfigStore", FakeRuntimeConfigStore)
    args = Namespace(config=Path("configs/experiment.yml"), command="search", root=None, index_root=None, embedding=None)

    config = apply_runtime_config(args, AppConfig(storage=StorageConfig(provider="qdrant")))

    assert config.embedding.provider == "openai_compatible"
    assert config.embedding.model == "google/embeddinggemma-300m"
    assert "embeddinggemma_300m" in config.storage.qdrant.collection


def test_global_root_can_be_parsed_before_subcommand() -> None:
    args = build_parser().parse_args(["--root", "/tmp/repo", "search", "auth"])

    assert str(args.root) == "/tmp/repo"


def test_normalize_argv_moves_root_before_subcommand() -> None:
    assert normalize_argv(["index", "--root", "/tmp/repo"]) == ["--root", "/tmp/repo", "index"]


def test_root_override_rebases_repo_local_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class EmptyRuntimeConfigStore:
        def exists(self) -> bool:
            return False

    monkeypatch.setattr("code_diver.cli.RuntimeConfigStore", EmptyRuntimeConfigStore)
    repo = tmp_path / "repo"
    args = Namespace(config=Path("code-diver.yml"), command="search", root=repo, index_root=None, embedding=None)

    config = apply_runtime_config(
        args,
        AppConfig(
            artifact=Path(".code-diver/index.json"),
            graph=GraphConfig(artifact=Path(".code-diver/graph.json")),
            trace=TraceConfig(artifact=Path(".code-diver/traces/indexing.jsonl")),
            storage=StorageConfig(provider="qdrant"),
        ),
    )

    assert config.root == repo
    assert config.artifact == repo / ".code-diver/index.json"
    assert config.graph.artifact == repo / ".code-diver/graph.json"
    assert config.trace.artifact == repo / ".code-diver/traces/indexing.jsonl"


def test_builtin_h5_profile_sets_manifest_hybrid_rerank_defaults() -> None:
    config = apply_builtin_h5(AppConfig())

    assert config.search.strategy == "hybrid"
    assert config.scanner.line_chunks is False
    assert config.scanner.file_summary_chunks is True
    assert config.scanner.file_manifest_chunks is True
    assert config.hybrid_search.routing_enabled is True
    assert config.hybrid_search.vector_kind_limits == {"file_summary": 170, "file_manifest": 170}
    assert config.hybrid_search.vector_weight == 0.5625
    assert config.hybrid_search.lexical_weight == 0.1875
    assert config.hybrid_search.graph_weight == 0.08333333333333334
    assert config.llm_rerank.rerank_limit == 10
    assert config.llm_rerank.mode == "precision"
    assert config.generation.provider == "gemini"
    assert config.generation.model == "gemini-3.1-flash-lite"


def test_benchmark_asset_service_skips_existing_assets(tmp_path: Path) -> None:
    preparation = BenchmarkPreparation(
        kind="missing",
        dataset_name="dataset",
        language="python",
        limit=1,
        output_root=tmp_path,
        estimated_download_mb=1,
    )
    preparation.corpus_dir.mkdir(parents=True)
    (preparation.corpus_dir / "case.py").write_text("def f(): pass\n", encoding="utf-8")
    preparation.dataset_path.write_text('{"id":"x","query":"q","expected":["case.py"]}\n', encoding="utf-8")
    preparation.manifest_path.write_text("{}", encoding="utf-8")
    profile = BenchmarkProfile("bench", preparation.dataset_path, "desc", preparation=preparation)

    assert BenchmarkAssetService().ensure(profile) is None


def test_benchmark_asset_service_declines_without_tty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    preparation = BenchmarkPreparation(
        kind="mteb_codesearchnet",
        dataset_name="dataset",
        language="python",
        limit=1,
        output_root=tmp_path,
        estimated_download_mb=1,
    )
    profile = BenchmarkProfile("bench", preparation.dataset_path, "desc", preparation=preparation)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    with pytest.raises(RuntimeError, match="Benchmark assets not prepared"):
        BenchmarkAssetService().ensure(profile)


def test_benchmark_asset_service_prompts_on_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    preparation = BenchmarkPreparation(
        kind="unsupported",
        dataset_name="dataset",
        language="python",
        limit=1,
        output_root=tmp_path,
        estimated_download_mb=1,
    )
    profile = BenchmarkProfile("bench", preparation.dataset_path, "desc", preparation=preparation)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "n")

    with pytest.raises(RuntimeError):
        BenchmarkAssetService().ensure(profile)

    captured = capsys.readouterr()
    assert "Download and prepare it now?" in captured.err
    assert captured.out == ""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from code_diver.benchmarks import BenchmarkAssetService, BenchmarkPreparation, BenchmarkProfile, BenchmarkProfileRegistry
from code_diver.cli import (
    apply_builtin_pure_h3,
    apply_embedding_profile,
    build_parser,
    normalize_argv,
    resolve_benchmark_profile,
)
from code_diver.config import AppConfig


pytestmark = pytest.mark.unit


def test_benchmark_registry_exposes_reproducible_profiles() -> None:
    registry = BenchmarkProfileRegistry()

    assert registry.names() == ["codesearchnet-mteb-python-1000", "intellij-1000-answer-sets", "sample"]
    codesearch = registry.get("codesearchnet-mteb-python-1000")
    assert codesearch.preparation is not None
    assert codesearch.preparation.dataset_name == "mteb/CodeSearchNetRetrieval"
    assert registry.get("intellij-1000-answer-sets").dataset.name == "intellij_eval_1000.answer_sets.jsonl"


def test_benchmark_registry_reports_available_names() -> None:
    with pytest.raises(ValueError, match="codesearchnet-mteb-python-1000"):
        BenchmarkProfileRegistry().get("missing")


def test_evaluate_parser_accepts_benchmark_profile() -> None:
    args = build_parser().parse_args(["evaluate", "--benchmark", "sample", "--json"])

    assert args.benchmark == "sample"
    assert resolve_benchmark_profile(args).name == "sample"


def test_resolve_benchmark_profile_returns_none_when_not_requested() -> None:
    assert resolve_benchmark_profile(Namespace(benchmark=None)) is None


def test_index_parser_accepts_repository_root() -> None:
    args = build_parser().parse_args(["index", "/tmp/repo"])

    assert str(args.index_root) == "/tmp/repo"


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


def test_embedding_profile_overrides_embedding_config() -> None:
    config = apply_embedding_profile(AppConfig(), "qwen3-4b", announce=False)

    assert config.embedding.provider == "openai_compatible"
    assert config.embedding.model == "mlx-community/Qwen3-Embedding-4B-4bit-DWQ"
    assert config.embedding.url == "http://127.0.0.1:8001/v1/embeddings"
    assert config.embedding.max_input_chars == 400


def test_global_root_can_be_parsed_before_subcommand() -> None:
    args = build_parser().parse_args(["--root", "/tmp/repo", "search", "auth"])

    assert str(args.root) == "/tmp/repo"


def test_normalize_argv_moves_root_before_subcommand() -> None:
    assert normalize_argv(["index", "--root", "/tmp/repo"]) == ["--root", "/tmp/repo", "index"]


def test_builtin_pure_h3_profile_sets_manifest_hybrid_defaults() -> None:
    config = apply_builtin_pure_h3(AppConfig())

    assert config.search.strategy == "hybrid"
    assert config.scanner.line_chunks is False
    assert config.scanner.file_summary_chunks is True
    assert config.scanner.file_manifest_chunks is True
    assert config.hybrid_search.routing_enabled is True
    assert config.hybrid_search.vector_kind_limits == {"file_summary": 170, "file_manifest": 170}


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

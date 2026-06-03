from __future__ import annotations

from argparse import Namespace

import pytest

from code_diver.benchmarks import BenchmarkProfileRegistry
from code_diver.cli import build_parser, resolve_benchmark_profile


pytestmark = pytest.mark.unit


def test_benchmark_registry_exposes_reproducible_profiles() -> None:
    registry = BenchmarkProfileRegistry()

    assert registry.names() == ["intellij-1000-answer-sets", "open-protogen-hash-vector-30", "protogen-open", "sample"]
    assert registry.get("intellij-1000-answer-sets").dataset.name == "intellij_eval_1000.answer_sets.jsonl"
    assert registry.get("open-protogen-hash-vector-30").dataset.name == "protogen_eval_30.jsonl"
    assert registry.get("protogen-open").config_path is not None


def test_benchmark_registry_reports_available_names() -> None:
    with pytest.raises(ValueError, match="Available profiles: intellij-1000-answer-sets"):
        BenchmarkProfileRegistry().get("missing")


def test_evaluate_parser_accepts_benchmark_profile() -> None:
    args = build_parser().parse_args(["evaluate", "--benchmark", "sample", "--json"])

    assert args.benchmark == "sample"
    assert resolve_benchmark_profile(args).name == "sample"


def test_resolve_benchmark_profile_returns_none_when_not_requested() -> None:
    assert resolve_benchmark_profile(Namespace(benchmark=None)) is None

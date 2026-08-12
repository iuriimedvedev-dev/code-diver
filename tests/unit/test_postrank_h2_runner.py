from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_postrank_h2_deterministic.py"
SPEC = importlib.util.spec_from_file_location("run_postrank_h2_deterministic", SCRIPT_PATH)
assert SPEC is not None
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
DeterministicPostrankH2 = MODULE.DeterministicPostrankH2


def test_alias_locator_is_skipped_when_alias_limit_is_zero(tmp_path: Path) -> None:
    runner = object.__new__(DeterministicPostrankH2)
    runner.args = SimpleNamespace(alias_limit=0, alias_graph=tmp_path / "missing-graph.json")
    config = SimpleNamespace(graph=SimpleNamespace(artifact=tmp_path / "also-missing.json"))

    assert runner._alias_locator(config) is None


def test_preserve_base_files_reserves_unique_base_files_before_llm_tail() -> None:
    runner = object.__new__(DeterministicPostrankH2)
    ranked = [
        {"path": "src/llm_a.py", "id": "llm-a"},
        {"path": "src/base_2.py", "id": "base-2-reranked"},
        {"path": "src/llm_b.py", "id": "llm-b"},
    ]
    candidates = [
        {"path": "src/base_1.py", "id": "base-1"},
        {"path": "src/base_1.py::symbol", "id": "base-1-symbol"},
        {"path": "src/base_2.py", "id": "base-2"},
        {"path": "src/base_3.py", "id": "base-3"},
    ]

    result = runner._preserve_base_files(ranked, candidates, preserve_count=2, limit=4)

    assert [candidate["path"] for candidate in result] == [
        "src/base_1.py",
        "src/base_2.py",
        "src/llm_a.py",
        "src/llm_b.py",
    ]
    assert result[0]["protectedBaseRank"] == 1
    assert result[1]["protectedBaseRank"] == 2
    assert [candidate["rerankRank"] for candidate in result] == [1, 2, 3, 4]


def test_preserve_base_files_is_noop_when_disabled() -> None:
    runner = object.__new__(DeterministicPostrankH2)
    ranked = [{"path": "src/llm_a.py", "id": "llm-a"}]

    result = runner._preserve_base_files(
        ranked,
        [{"path": "src/base_1.py", "id": "base-1"}],
        preserve_count=0,
        limit=10,
    )

    assert result == ranked


def test_preserve_base_files_rescue_mode_keeps_llm_prefix_then_base_files() -> None:
    runner = object.__new__(DeterministicPostrankH2)
    ranked = [
        {"path": "src/llm_1.py", "id": "llm-1"},
        {"path": "src/llm_2.py", "id": "llm-2"},
        {"path": "src/llm_3.py", "id": "llm-3"},
        {"path": "src/base_2.py", "id": "base-2-reranked"},
    ]
    candidates = [
        {"path": "src/base_1.py", "id": "base-1"},
        {"path": "src/base_2.py", "id": "base-2"},
        {"path": "src/base_3.py", "id": "base-3"},
    ]

    result = runner._preserve_base_files(
        ranked,
        candidates,
        preserve_count=3,
        limit=5,
        mode="rescue",
        llm_prefix_files=2,
    )

    assert [candidate["path"] for candidate in result] == [
        "src/llm_1.py",
        "src/llm_2.py",
        "src/base_1.py",
        "src/base_2.py",
        "src/base_3.py",
    ]


def test_dedupe_final_files_keeps_unique_files_and_symbol_variants_once() -> None:
    runner = object.__new__(DeterministicPostrankH2)
    runner.args = SimpleNamespace(dedupe_final_files=True)

    result = runner._dedupe_final_files(
        [
            {"path": "src/a.py::ClassA", "id": "a-class"},
            {"path": "src/a.py::ClassA.method", "id": "a-method"},
            {"path": "src/b.py", "id": "b"},
            {"path": "src/c.py#L10", "id": "c"},
        ],
        limit=3,
    )

    assert [candidate["path"] for candidate in result] == ["src/a.py::ClassA", "src/b.py", "src/c.py#L10"]
    assert [candidate["rerankRank"] for candidate in result] == [1, 2, 3]

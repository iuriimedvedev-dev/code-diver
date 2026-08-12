"""Regression tests for the output-path defaulting and overwrite guard in
`scripts/run_postrank_h2_deterministic.py`.

Root cause: `--output`/`--report` used to default to a literal path containing `-100`
(`.code-diver/reports/intellij-postrank-h2-deterministic-100.json`/`.html`) while `--cases`
defaulted to 100 as a separate flag. Running with `--cases 10` and no explicit `--output`
therefore silently wrote into the 100-case file. These tests pin: (1) the default path is a
function of the actual `--cases` value, resolved AFTER argument parsing; (2) an explicit
`--output`/`--report` still wins; (3) a pre-existing destination -- including the
per-hypothesis `--partial-dir` sibling this script also writes -- is never touched unless
`--allow-overwrite`/`ALLOW_OVERWRITE` says so, matching the idiom in
`tests/unit/test_rejudge_report_overwrite_guard.py`.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]

PRE_EXISTING_CONTENT = '{"sentinel": "do-not-touch"}'


def load_script(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered in sys.modules BEFORE exec_module: the module defines a `slots=True`
    # dataclass, and dataclasses on 3.12+ resolve `cls.__module__` via `sys.modules` while
    # processing annotations -- without this, exec_module() raises `AttributeError` because
    # the module isn't registered yet. Mirrors tests/unit/test_postrank_h2_runner.py.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DETERMINISTIC = load_script("run_postrank_h2_deterministic")


class _StubDeterministicRunner:
    """Stands in for `DeterministicPostrankH2`: no `ConfigLoader`, no real search/rerank.

    Still writes `args.output` (like the real `.run()` does) so the overwrite-guard tests
    below can tell a refused run apart from a permitted one by content, not just exit code.
    """

    def __init__(self, args: Any) -> None:
        self.args = args
        self.config = SimpleNamespace()

    def _scenario(self, name: str) -> str:
        return "branch_a"

    def run(self) -> dict[str, Any]:
        self.args.output.parent.mkdir(parents=True, exist_ok=True)
        self.args.output.write_text(json.dumps({"run_id": "stub-run-id"}), encoding="utf-8")
        return {"run_id": "stub-run-id"}


def run_main(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    *,
    hypotheses: list[Any] | None = None,
) -> int:
    monkeypatch.setattr(DETERMINISTIC, "DeterministicPostrankH2", _StubDeterministicRunner)
    monkeypatch.setattr(
        DETERMINISTIC, "search_tool_hypotheses", lambda config, names: list(hypotheses or [])
    )
    monkeypatch.setattr(sys, "argv", ["run_postrank_h2_deterministic.py", *argv])
    return DETERMINISTIC.main()


def test_default_output_path_is_a_function_of_cases() -> None:
    """The exact collision from the incident: `--cases 10` vs `--cases 100` must never
    resolve to the same default `--output`."""
    ten_case = DETERMINISTIC.default_output_path(10, DETERMINISTIC.DEFAULT_POSTRANK_RERANKER)
    hundred_case = DETERMINISTIC.default_output_path(100, DETERMINISTIC.DEFAULT_POSTRANK_RERANKER)

    assert ten_case != hundred_case
    assert ten_case.name == "intellij-postrank-h2-deterministic-10.json"
    assert hundred_case.name == "intellij-postrank-h2-deterministic-100.json"


def test_default_report_path_is_a_function_of_cases() -> None:
    ten_case = DETERMINISTIC.default_report_path(10, DETERMINISTIC.DEFAULT_POSTRANK_RERANKER)
    hundred_case = DETERMINISTIC.default_report_path(100, DETERMINISTIC.DEFAULT_POSTRANK_RERANKER)

    assert ten_case != hundred_case
    assert ten_case.suffix == ".html"


def test_zero_cases_means_full_dataset_and_is_distinct_from_any_finite_count() -> None:
    full = DETERMINISTIC.default_output_path(0, DETERMINISTIC.DEFAULT_POSTRANK_RERANKER)
    hundred_case = DETERMINISTIC.default_output_path(100, DETERMINISTIC.DEFAULT_POSTRANK_RERANKER)

    assert full != hundred_case
    assert full.name == "intellij-postrank-h2-deterministic-full.json"


def test_default_output_path_also_reflects_a_non_default_reranker() -> None:
    """`--postrank-reranker` swaps the entire reranking pipeline but was completely absent
    from the old literal default -- two runs at the same `--cases` with different rerankers
    would otherwise collide too."""
    default_reranker = DETERMINISTIC.default_output_path(100, "llm")
    cross_encoder = DETERMINISTIC.default_output_path(100, "cross_encoder")

    assert default_reranker != cross_encoder


def test_partial_output_paths_are_named_after_each_hypothesis(tmp_path: Path) -> None:
    hypotheses = [SimpleNamespace(name="graph_file"), SimpleNamespace(name="union")]

    paths = DETERMINISTIC.partial_output_paths(tmp_path, hypotheses)

    assert paths == [tmp_path / "graph_file.partial.json", tmp_path / "union.partial.json"]


def test_partial_output_paths_is_empty_when_partial_dir_is_none() -> None:
    assert DETERMINISTIC.partial_output_paths(None, [SimpleNamespace(name="graph_file")]) == []


def test_explicit_output_and_report_override_the_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ALLOW_OVERWRITE", raising=False)
    explicit_output = tmp_path / "custom-output.json"
    explicit_report = tmp_path / "custom-report.html"

    exit_code = run_main(
        monkeypatch,
        ["--cases", "10", "--output", str(explicit_output), "--report", str(explicit_report)],
    )

    assert exit_code == 0
    assert explicit_output.exists()
    assert json.loads(explicit_output.read_text(encoding="utf-8"))["run_id"] == "stub-run-id"


def test_default_ten_and_hundred_case_runs_do_not_collide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end reproduction of the incident: two runs, differing only in `--cases`, with
    no explicit `--output`, must land on two different files."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ALLOW_OVERWRITE", raising=False)

    assert run_main(monkeypatch, ["--cases", "10"]) == 0
    assert run_main(monkeypatch, ["--cases", "100"]) == 0

    ten_case_output = tmp_path / ".code-diver/reports/intellij-postrank-h2-deterministic-10.json"
    hundred_case_output = tmp_path / ".code-diver/reports/intellij-postrank-h2-deterministic-100.json"
    assert ten_case_output.exists()
    assert hundred_case_output.exists()


def test_refuses_to_overwrite_an_existing_output_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ALLOW_OVERWRITE", raising=False)
    output = tmp_path / "existing.json"
    output.write_text(PRE_EXISTING_CONTENT, encoding="utf-8")

    with pytest.raises(DETERMINISTIC.RefuseToClobberError, match=str(output)):
        run_main(monkeypatch, ["--output", str(output), "--report", str(tmp_path / "report.html")])

    assert output.read_text(encoding="utf-8") == PRE_EXISTING_CONTENT


def test_refuses_to_overwrite_an_existing_partial_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The per-hypothesis `.partial.json` sibling under `--partial-dir` is guarded too --
    an unguarded partial is what destroyed the only recovery path in the real incident."""
    monkeypatch.delenv("ALLOW_OVERWRITE", raising=False)
    partial_dir = tmp_path / "partials"
    partial_dir.mkdir()
    stale_partial = partial_dir / "graph_file.partial.json"
    stale_partial.write_text(PRE_EXISTING_CONTENT, encoding="utf-8")
    output = tmp_path / "fresh-output.json"

    with pytest.raises(DETERMINISTIC.RefuseToClobberError, match=str(stale_partial)):
        run_main(
            monkeypatch,
            [
                "--output",
                str(output),
                "--report",
                str(tmp_path / "report.html"),
                "--partial-dir",
                str(partial_dir),
            ],
            hypotheses=[SimpleNamespace(name="graph_file")],
        )

    assert stale_partial.read_text(encoding="utf-8") == PRE_EXISTING_CONTENT
    assert not output.exists()


def test_allow_overwrite_flag_permits_overwriting_an_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ALLOW_OVERWRITE", raising=False)
    output = tmp_path / "existing.json"
    output.write_text(PRE_EXISTING_CONTENT, encoding="utf-8")

    exit_code = run_main(
        monkeypatch,
        [
            "--output",
            str(output),
            "--report",
            str(tmp_path / "report.html"),
            "--allow-overwrite",
        ],
    )

    assert exit_code == 0
    rewritten = json.loads(output.read_text(encoding="utf-8"))
    assert rewritten != {"sentinel": "do-not-touch"}
    assert rewritten["run_id"] == "stub-run-id"


def test_allow_overwrite_env_var_permits_overwriting_an_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALLOW_OVERWRITE", "1")
    output = tmp_path / "existing.json"
    output.write_text(PRE_EXISTING_CONTENT, encoding="utf-8")

    exit_code = run_main(monkeypatch, ["--output", str(output), "--report", str(tmp_path / "report.html")])

    assert exit_code == 0
    rewritten = json.loads(output.read_text(encoding="utf-8"))
    assert rewritten["run_id"] == "stub-run-id"


@pytest.mark.parametrize("falsy_value", ["", "0", "false", "False"])
def test_allow_overwrite_env_var_falsy_values_still_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, falsy_value: str
) -> None:
    monkeypatch.setenv("ALLOW_OVERWRITE", falsy_value)
    output = tmp_path / "existing.json"
    output.write_text(PRE_EXISTING_CONTENT, encoding="utf-8")

    with pytest.raises(DETERMINISTIC.RefuseToClobberError):
        run_main(monkeypatch, ["--output", str(output), "--report", str(tmp_path / "report.html")])

    assert output.read_text(encoding="utf-8") == PRE_EXISTING_CONTENT


def test_succeeds_when_no_destination_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLOW_OVERWRITE", raising=False)
    output = tmp_path / "brand-new.json"

    exit_code = run_main(monkeypatch, ["--output", str(output), "--report", str(tmp_path / "report.html")])

    assert exit_code == 0
    assert output.exists()

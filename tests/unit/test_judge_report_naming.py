"""Regression tests for `scripts/judge_report_naming.py`.

A 100-case judged baseline (`h14-qwen35-4b-answer-strict-qwen35-9b.json`) was silently
overwritten by a re-judge of a 10-case smoke run: `run_h14_model.sh` built its judged
output path from `$MODEL_LABEL`, `$JUDGE_LABEL`, and `$BUDGET_SUFFIX` alone, dropping the
`$CASES` suffix that the answer-report filename (`$OUT`) already carried. Two different
answer-report filenames -- one for `-10`, one for `-100` -- therefore mapped to the exact
same judged-report path.

These tests pin the fix: `derive_judge_output_path()` takes the whole answer-report path as
its input (rather than re-deriving a subset of its distinguishing parts), so any two
distinct answer-report filenames necessarily produce distinct judged-report filenames.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NAMING = load_script("judge_report_naming")


def test_ten_case_and_hundred_case_inputs_map_to_different_judged_outputs() -> None:
    """The exact collision from the incident: `-10` vs. `-100` must never share an output."""
    ten_case = Path("/repo/.code-diver/reports/protogen-h14-qwen35-4b-text-graph-10.json")
    hundred_case = Path("/repo/.code-diver/reports/protogen-h14-qwen35-4b-text-graph-100.json")

    ten_case_out = NAMING.derive_judge_output_path(ten_case, "qwen35-9b")
    hundred_case_out = NAMING.derive_judge_output_path(hundred_case, "qwen35-9b")

    assert ten_case_out != hundred_case_out


def test_worked_examples_match_documented_convention() -> None:
    """Pin the documented before/after examples in the module docstring."""
    reports = Path("/repo/.code-diver/reports")

    ten_case = NAMING.derive_judge_output_path(
        reports / "protogen-h14-qwen35-4b-text-graph-10.json", "qwen35-9b"
    )
    assert ten_case == reports / "strict-judge" / "protogen-h14-qwen35-4b-text-graph-10-answer-strict-qwen35-9b.json"

    hundred_case = NAMING.derive_judge_output_path(
        reports / "protogen-h14-qwen35-4b-text-graph-100.json", "qwen35-9b"
    )
    assert (
        hundred_case
        == reports / "strict-judge" / "protogen-h14-qwen35-4b-text-graph-100-answer-strict-qwen35-9b.json"
    )

    hundred_case_with_budget = NAMING.derive_judge_output_path(
        reports / "protogen-h14-qwen35-4b-text-graph-100-cf10-cl160.json", "qwen35-9b"
    )
    assert (
        hundred_case_with_budget
        == reports
        / "strict-judge"
        / "protogen-h14-qwen35-4b-text-graph-100-cf10-cl160-answer-strict-qwen35-9b.json"
    )


def test_different_budget_suffixes_map_to_different_judged_outputs() -> None:
    default_budget = Path("/repo/.code-diver/reports/protogen-h16-armb-qwen35-4b-100.json")
    custom_budget = Path("/repo/.code-diver/reports/protogen-h16-armb-qwen35-4b-100-cf10-cl160.json")

    assert NAMING.derive_judge_output_path(default_budget, "qwen35-9b") != NAMING.derive_judge_output_path(
        custom_budget, "qwen35-9b"
    )


def test_different_judge_labels_map_to_different_judged_outputs() -> None:
    answer_report = Path("/repo/.code-diver/reports/protogen-h14-qwen35-4b-text-graph-100.json")

    assert NAMING.derive_judge_output_path(answer_report, "qwen35-9b") != NAMING.derive_judge_output_path(
        answer_report, "gemma4-12b"
    )


def test_judge_output_is_written_under_a_strict_judge_sibling_directory() -> None:
    answer_report = Path("/repo/.code-diver/reports/protogen-h14-qwen35-4b-text-graph-100.json")

    output = NAMING.derive_judge_output_path(answer_report, "qwen35-9b")

    assert output.parent == answer_report.parent / "strict-judge"


def test_empty_judge_label_is_rejected() -> None:
    answer_report = Path("/repo/.code-diver/reports/protogen-h14-qwen35-4b-text-graph-100.json")

    with pytest.raises(ValueError, match="judge_label"):
        NAMING.derive_judge_output_path(answer_report, "")


def test_partial_path_mirrors_the_shell_percent_json_idiom() -> None:
    judge_output = Path("/repo/.code-diver/reports/strict-judge/foo-answer-strict-qwen35-9b.json")

    partial = NAMING.derive_judge_partial_path(judge_output)

    assert partial == Path("/repo/.code-diver/reports/strict-judge/foo-answer-strict-qwen35-9b.partial.json")


def test_cli_prints_derived_output_path(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = NAMING.main(
        ["/repo/.code-diver/reports/protogen-h14-qwen35-4b-text-graph-10.json", "--judge-label", "qwen35-9b"]
    )

    assert exit_code == 0
    printed = capsys.readouterr().out.strip()
    assert printed == str(
        Path("/repo/.code-diver/reports/strict-judge/protogen-h14-qwen35-4b-text-graph-10-answer-strict-qwen35-9b.json")
    )


def test_cli_partial_flag_prints_the_partial_sibling(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = NAMING.main(
        [
            "/repo/.code-diver/reports/protogen-h14-qwen35-4b-text-graph-10.json",
            "--judge-label",
            "qwen35-9b",
            "--partial",
        ]
    )

    assert exit_code == 0
    printed = capsys.readouterr().out.strip()
    assert printed.endswith(".partial.json")
    assert "protogen-h14-qwen35-4b-text-graph-10-answer-strict-qwen35-9b" in printed

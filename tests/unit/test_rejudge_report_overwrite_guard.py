"""Regression tests for the overwrite guard in `scripts/rejudge_answer_report.py`.

A 100-case judged baseline report and its `.partial.json` sibling were both silently
overwritten by a re-judge of an unrelated 10-case smoke run, because nothing checked
whether `--output`/`--partial-output` already pointed at a file with real data in it.
These tests pin the fix: `main()` refuses to run at all -- leaving any pre-existing
destination file byte-for-byte untouched -- unless `--allow-overwrite` (or the
`ALLOW_OVERWRITE` env var) explicitly says otherwise.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]

PRE_EXISTING_CONTENT = '{"sentinel": "do-not-touch"}'


class _StubProvider:
    model = "stub-judge-model"


class _StubJudge:
    """Never actually invoked by these tests: every row below is unjudgeable by design."""

    DEFAULT_PROMPT_PATH = Path("prompts/code-answer-judge.md")

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.prompt_path = self.DEFAULT_PROMPT_PATH
        self.provider = _StubProvider()

    def judge(self, *_args: object, **_kwargs: object) -> dict[str, Any]:
        raise AssertionError("StubJudge.judge() should never be called by these tests")


def load_script(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REJUDGE = load_script("rejudge_answer_report")


def make_input(tmp_path: Path) -> Path:
    """A single-row source report whose row is unjudgeable (empty prediction).

    This keeps the happy-path runs in this module independent of `AnswerJudge`/
    `create_generation_provider` behaviour -- both are still monkeypatched below purely so
    a run that is *allowed* to proceed doesn't need a real judge config or model server.
    """
    source = {
        "results": [
            {
                "case_id": "case-0",
                "question": "What does case-0 do?",
                "reference": "reference-0",
                "prediction": "",
                "error": "generation failed: invalid json",
                "context_text": "=== a.py ===\ndef a(): ...",
                "metadata": {},
                "expected_paths": ["a.py"],
                "metrics": {},
            }
        ]
    }
    input_path = tmp_path / "source.json"
    input_path.write_text(json.dumps(source), encoding="utf-8")
    return input_path


def run_rejudge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    output: Path,
    partial_output: Path | None = None,
    extra_args: list[str] | None = None,
) -> int:
    monkeypatch.setattr(REJUDGE, "AnswerJudge", _StubJudge)
    monkeypatch.setattr(REJUDGE, "create_generation_provider", lambda config: _StubProvider())
    argv = [
        "rejudge_answer_report.py",
        str(make_input(tmp_path)),
        "--judge-config",
        str(tmp_path / "missing-config.yml"),
        "--judge-prompt",
        str(tmp_path / "missing-prompt.md"),
        "--output",
        str(output),
    ]
    if partial_output is not None:
        argv += ["--partial-output", str(partial_output)]
    argv += extra_args or []
    monkeypatch.setattr(sys, "argv", argv)
    return REJUDGE.main()


def test_refuses_to_overwrite_an_existing_output_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ALLOW_OVERWRITE", raising=False)
    output = tmp_path / "existing.json"
    output.write_text(PRE_EXISTING_CONTENT, encoding="utf-8")

    with pytest.raises(REJUDGE.RefuseToClobberError, match=str(output)):
        run_rejudge(tmp_path, monkeypatch, output=output)

    assert output.read_text(encoding="utf-8") == PRE_EXISTING_CONTENT


def test_refuses_to_overwrite_an_existing_partial_output_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `.partial.json` sibling is guarded too -- it was clobbered in the real incident."""
    monkeypatch.delenv("ALLOW_OVERWRITE", raising=False)
    output = tmp_path / "fresh.json"
    partial_output = tmp_path / "fresh.partial.json"
    partial_output.write_text(PRE_EXISTING_CONTENT, encoding="utf-8")

    with pytest.raises(REJUDGE.RefuseToClobberError, match=str(partial_output)):
        run_rejudge(tmp_path, monkeypatch, output=output, partial_output=partial_output)

    assert partial_output.read_text(encoding="utf-8") == PRE_EXISTING_CONTENT
    assert not output.exists()


def test_allow_overwrite_flag_permits_overwriting_an_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ALLOW_OVERWRITE", raising=False)
    output = tmp_path / "existing.json"
    output.write_text(PRE_EXISTING_CONTENT, encoding="utf-8")

    exit_code = run_rejudge(tmp_path, monkeypatch, output=output, extra_args=["--allow-overwrite"])

    assert exit_code == 0
    rewritten = json.loads(output.read_text(encoding="utf-8"))
    assert rewritten != {"sentinel": "do-not-touch"}
    assert rewritten["results"][0]["case_id"] == "case-0"


def test_allow_overwrite_env_var_permits_overwriting_an_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALLOW_OVERWRITE", "1")
    output = tmp_path / "existing.json"
    output.write_text(PRE_EXISTING_CONTENT, encoding="utf-8")

    exit_code = run_rejudge(tmp_path, monkeypatch, output=output)

    assert exit_code == 0
    rewritten = json.loads(output.read_text(encoding="utf-8"))
    assert rewritten["results"][0]["case_id"] == "case-0"


@pytest.mark.parametrize("falsy_value", ["", "0", "false", "False"])
def test_allow_overwrite_env_var_falsy_values_still_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, falsy_value: str
) -> None:
    monkeypatch.setenv("ALLOW_OVERWRITE", falsy_value)
    output = tmp_path / "existing.json"
    output.write_text(PRE_EXISTING_CONTENT, encoding="utf-8")

    with pytest.raises(REJUDGE.RefuseToClobberError):
        run_rejudge(tmp_path, monkeypatch, output=output)

    assert output.read_text(encoding="utf-8") == PRE_EXISTING_CONTENT


def test_succeeds_when_no_destination_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLOW_OVERWRITE", raising=False)
    output = tmp_path / "brand-new.json"

    exit_code = run_rejudge(tmp_path, monkeypatch, output=output)

    assert exit_code == 0
    assert output.exists()

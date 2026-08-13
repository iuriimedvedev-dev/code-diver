from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.answering import AnswerCase
from code_diver.answering.answer_context import AnswerContext
from code_diver.answering.answer_service import AnswerService
from code_diver.config import ConfigLoader

pytestmark = pytest.mark.unit


def _service(*, restrict: bool) -> AnswerService:
    # The prompt lives on AnswerService now: it is part of answering, not of scoring.
    # Only `answer_prompt` is exercised, so the collaborators it never touches stay None.
    return AnswerService(
        retrieval_strategy=None,  # type: ignore[arg-type]
        answer_provider=None,  # type: ignore[arg-type]
        context_builder=None,  # type: ignore[arg-type]
        restrict_citations_to_context=restrict,
    )


def _case() -> AnswerCase:
    return AnswerCase(
        id="c1",
        question="where are agent objects constructed",
        reference="",
        expected_paths=["src/agents/base/factory.py"],
        metadata={},
    )


def _context() -> AnswerContext:
    return AnswerContext(
        text="src/agents/base/factory.py\n1 | class Factory: ...",
        files=["src/agents/base/factory.py", "src/agents/base/agent.py"],
    )


def test_the_default_prompt_is_unchanged_so_earlier_runs_stay_comparable() -> None:
    prompt = _service(restrict=False).answer_prompt(_case(), _context())

    assert "Citable files" not in prompt
    # The pre-existing weak instruction is still the only citation boundary in this mode.
    assert "Cite relative file paths and line numbers from the context" in prompt


def test_the_allowlist_names_every_context_file_and_forbids_the_rest() -> None:
    prompt = _service(restrict=True).answer_prompt(_case(), _context())

    assert "Citable files" in prompt
    assert "  - src/agents/base/factory.py" in prompt
    assert "  - src/agents/base/agent.py" in prompt
    assert "Citing any other path is an error" in prompt
    # The escape hatch matters: without it the model is pushed to cite a listed file it does
    # not believe in, which trades fabrication for a wrong citation rather than removing one.
    assert "say so in the answer instead of citing it" in prompt


def test_an_empty_bundle_gets_no_allowlist_rather_than_an_empty_one() -> None:
    # An empty list would read as "cite nothing", which is not the intended instruction for a
    # case where retrieval returned nothing -- that case should still explain what is missing.
    prompt = _service(restrict=True).answer_prompt(_case(), AnswerContext(text="", files=[]))

    assert "Citable files" not in prompt


def test_the_allowlist_is_exactly_the_set_the_fabrication_metric_scores_against() -> None:
    # `AnswerGroundingMetrics.score` is called with `context.files`; if the prompt listed any
    # other set, the model would be told one boundary and graded on a different one.
    from code_diver.answering.answer_grounding_metrics import AnswerGroundingMetrics

    context = _context()
    prompt = _service(restrict=True).answer_prompt(_case(), context)
    for path in context.files:
        assert f"  - {path}" in prompt

    scored = AnswerGroundingMetrics().score(
        "answer",
        [{"path": path} for path in context.files],
        context.files,
        ["src/agents/base/factory.py"],
    )
    assert scored["citation_fabricated_count"] == 0.0


def test_the_config_flag_defaults_off_and_loads_from_yaml(tmp_path: Path) -> None:
    default = ConfigLoader().load(_write(tmp_path / "a.yml", "evaluation:\n  limit: 10\n"))
    assert default.evaluation.restrict_citations_to_context is False

    enabled = ConfigLoader().load(
        _write(tmp_path / "b.yml", "evaluation:\n  restrict_citations_to_context: true\n")
    )
    assert enabled.evaluation.restrict_citations_to_context is True


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path

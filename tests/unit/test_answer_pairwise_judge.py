from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from code_diver.answering.answer_pairwise_judge import (
    TIE,
    AnswerPairwiseJudge,
    AnswerPairwiseJudgeError,
)
from code_diver.answering.answer_pairwise_report import (
    AnswerPairwiseReport,
    MismatchedPairwiseContextError,
    sign_test_p_value,
)
from code_diver.generation.generation_result import GenerationResult

PROMPT = "{{question}} | {{context}} | A={{answer_a}} | B={{answer_b}}"


def _verdict(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "winner": "A",
        "margin": "clear",
        "dimensions": {
            "correctness": {"winner": "A", "evidence": "src/a.py names the right function"},
            "grounding": {"winner": "A", "evidence": "every claim traces to src/a.py"},
            "coverage": {"winner": TIE, "evidence": "both use src/a.py and src/b.py"},
            "specificity": {"winner": "B", "evidence": "B names load_config(), A says 'the loader'"},
        },
        "critical_errors": [],
        "rationale": "A is more accurate about what run() does.",
    }
    payload.update(overrides)
    return payload


class StubProvider:
    """Records the prompts it is handed and replays a queue of verdicts."""

    model = "stub-judge"

    def __init__(self, verdicts: list[dict[str, Any] | Exception]):
        self.verdicts = list(verdicts)
        self.prompts: list[str] = []

    def generate_json_result(self, prompt: str, *, schema: dict[str, Any] | None = None):
        self.prompts.append(prompt)
        nxt = self.verdicts.pop(0) if self.verdicts else _verdict()
        if isinstance(nxt, Exception):
            raise nxt
        return GenerationResult(
            text=json.dumps(nxt),
            model=self.model,
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        )


def _judge(tmp_path: Path, verdicts: list[dict[str, Any] | Exception]) -> AnswerPairwiseJudge:
    prompt_path = tmp_path / "pairwise.md"
    prompt_path.write_text(PROMPT, encoding="utf-8")
    return AnswerPairwiseJudge(StubProvider(verdicts), prompt_path=prompt_path)


def _compare(judge: AnswerPairwiseJudge, **overrides: Any):
    kwargs: dict[str, Any] = {
        "case_id": "where-config",
        "question": "where is config loaded",
        "context": "src/a.py: def load_config(): ...",
        "answer_in_slot_a": "load_config() in src/a.py",
        "answer_in_slot_b": "the loader handles it",
        "system_in_slot_a": "champion",
        "system_in_slot_b": "arm",
    }
    kwargs.update(overrides)
    return judge.compare(**kwargs)


def test_the_slot_verdict_is_translated_back_into_the_system_that_filled_the_slot(tmp_path):
    judge = _judge(tmp_path, [_verdict(winner="B")])
    result = _compare(judge, system_in_slot_a="champion", system_in_slot_b="arm")
    assert result.winner == "arm"
    # The raw slot verdict survives alongside it -- without it there is no way to separate a
    # judge that prefers better answers from one that prefers whichever it read first.
    assert result.slot_winner == "B"


def test_swapping_the_slots_swaps_the_reported_winner_for_the_same_verdict(tmp_path):
    judge = _judge(tmp_path, [_verdict(winner="B")])
    result = _compare(judge, system_in_slot_a="arm", system_in_slot_b="champion")
    assert result.winner == "champion"


def test_dimension_verdicts_are_translated_out_of_slot_labels_too(tmp_path):
    judge = _judge(tmp_path, [_verdict()])
    result = _compare(judge)
    assert result.dimension_winners == {
        "correctness": "champion",
        "grounding": "champion",
        "coverage": TIE,
        "specificity": "arm",
    }


def test_a_verdict_naming_a_side_this_judge_does_not_have_is_rejected_not_read_as_a_tie(tmp_path):
    # Folding an unreadable verdict into the tie bucket would quietly bias every aggregate
    # toward "no difference", which is the one conclusion this instrument exists to test.
    judge = _judge(tmp_path, [_verdict(winner="whichever")])
    with pytest.raises(AnswerPairwiseJudgeError, match="winner"):
        _compare(judge)


def test_a_missing_dimension_is_rejected_rather_than_scored_as_a_tie(tmp_path):
    judge = _judge(tmp_path, [_verdict(dimensions={"correctness": {"winner": "A", "evidence": "x"}})])
    with pytest.raises(AnswerPairwiseJudgeError, match="grounding"):
        _compare(judge)


def test_comparing_a_system_against_itself_is_refused(tmp_path):
    judge = _judge(tmp_path, [_verdict()])
    with pytest.raises(AnswerPairwiseJudgeError, match="same system"):
        _compare(judge, system_in_slot_a="champion", system_in_slot_b="champion")


def test_a_prompt_missing_a_placeholder_fails_at_load_not_silently_at_judge_time(tmp_path):
    prompt_path = tmp_path / "broken.md"
    prompt_path.write_text("{{question}} {{answer_a}} {{answer_b}}", encoding="utf-8")
    with pytest.raises(ValueError, match=r"\{\{context\}\}"):
        AnswerPairwiseJudge(StubProvider([]), prompt_path=prompt_path)


def test_both_answers_and_the_context_reach_the_prompt(tmp_path):
    judge = _judge(tmp_path, [_verdict()])
    _compare(judge)
    prompt = judge.provider.prompts[0]
    assert "src/a.py: def load_config(): ..." in prompt
    assert "A=load_config() in src/a.py" in prompt
    assert "B=the loader handles it" in prompt


# --- report-level aggregation -------------------------------------------------------------


def _payload(case_ids: list[str], prediction: str, context: str = "shared context") -> dict[str, Any]:
    return {
        "results": [
            {
                "case_id": case_id,
                "question": f"where is {case_id}",
                "context_text": context,
                "prediction": f"{prediction} for {case_id}",
            }
            for case_id in case_ids
        ]
    }


def test_the_baseline_and_arm_take_turns_in_slot_a(tmp_path):
    cases = ["c1", "c2", "c3", "c4"]
    judge = _judge(tmp_path, [_verdict() for _ in cases])
    report = AnswerPairwiseReport(judge, baseline_name="champion", arm_name="arm")
    result = report.compare_payloads(_payload(cases, "base"), _payload(cases, "arm"))
    slots = [c["system_in_slot_a"] for c in result["comparisons"]]
    assert slots == ["champion", "arm", "champion", "arm"]


def test_reports_built_over_different_contexts_are_refused(tmp_path):
    judge = _judge(tmp_path, [_verdict()])
    report = AnswerPairwiseReport(judge, baseline_name="champion", arm_name="arm")
    with pytest.raises(MismatchedPairwiseContextError, match="different context_text"):
        report.compare_payloads(
            _payload(["c1"], "base", context="160 lines of code"),
            _payload(["c1"], "arm", context="64 lines of code"),
        )


def test_a_case_with_no_stored_context_is_refused(tmp_path):
    judge = _judge(tmp_path, [_verdict()])
    report = AnswerPairwiseReport(judge, baseline_name="champion", arm_name="arm")
    with pytest.raises(MismatchedPairwiseContextError, match="no stored context_text"):
        report.compare_payloads(_payload(["c1"], "base", context=""), _payload(["c1"], "arm", context=""))


def test_a_failed_comparison_is_dropped_and_reported_not_counted_as_a_tie(tmp_path):
    cases = ["c1", "c2"]
    judge = _judge(tmp_path, [_verdict(), RuntimeError("server said no")])
    report = AnswerPairwiseReport(judge, baseline_name="champion", arm_name="arm")
    result = report.compare_payloads(_payload(cases, "base"), _payload(cases, "arm"))
    assert result["cases_paired"] == 2
    assert result["cases_judged"] == 1
    assert result["summary"]["ties"] == 0
    assert result["judge_errors"] == [{"case_id": "c2", "error": "server said no"}]


def test_the_summary_counts_wins_for_the_arm_across_alternating_slots(tmp_path):
    cases = ["c1", "c2"]
    # c1 puts champion in slot A and the judge picks B; c2 puts arm in slot A and the judge
    # picks A. Both are arm wins, and only a correct slot map makes them read that way.
    judge = _judge(tmp_path, [_verdict(winner="B"), _verdict(winner="A")])
    report = AnswerPairwiseReport(judge, baseline_name="champion", arm_name="arm")
    result = report.compare_payloads(_payload(cases, "base"), _payload(cases, "arm"))
    summary = result["summary"]
    assert (summary["arm_wins"], summary["arm_losses"], summary["ties"]) == (2, 0, 0)
    assert summary["win_rate"] == 1.0
    # One verdict for each slot: position bias is exactly balanced here.
    assert summary["slot_a_win_share"] == 0.5


def test_critical_errors_are_attributed_to_the_system_that_made_them(tmp_path):
    judge = _judge(
        tmp_path,
        [_verdict(critical_errors=["B: invents a retry loop", "A: wrong line range", "untagged note"])],
    )
    report = AnswerPairwiseReport(judge, baseline_name="champion", arm_name="arm")
    result = report.compare_payloads(_payload(["c1"], "base"), _payload(["c1"], "arm"))
    assert result["summary"]["critical_errors"] == {"champion": 1, "arm": 1, "unattributed": 1}


@pytest.mark.parametrize(
    ("wins", "losses", "expected"),
    [
        (0, 0, 1.0),
        (5, 5, 1.0),
        (10, 0, 2 / 1024),
        (0, 10, 2 / 1024),
        # Two-sided, so both tails: 2 * (C(10,0) + C(10,1)) / 2^10.
        (9, 1, 22 / 1024),
    ],
)
def test_the_sign_test_uses_only_the_discordant_pairs(wins, losses, expected):
    assert sign_test_p_value(wins, losses) == pytest.approx(expected)

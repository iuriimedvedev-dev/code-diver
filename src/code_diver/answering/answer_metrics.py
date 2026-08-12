from __future__ import annotations

from statistics import mean
from typing import Any, ClassVar, Final

from ..explanation import ExplanationMetrics
from ..generation.response_schemas import JUDGE_CRITERIA_NAMES
from ..services.evaluation_statistics import EvaluationStatistics

# Score keys the LLM judge attaches to a row: one per rubric criterion plus the derived
# summary keys `AnswerJudgeRubric.score()` computes. An explicit set, not a `"judge_"`
# prefix match, because `judge_duration_ms` also starts with `judge_` but is a timing
# metric present on essentially every row regardless of judge outcome -- it must keep the
# default-to-zero behaviour every other duration metric gets, not the present-only rule
# `aggregate()` applies to these keys below.
JUDGE_SCORE_METRICS: Final[frozenset[str]] = frozenset(
    {f"judge_{name}" for name in JUDGE_CRITERIA_NAMES} | {"judge_overall", "judge_abstained", "judge_empty_answer"}
)


class AnswerMetrics:
    BINARY_METRICS: ClassVar[set[str]] = {
        "file_hit",
        "candidate_file_hit",
        "context_file_hit",
        "citation_path_valid_rate",
        "citation_line_valid_rate",
        # Deterministic grounding gates. Listed so they get a confidence interval: these are
        # the primary promotion signal for local models, and a 100-case sweep needs the
        # interval to tell a real gap from sampling noise.
        "answer_grounded",
        "answer_nonempty",
        "candidate_bundle_complete",
        "context_bundle_complete",
        # Judge-reported answer classification. Binary so a benchmark sweep gets a
        # Wilson interval on abstention/empty-answer rate, not just a raw mean.
        "judge_abstained",
        "judge_empty_answer",
        # `answer_type` is not a required JUDGE_SCHEMA property (the local judge model
        # often omits it), so a missing value is silently defaulted to "substantive".
        # A high mean here means `judge_abstained` is not trustworthy for this run,
        # since every omitted answer_type was counted as substantive rather than
        # actually judged for abstention.
        "judge_answer_type_missing",
    }

    def __init__(self):
        self.text_metrics = ExplanationMetrics()
        self.statistics = EvaluationStatistics()

    def score(self, prediction: str, reference: str) -> dict[str, float]:
        return self.text_metrics.score(prediction, reference)

    def aggregate(self, rows: list[dict[str, Any]]) -> dict[str, float]:
        metric_keys = sorted(
            {
                key
                for row in rows
                for key, value in (row.get("metrics") or {}).items()
                if isinstance(value, (int, float))
            }
        )
        aggregate: dict[str, float] = {}
        judge_scored_count: int | None = None
        for key in metric_keys:
            values = self._contributing_values(rows, key)
            if not values:
                continue
            aggregate[key] = mean(values)
            aggregate.update(
                self.statistics.summarize(
                    key,
                    values,
                    binary=self._is_binary_metric(key, values),
                )
            )
            if key == "judge_overall":
                judge_scored_count = len(values)
        if judge_scored_count is not None:
            aggregate["judge_scored_count"] = float(judge_scored_count)
        return aggregate

    def _contributing_values(self, rows: list[dict[str, Any]], key: str) -> list[float]:
        """Per-row values feeding `key`'s mean and confidence interval.

        `JUDGE_SCORE_METRICS` keys are present-only: a row whose judging FAILED (a
        `judge_error`, no `judge_*` scores) has no such key and is excluded from the mean
        rather than counted as a zero -- an infrastructure failure (e.g. a schema
        violation the judge model never recovered from) is a missing measurement, not a
        quality measurement, and must not drag `judge_overall` toward "worthless answer".
        Every other metric keeps the original default-to-zero behaviour: a key like
        `file_hit` is legitimately absent on a case with no `expected_paths`, and treating
        that as "exclude" rather than "zero" would change unrelated metrics across the
        whole suite.
        """
        if key in JUDGE_SCORE_METRICS:
            return [
                float((row.get("metrics") or {})[key])
                for row in rows
                if key in (row.get("metrics") or {})
            ]
        return [float((row.get("metrics") or {}).get(key, 0.0)) for row in rows]

    def _is_binary_metric(self, key: str, values: list[float]) -> bool:
        if not all(value in {0.0, 1.0} for value in values):
            return False
        return key in self.BINARY_METRICS or "_hit@" in key or key.endswith("_hit")

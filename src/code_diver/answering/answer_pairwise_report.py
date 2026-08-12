"""Run the pairwise judge across two saved answer reports and aggregate the verdicts.

Two invariants are enforced here rather than left to the caller, because both failures are
silent and both would produce a clean-looking table of meaningless numbers:

1. **Both answers must be judged against the same context.** A reference-free judge grades an
   answer against what it was shown. If each arm is judged on its own context, an arm shown
   less code has less to be incomplete about, and a context-length experiment comes out a tie
   by construction. The two reports must therefore carry identical `context_text` per case.
2. **Slot assignment must alternate.** LLM judges favour whichever answer they read first.
   Assigning the baseline to slot `A` every time turns that bias into a fake result, so the
   slot flips on case index and the realised split is reported as a diagnostic.

The output is a matched-pair table: wins, losses, ties, and an exact two-sided sign test over
the discordant pairs -- the same statistic the rest of this series uses for arm comparisons.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from math import comb
from time import perf_counter
from typing import Any

from ..generation.response_schemas import PAIRWISE_DIMENSION_NAMES, PAIRWISE_MARGINS
from .answer_pairwise_judge import TIE, AnswerPairwiseComparison, AnswerPairwiseJudge


class MismatchedPairwiseContextError(ValueError):
    """The two reports do not show the judge the same code for a case."""


def sign_test_p_value(wins: int, losses: int) -> float:
    """Two-sided exact binomial sign test over the discordant pairs only.

    Ties carry no directional information and are excluded, which is the standard sign-test
    convention. With no discordant pairs there is nothing to test and the p-value is 1.0.
    """
    discordant = wins + losses
    if discordant == 0:
        return 1.0
    extreme = min(wins, losses)
    tail = sum(comb(discordant, k) for k in range(extreme + 1))
    return min(1.0, 2.0 * tail / (2.0**discordant))


@dataclass(slots=True)
class AnswerPairwiseReport:
    judge: AnswerPairwiseJudge
    baseline_name: str
    arm_name: str
    workers: int = 1
    progress_callback: Callable[[int, int, AnswerPairwiseComparison | None], None] | None = None
    errors: list[dict[str, str]] = field(default_factory=list)

    def compare_payloads(
        self,
        baseline_payload: dict[str, Any],
        arm_payload: dict[str, Any],
    ) -> dict[str, Any]:
        pairs = self._pairs(baseline_payload, arm_payload)
        started = perf_counter()
        self.errors = []
        comparisons: list[AnswerPairwiseComparison | None] = [None] * len(pairs)
        worker_count = max(1, min(int(self.workers or 1), max(len(pairs), 1)))
        if worker_count == 1:
            for index, pair in enumerate(pairs):
                comparisons[index] = self._compare_pair(pair)
                self._notify(index + 1, len(pairs), comparisons[index])
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {executor.submit(self._compare_pair, pair): i for i, pair in enumerate(pairs)}
                for done, future in enumerate(as_completed(futures), start=1):
                    index = futures[future]
                    comparisons[index] = future.result()
                    self._notify(done, len(pairs), comparisons[index])
        verdicts = [c for c in comparisons if c is not None]
        return {
            "baseline": self.baseline_name,
            "arm": self.arm_name,
            "prompt": str(self.judge.prompt_path),
            "model": self.judge.provider.model,
            "cases_paired": len(pairs),
            "cases_judged": len(verdicts),
            "judge_errors": list(self.errors),
            "duration_ms": (perf_counter() - started) * 1000,
            "summary": self.summarize(verdicts),
            "comparisons": [verdict.as_json() for verdict in verdicts],
        }

    def summarize(self, verdicts: list[AnswerPairwiseComparison]) -> dict[str, Any]:
        wins = sum(1 for v in verdicts if v.winner == self.arm_name)
        losses = sum(1 for v in verdicts if v.winner == self.baseline_name)
        ties = sum(1 for v in verdicts if v.winner == TIE)
        judged = len(verdicts)
        slot_a_wins = sum(1 for v in verdicts if v.slot_winner == "A")
        decided = sum(1 for v in verdicts if v.slot_winner != TIE)
        return {
            # Framed as the ARM's record against the baseline, so the sign of the result reads
            # the same way as every other arm comparison in this series.
            "arm_wins": wins,
            "arm_losses": losses,
            "ties": ties,
            "win_rate": wins / judged if judged else 0.0,
            "loss_rate": losses / judged if judged else 0.0,
            "tie_rate": ties / judged if judged else 0.0,
            # Ties excluded: among the cases where the judge saw a difference, how often did
            # it favour the arm? This is what the sign test is actually testing.
            "win_rate_decided": wins / (wins + losses) if (wins + losses) else 0.0,
            "sign_test_p": sign_test_p_value(wins, losses),
            # ~0.5 means position bias is small. Far from 0.5 means the judge is partly
            # reading slot order, and the arm-level numbers above are correspondingly softer.
            "slot_a_win_share": slot_a_wins / decided if decided else 0.0,
            "decided_cases": decided,
            "dimensions": self._dimension_summary(verdicts),
            "margins": self._margin_summary(verdicts),
            "critical_errors": self._critical_error_counts(verdicts),
        }

    def _dimension_summary(self, verdicts: list[AnswerPairwiseComparison]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for name in PAIRWISE_DIMENSION_NAMES:
            wins = sum(1 for v in verdicts if v.dimension_winners.get(name) == self.arm_name)
            losses = sum(1 for v in verdicts if v.dimension_winners.get(name) == self.baseline_name)
            summary[name] = {
                "arm_wins": wins,
                "arm_losses": losses,
                "ties": len(verdicts) - wins - losses,
                "sign_test_p": sign_test_p_value(wins, losses),
            }
        return summary

    def _margin_summary(self, verdicts: list[AnswerPairwiseComparison]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for margin in PAIRWISE_MARGINS:
            at_margin = [v for v in verdicts if v.margin == margin]
            summary[margin] = {
                "arm_wins": sum(1 for v in at_margin if v.winner == self.arm_name),
                "arm_losses": sum(1 for v in at_margin if v.winner == self.baseline_name),
                "ties": sum(1 for v in at_margin if v.winner == TIE),
            }
        return summary

    def _critical_error_counts(self, verdicts: list[AnswerPairwiseComparison]) -> dict[str, int]:
        # The prompt asks the judge to tag each error with the slot that made it. Read the tag
        # back through the slot map so the count lands on the right system.
        counts = {self.baseline_name: 0, self.arm_name: 0, "unattributed": 0}
        for verdict in verdicts:
            slots = {"a": verdict.system_in_slot_a, "b": verdict.system_in_slot_b}
            for error in verdict.critical_errors:
                head = error.strip()[:2].lower().rstrip(":").strip()
                counts[slots.get(head, "unattributed")] += 1
        return counts

    def _pairs(
        self,
        baseline_payload: dict[str, Any],
        arm_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        baseline = self._rows(baseline_payload)
        arm = self._rows(arm_payload)
        shared = [case_id for case_id in baseline if case_id in arm]
        pairs: list[dict[str, Any]] = []
        for index, case_id in enumerate(shared):
            base_row, arm_row = baseline[case_id], arm[case_id]
            context = str(base_row.get("context_text") or "")
            if context != str(arm_row.get("context_text") or ""):
                raise MismatchedPairwiseContextError(
                    f"case {case_id!r}: the two reports store different context_text. A "
                    "reference-free judge grades an answer against the code it is shown, so "
                    "comparing answers over different contexts measures the contexts, not the "
                    "answers. Re-point both reports at one common context first."
                )
            if not context.strip():
                raise MismatchedPairwiseContextError(
                    f"case {case_id!r}: no stored context_text. The pairwise judge has no "
                    "ground truth without it and would be comparing prose to prose."
                )
            # Alternate the slot so position bias cancels across the run instead of
            # accumulating in one direction.
            baseline_first = index % 2 == 0
            pairs.append(
                {
                    "case_id": case_id,
                    "question": str(base_row.get("question") or ""),
                    "context": context,
                    "system_in_slot_a": self.baseline_name if baseline_first else self.arm_name,
                    "system_in_slot_b": self.arm_name if baseline_first else self.baseline_name,
                    "answer_in_slot_a": str(
                        (base_row if baseline_first else arm_row).get("prediction") or ""
                    ),
                    "answer_in_slot_b": str(
                        (arm_row if baseline_first else base_row).get("prediction") or ""
                    ),
                }
            )
        return pairs

    def _rows(self, payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            str(row.get("case_id")): row
            for row in payload.get("results") or []
            if isinstance(row, dict) and row.get("case_id")
        }

    def _compare_pair(self, pair: dict[str, Any]) -> AnswerPairwiseComparison | None:
        try:
            return self.judge.compare(
                case_id=pair["case_id"],
                question=pair["question"],
                context=pair["context"],
                answer_in_slot_a=pair["answer_in_slot_a"],
                answer_in_slot_b=pair["answer_in_slot_b"],
                system_in_slot_a=pair["system_in_slot_a"],
                system_in_slot_b=pair["system_in_slot_b"],
            )
        except Exception as exc:
            # Dropped rather than counted as a tie: a failed call is missing data, and folding
            # it into the tie bucket would drag every win rate toward "no difference".
            self.errors.append({"case_id": pair["case_id"], "error": str(exc)})
            return None

    def _notify(self, completed: int, total: int, verdict: AnswerPairwiseComparison | None) -> None:
        if self.progress_callback is not None:
            self.progress_callback(completed, total, verdict)

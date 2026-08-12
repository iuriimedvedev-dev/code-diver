"""Guards an answer-evaluation report against silently shipping fewer rows than requested.

A 100-case judged report (and its `.partial.json` recovery sibling) was silently overwritten
by an unrelated 10-case run that happened to compute the same output path. The mismatch
between the report's row count and the case count the run was actually asked to produce was
discoverable the whole time -- both numbers are already known at the moment each report's
`metrics` block is assembled -- but nothing checked it, so the truncation was found only by
luck, days later, when an unrelated comparator printed "matched cases: 10" for a comparison
that should have matched 100.

This module is called from every place that assembles an answer-evaluation report's
`metrics` block -- `AnswerEvaluator.evaluate()`, `AnswerReportJudge.judge_payload()`, and
`scripts/rejudge_answer_report.py`'s hand-rolled equivalent -- rather than from the CLI/script
call sites that write the resulting payload to disk. Every currently known write call site
is a *final*-report writer: partial/interrupted-run progress is already persisted separately
and incrementally (via each caller's own `row_callback`/`write_partial` mechanism) before the
final write is ever attempted, and every per-row worker in this codebase already catches its
own exceptions and always contributes a placeholder row rather than dropping the row outright.
That means a row-count/case-count mismatch at this point can only indicate a bug or a caller
error (e.g. a stale/reused output path across two differently-sized runs), never a legitimate
in-progress run -- so failing loudly here can never discard work that was not already safely
written elsewhere. Placing the check in the shared `metrics`-assembly functions, rather than
in each CLI/script write site, also keeps the check itself from being duplicated three times
the way the refuse-to-clobber guard was (see `scripts/clobber_guard.py`).
"""

from __future__ import annotations

from typing import Any


class IncompleteAnswerReportError(RuntimeError):
    """Raised when a report's row count does not match the requested case count.

    Carries both counts so callers/logs can report the exact shortfall instead of a generic
    failure message.
    """

    def __init__(self, case_count_requested: int, row_count: int, *, context: str = "") -> None:
        detail = f" ({context})" if context else ""
        super().__init__(
            f"answer report row count ({row_count}) does not match the requested case count "
            f"({case_count_requested}){detail}; refusing to treat this as a complete report -- "
            "if this is a deliberate partial run, write it under its own partial/incomplete "
            "path instead of the final report path"
        )
        self.case_count_requested = case_count_requested
        self.row_count = row_count


def stamp_case_counts(metrics: dict[str, Any], *, case_count_requested: int, row_count: int) -> None:
    """Record `case_count_requested` into `metrics`, alongside the existing `cases` field.

    `metrics["cases"]` already serves as the row count in every report this codebase writes;
    this adds the sibling "how many rows were we asked to produce" field so a future
    comparison can detect a truncated report without re-deriving either number. Stamped before
    `assert_case_count_matches()` is called so the mismatch is visible in the payload even if
    a caller chooses to catch the raised error and persist a diagnostic copy anyway.
    """
    metrics["case_count_requested"] = float(case_count_requested)


def assert_case_count_matches(*, case_count_requested: int, row_count: int, context: str = "") -> None:
    """Fail loudly if `row_count` does not equal `case_count_requested`.

    Raises:
        IncompleteAnswerReportError: if the counts differ.
    """
    if row_count != case_count_requested:
        raise IncompleteAnswerReportError(case_count_requested, row_count, context=context)

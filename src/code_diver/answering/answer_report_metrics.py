from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

from .answer_metrics import AnswerMetrics

# Deterministic, model-free metrics. `context_bundle_complete` leads: it is 1.0 only when
# every expected file made it into the context bundle, so it is the actual bottleneck for a
# small local model -- unlike the judge scores below, nothing here can be inflated by a judge
# grading its own family.
PRIMARY_METRICS: tuple[str, ...] = (
    "context_bundle_complete",
    "cases",
    "candidate_bundle_complete",
    "answer_grounded",
    "answer_nonempty",
    "citation_fabricated_rate",
    "citation_resolved_rate",
    "file_hit",
    "candidate_file_hit@1",
    "candidate_file_hit@3",
    "candidate_file_hit@5",
    "candidate_file_recall@5",
    "candidate_file_mrr",
    "context_file_hit",
    "context_file_recall",
    "context_file_precision",
    "citation_path_valid_rate",
    "citation_line_valid_rate",
    "token_f1",
    "key_token_f1",
    "bigram_f1",
)
# LLM-judge metrics. Secondary and unvalidated: each of the six criteria is reported
# individually so a halo effect on one axis cannot hide behind a composite. No sum-of-criteria
# is computed anywhere -- it rewards citation-format density over correctness and is not a
# reliable ranking signal. `judge_overall` (a weighted mean, not a sum) stays last.
JUDGE_METRICS: tuple[str, ...] = (
    "judge_answer_correctness",
    "judge_evidence_grounding",
    "judge_coverage",
    "judge_citation_quality",
    "judge_specificity",
    "judge_hallucination_control",
    "judge_abstained",
    "judge_overall",
)
# Cost/latency metrics. Neither primary nor judge, kept last purely for operational visibility.
DURATION_METRICS: tuple[str, ...] = (
    "retrieval_duration_ms",
    "context_duration_ms",
    "generation_duration_ms",
    "judge_duration_ms",
    "answer_duration_ms_mean",
)


class AnswerReportMetrics:
    DEFAULT_METRICS: ClassVar[list[str]] = [
        *PRIMARY_METRICS,
        *JUDGE_METRICS,
        *DURATION_METRICS,
    ]

    def load(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def summarize(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = self._rows(payload)
        metrics = dict(payload.get("metrics") or {})
        if rows:
            metrics = AnswerMetrics().aggregate(rows)
            metrics["cases"] = float(len(rows))
        return {
            "settings": payload.get("settings") or {},
            "metrics": metrics,
            "rows": rows,
        }

    def compare(self, paths: list[Path]) -> dict[str, Any]:
        reports = []
        for path in paths:
            payload = self.load(path)
            summary = self.summarize(payload)
            reports.append(
                {
                    "name": path.stem,
                    "path": str(path),
                    "settings": summary["settings"],
                    "metrics": summary["metrics"],
                }
            )
        return {"reports": reports}

    def _rows(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        rows = payload.get("results")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
        return []


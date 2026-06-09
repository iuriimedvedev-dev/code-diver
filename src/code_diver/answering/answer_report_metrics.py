from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .answer_metrics import AnswerMetrics


class AnswerReportMetrics:
    DEFAULT_METRICS = [
        "cases",
        "file_hit",
        "file_recall",
        "file_precision",
        "file_mrr",
        "candidate_file_hit@1",
        "candidate_file_hit@3",
        "candidate_file_hit@5",
        "candidate_file_recall@5",
        "context_file_hit",
        "context_file_recall",
        "context_file_precision",
        "citation_path_valid_rate",
        "citation_line_valid_rate",
        "token_f1",
        "key_token_f1",
        "judge_overall",
        "retrieval_duration_ms",
        "context_duration_ms",
        "generation_duration_ms",
        "judge_duration_ms",
        "answer_duration_ms_mean",
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


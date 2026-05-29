from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .pi_run_log_summary import PiRunLogSummary


class PiRunLogParser:
    def parse(self, path: Path) -> PiRunLogSummary:
        summary = PiRunLogSummary()
        if not path.exists():
            return summary
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            self._apply_line(summary, line)
        return summary

    def _apply_line(self, summary: PiRunLogSummary, line: str) -> None:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return
        if event.get("type") == "message_end":
            self._apply_message(summary, event.get("message"))
        if event.get("type") == "turn_end":
            tool_results = event.get("toolResults") or []
            if isinstance(tool_results, list):
                summary.tool_calls += len(tool_results)

    def _apply_message(self, summary: PiRunLogSummary, message: Any) -> None:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            return
        usage = message.get("usage")
        if not isinstance(usage, dict):
            return
        summary.model_calls += 1
        model = message.get("model")
        if model and str(model) not in summary.models:
            summary.models.append(str(model))
        summary.input_tokens += int(usage.get("input") or 0)
        summary.output_tokens += int(usage.get("output") or 0)
        summary.cache_read_tokens += int(usage.get("cacheRead") or 0)
        summary.cache_write_tokens += int(usage.get("cacheWrite") or 0)
        summary.total_tokens += int(usage.get("totalTokens") or 0)
        cost = usage.get("cost")
        if not isinstance(cost, dict):
            return
        summary.input_cost += float(cost.get("input") or 0.0)
        summary.output_cost += float(cost.get("output") or 0.0)
        summary.cache_read_cost += float(cost.get("cacheRead") or 0.0)
        summary.cache_write_cost += float(cost.get("cacheWrite") or 0.0)
        summary.total_cost += float(cost.get("total") or 0.0)

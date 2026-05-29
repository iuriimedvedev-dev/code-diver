from __future__ import annotations

import json
from typing import Any


class DirectSearchPromptBuilder:
    MAX_HISTORY_CHARS = 50_000

    def build(
        self,
        *,
        hypothesis_name: str,
        query: str,
        tool_manifest: str,
        history: list[dict[str, Any]],
        limit: int,
    ) -> str:
        return "\n\n".join(
            [
                self._instructions(hypothesis_name, limit),
                "Available tools:\n" + tool_manifest,
                f"User search query:\n{query}",
                "Conversation so far:\n" + self._history(history),
            ]
        )

    def _instructions(self, hypothesis_name: str, limit: int) -> str:
        return f"""
You are a code search orchestrator for hypothesis `{hypothesis_name}`.
Use only the listed read-only tools. Find code locations that answer the user's informal query.
Return JSON only. Do not invent paths. Prefer precise files or code ranges with direct evidence.
Tool observations are structured JSON. grep/rg/symbols/tree return candidates, metrics, file names, and line numbers by default; request source text only through code_diver_read or includeText=true when absolutely necessary.

When you need more evidence:
{{
  "reason": "short reasoning",
  "tool_calls": [
    {{"name": "code_diver_rg", "arguments": {{"pattern": "auth|login", "path": "src", "limit": 50}}}}
  ]
}}

When ready, return up to {limit} results:
{{
  "reason": "short reasoning",
  "results": [
    {{"path": "relative/file.py", "startLine": 10, "title": "what is here", "reason": "why it matches"}}
  ],
  "final": "short summary"
}}
""".strip()

    def _history(self, history: list[dict[str, Any]]) -> str:
        if not history:
            return "[]"
        text = json.dumps(history, indent=2, ensure_ascii=False)
        if len(text) <= self.MAX_HISTORY_CHARS:
            return text
        return "... truncated history ...\n" + text[-self.MAX_HISTORY_CHARS :]

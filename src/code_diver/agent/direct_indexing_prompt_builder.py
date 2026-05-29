from __future__ import annotations

import json
from typing import Any


class DirectIndexingPromptBuilder:
    MAX_HISTORY_CHARS = 80_000

    def build(
        self,
        *,
        hypothesis_name: str,
        queries: list[str],
        tool_manifest: str,
        history: list[dict[str, Any]],
        max_items: int,
    ) -> str:
        return "\n\n".join(
            [
                self._instructions(hypothesis_name, max_items),
                "Available tools:\n" + tool_manifest,
                "Evaluation queries:\n" + "\n".join(f"- {query}" for query in queries),
                "Conversation so far:\n" + self._history(history),
            ]
        )

    def _instructions(self, hypothesis_name: str, max_items: int) -> str:
        return f"""
You are a codebase indexing orchestrator for hypothesis `{hypothesis_name}`.
You are indexing an arbitrary repository, not this CLI's own implementation.
Use only the listed read-only tools to discover where useful concepts live.
Prefer compact, high-value code ranges that answer task-style queries such as "where is auth handled" or "where is a command created".
Do not invent file paths, line ranges, or identifiers. Select ranges only after tool evidence.
Use parallel tool calls when independent probes can be run at the same time.
You have a hard budget of 8 rounds. After 3 evidence rounds, prefer saving the best valid file ranges instead of continuing broad exploration.
For `code_diver_inspect`, each list entry must be an object, not a raw string.
Return JSON only.

When you need more evidence:
{{
  "reason": "short reasoning",
  "tool_calls": [
    {{"name": "code_diver_tree", "arguments": {{"path": "src", "depth": 2, "limit": 200}}}}
  ]
}}

When ready to persist the index, return between 1 and {max_items} selected items:
{{
  "reason": "short reasoning",
  "index_items": [
    {{
      "path": "relative/file.py",
      "startLine": 1,
      "endLine": 80,
      "title": "Human readable concept title",
      "reason": "why this range matters for search",
      "kind": "module|class|function|route|config|test|workflow|other"
    }}
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

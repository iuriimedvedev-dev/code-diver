from __future__ import annotations

import json
from typing import Any


class DirectSearchPromptBuilder:
    MAX_HISTORY_CHARS = 16_000

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
                self._instructions(hypothesis_name, limit, self._tool_call_example(tool_manifest)),
                "Available tools:\n" + tool_manifest,
                f"User search query:\n{query}",
                "Conversation so far:\n" + self._history(history),
            ]
        )

    def _instructions(self, hypothesis_name: str, limit: int, tool_call_example: dict[str, Any]) -> str:
        return f"""
You are a code search orchestrator for hypothesis `{hypothesis_name}`.
Use only the listed read-only tools. Find code locations that answer the user's informal query.
Return JSON only. Do not invent paths. Prefer precise files or code ranges with direct evidence.
Tool observations are structured JSON. grep/rg/symbols/tree return candidates, metrics, file names, and line numbers by default; request source text only through code_diver_read or includeText=true when absolutely necessary.
After any tool returns plausible candidates, prefer returning ranked results from those candidates instead of issuing another broad search.

When you need more evidence:
{{
  "reason": "short reasoning",
  "tool_calls": [
    {json.dumps(tool_call_example, ensure_ascii=False)}
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

    def _tool_call_example(self, tool_manifest: str) -> dict[str, Any]:
        try:
            tools = json.loads(tool_manifest)
        except json.JSONDecodeError:
            tools = []
        names = [str(tool.get("name") or "") for tool in tools if isinstance(tool, dict)]
        if "code_diver_search" in names:
            return {"name": "code_diver_search", "arguments": {"query": "auth login session handling", "limit": 10}}
        if "code_diver_rg" in names:
            return {"name": "code_diver_rg", "arguments": {"pattern": "auth|login", "path": "src", "limit": 50}}
        if "code_diver_grep" in names:
            return {"name": "code_diver_grep", "arguments": {"pattern": "login", "path": "src", "limit": 50}}
        if "code_diver_symbols" in names:
            return {"name": "code_diver_symbols", "arguments": {"path": "src", "limit": 100}}
        if "code_diver_tree" in names:
            return {"name": "code_diver_tree", "arguments": {"path": "src", "depth": 2, "limit": 100}}
        if "code_diver_read" in names:
            return {"name": "code_diver_read", "arguments": {"file": "src/example.py", "startLine": 1, "lines": 60}}
        if "code_diver_inspect" in names:
            return {
                "name": "code_diver_inspect",
                "arguments": {"regexes": [{"pattern": "auth|login", "path": "src", "limit": 50}]},
            }
        return {"name": "code_diver_tree", "arguments": {"path": ".", "depth": 1, "limit": 100}}

    def _history(self, history: list[dict[str, Any]]) -> str:
        if not history:
            return "[]"
        text = json.dumps(self._compact_history(history), indent=2, ensure_ascii=False)
        if len(text) <= self.MAX_HISTORY_CHARS:
            return text
        return "... truncated history ...\n" + text[-self.MAX_HISTORY_CHARS :]

    def _compact_history(self, history: list[dict[str, Any]]) -> Any:
        if len(history) <= 2:
            return history
        summaries: list[dict[str, Any]] = []
        for entry in history[:-2]:
            assistant = entry.get("assistant")
            if not isinstance(assistant, dict):
                continue
            tool_calls = assistant.get("tool_calls")
            results = assistant.get("results")
            summaries.append(
                {
                    "round": entry.get("round"),
                    "reason": assistant.get("reason"),
                    "toolCallCount": len(tool_calls) if isinstance(tool_calls, list) else 0,
                    "resultCount": len(results) if isinstance(results, list) else 0,
                }
            )
        return {"previousRounds": summaries[-6:], "recent": history[-2:]}

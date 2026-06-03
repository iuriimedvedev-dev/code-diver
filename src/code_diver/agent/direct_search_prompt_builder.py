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
        tool_names = self._tool_names(tool_manifest)
        return "\n\n".join(
            [
                self._instructions(hypothesis_name, limit, self._tool_call_example(tool_manifest), tool_names),
                "Available tools:\n" + tool_manifest,
                f"User search query:\n{query}",
                "Conversation so far:\n" + self._history(history),
            ]
        )

    def _instructions(
        self,
        hypothesis_name: str,
        limit: int,
        tool_call_example: dict[str, Any],
        tool_names: set[str],
    ) -> str:
        tool_guidance = "\n".join(self._tool_guidance(tool_names))
        policy = "\n".join(self._routing_policy(tool_names))
        default_flow = "\n".join(self._default_flow(tool_names))
        return f"""
You are a universal hybrid code-search orchestrator for hypothesis `{hypothesis_name}`.
Use only the listed read-only tools. Find code locations that answer the user's informal query.
Return JSON only. Do not invent paths. Prefer precise files or code ranges with direct evidence.
Never call a tool that is not listed in Available tools for this hypothesis.
Tool observations are structured JSON. Candidate-producing tools return metrics, file names, and line numbers by default.
The runtime executes independent tool_calls in parallel. When several cheap probes are useful, put them in the same tool_calls array instead of waiting for another round.
{tool_guidance}
If this hypothesis name contains "adaptive", "agentic", or "deep", you are expected to run an iterative search loop: first generate candidates, then run at most one different targeted probe or rewritten-query pass, then rank/verify before final results. The first candidate pass may include 2-4 parallel code_diver_h3_search calls with different precise queries when that improves recall. Do not stop after a single weak candidate list, but do not keep searching after a plausible rerank.

Hybrid tool policy:
{policy}
Default search flow:
{default_flow}
After any tool returns plausible candidates, prefer reranking or returning from those candidates instead of issuing another broad search. In rerank hypotheses, rerank first. After code_diver_rerank returns plausible candidates, return final results from that ranked list; do not call more search, grep, outline, symbols, or read tools unless the rerank result is empty or clearly degraded.

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

    def _tool_names(self, tool_manifest: str) -> set[str]:
        try:
            tools = json.loads(tool_manifest)
        except json.JSONDecodeError:
            return set()
        return {str(tool.get("name") or "") for tool in tools if isinstance(tool, dict)}

    def _tool_guidance(self, names: set[str]) -> list[str]:
        lines: list[str] = []
        if "code_diver_read" in names:
            lines.append("code_diver_read has a hard budget of 10 calls per case. Treat that as a maximum, not a target.")
        if "code_diver_rerank" in names:
            lines.append(
                "code_diver_rerank is an AI ranking tool. It does not discover candidates. Use it after candidate tools returned plausible structured candidates; omit candidates to rerank the current candidate bank, or pass explicit candidates/candidateIds."
            )
            lines.append(
                'If this hypothesis name contains "rerank" and code_diver_rerank is available, you MUST call code_diver_rerank after the first candidate-producing tool returns candidates and before returning final results.'
            )
        if "code_diver_ephemeral_search" in names:
            lines.append(
                "code_diver_ephemeral_search is a localized deep vector search tool. It builds/searches a temporary syntax-aware index only over candidate files from earlier tool results. Use it after the locator found likely files, not as first-pass discovery."
            )
        return lines or ["Use the available tools exactly as listed; if no tool can add evidence, return the best candidates already observed."]

    def _routing_policy(self, names: set[str]) -> list[str]:
        lines: list[str] = []
        if "code_diver_search" in names:
            lines.append(
                '- Semantic or informal "where is X handled" queries: call code_diver_search first. It is the primary hybrid vector/BM25/symbol/GraphRAG candidate generator.'
            )
        if "code_diver_h3_search" in names:
            lines.append(
                "- For IntelliJ-scale or H3 hypotheses, use code_diver_h3_search as the strongest first-pass candidate tool. Keep its default fast mode unless you explicitly need expensive full hybrid profiles. Choose precise code-like queries yourself: identifiers, verb+noun methods, class-name hypotheses, path/package terms, and short lexical anchors. You may call it multiple times with different queries and merge the evidence."
            )
        if "code_diver_tree" in names or "code_diver_rg" in names:
            parts = [tool for tool in ["code_diver_tree", "code_diver_rg"] if tool in names]
            lines.append(f"- Path, config, package, frontend, or filename queries: use {' and '.join(parts)} when they can narrow the file neighborhood.")
        if "code_diver_symbols" in names:
            prefix = "run code_diver_search first or in parallel with " if "code_diver_search" in names else "run "
            lines.append(
                f"- Class/function/method/command/handler/service/model/schema queries: {prefix}code_diver_symbols only when scoped to a known path such as src, a likely package directory, or a top candidate file. Never call code_diver_symbols without path when code_diver_search or code_diver_h3_search is available."
            )
        if "code_diver_outline" in names:
            read_suffix = " before code_diver_read" if "code_diver_read" in names else ""
            lines.append(
                f"- Once candidate files exist, prefer code_diver_outline{read_suffix}. Outline gives imports, symbols, signatures, and line ranges without reading source bodies."
            )
        workflow_tools = [
            tool
            for tool in ["code_diver_h3_search", "code_diver_search", "code_diver_symbols", "code_diver_outline", "code_diver_rg"]
            if tool in names
        ]
        if workflow_tools:
            lines.append(
                f"- Workflow queries such as called, created, dispatched, registered, routed, pipeline, strategy, execution: combine {', '.join(workflow_tools[:3])} with rewritten workflow terms."
            )
        exact_tools = [tool for tool in ["code_diver_grep", "code_diver_rg"] if tool in names]
        if exact_tools:
            lines.append(
                f"- Exact strings, config keys, CLI flags, error names: use {' or '.join(exact_tools)} as an exact probe, preferably parallel with semantic search when available."
            )
            lines.append(
                "- After candidate files exist, unscoped grep/rg is automatically limited to those candidate files. Use explicit path only when you intentionally want a specific package/file scope."
            )
        if "code_diver_ephemeral_search" in names:
            lines.append(
                "- For vague semantic/workflow queries where top candidate files are known but lexical evidence is weak, use code_diver_ephemeral_search over those files and inspect its returned chunks."
            )
        if "code_diver_rerank" in names:
            lines.append(
                "- If candidates are plausible but ordering is uncertain, call code_diver_rerank before final results. Do not call it in the same parallel batch as the candidate-producing search."
            )
        if "code_diver_read" in names:
            lines.append(
                "- code_diver_read is for verification after candidates exist. Read only tiny, targeted ranges from top candidate files, usually 20-60 lines around a symbol, route, handler, setting, or exact match."
            )
        lines.append("- If tool outputs disagree, prefer files supported by multiple allowed signals or by direct evidence from the available tools.")
        return lines

    def _default_flow(self, names: set[str]) -> list[str]:
        steps: list[str] = []
        if "code_diver_h3_search" in names:
            steps.append(
                "Think of 2-4 precise code-search queries, then call code_diver_h3_search for the strongest one or several in parallel."
            )
        elif "code_diver_search" in names:
            steps.append("Generate candidates with code_diver_search using a precise query you choose from the user's wording.")
        candidate_tools = [tool for tool in ["code_diver_symbols", "code_diver_rg", "code_diver_grep", "code_diver_outline"] if tool in names]
        if candidate_tools:
            steps.append(f"If recall looks weak or the query is ambiguous, run a second candidate pass with {', '.join(candidate_tools)}.")
        if "code_diver_ephemeral_search" in names:
            steps.append("If candidate files exist and evidence is semantic rather than lexical, call code_diver_ephemeral_search on those files.")
        verification_tools = [tool for tool in ["code_diver_grep", "code_diver_rg", "code_diver_outline", "code_diver_symbols"] if tool in names]
        if verification_tools:
            steps.append(f"Verify cheaply with {', '.join(verification_tools)} for concrete anchors.")
        if "code_diver_rerank" in names:
            steps.append("Use code_diver_rerank when final ordering is ambiguous.")
        if "code_diver_read" in names:
            steps.append("Use code_diver_read only for the few final candidate ranges that need source evidence.")
        steps.append("Return ranked results once there is enough evidence instead of issuing another broad search.")
        return [f"{index}. {step}" for index, step in enumerate(steps, start=1)]

    def _tool_call_example(self, tool_manifest: str) -> dict[str, Any]:
        try:
            tools = json.loads(tool_manifest)
        except json.JSONDecodeError:
            tools = []
        names = [str(tool.get("name") or "") for tool in tools if isinstance(tool, dict)]
        if "code_diver_h3_search" in names:
            return {
                "name": "code_diver_h3_search",
                "arguments": {
                    "query": "command creation factory handler",
                    "limit": 30,
                    "mode": "fast",
                    "candidateLimit": 90,
                    "profileLimit": 120,
                    "probeFiles": 5,
                },
            }
        if "code_diver_search" in names:
            return {"name": "code_diver_search", "arguments": {"query": "auth login session handling", "limit": 10}}
        if "code_diver_rg" in names:
            return {"name": "code_diver_rg", "arguments": {"pattern": "auth|login", "path": "src", "limit": 50}}
        if "code_diver_grep" in names:
            return {"name": "code_diver_grep", "arguments": {"pattern": "login", "path": "src", "limit": 50}}
        if "code_diver_outline" in names:
            return {"name": "code_diver_outline", "arguments": {"file": "src/example.py", "symbolLimit": 100}}
        if "code_diver_symbols" in names:
            return {"name": "code_diver_symbols", "arguments": {"path": "src", "limit": 100}}
        if "code_diver_tree" in names:
            return {"name": "code_diver_tree", "arguments": {"path": "src", "depth": 2, "limit": 100}}
        if "code_diver_rerank" in names:
            return {"name": "code_diver_rerank", "arguments": {"query": "auth login session handling", "limit": 10, "mode": "compact"}}
        if "code_diver_ephemeral_search" in names:
            return {
                "name": "code_diver_ephemeral_search",
                "arguments": {"query": "auth login session handling", "files": ["src/example.py"], "limit": 10},
            }
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

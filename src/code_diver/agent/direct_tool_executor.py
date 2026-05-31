from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from ..inspection import GrepService, ReadExcerptService, RgService, SymbolsService, TreeService
from .tool_call import ToolCall
from .tool_manifest_builder import ToolManifestBuilder
from .tool_result import ToolResult


class DirectToolExecutor:
    MAX_OUTPUT = 80_000

    def __init__(
        self,
        root: Path,
        allowed_tools: list[str],
        search_handler: Callable[[str, int], str] | None = None,
        exclude: list[str] | None = None,
        max_file_bytes: int = 1_000_000,
    ):
        self.root = root
        self.allowed_tools = set(allowed_tools)
        self.search_handler = search_handler
        self.exclude = exclude or []
        self.max_file_bytes = max_file_bytes

    def execute(self, call: ToolCall) -> ToolResult:
        started = perf_counter()
        if call.name not in self.allowed_tools:
            return ToolResult(call.name, self._json_error(call.name, "tool_not_allowed", started), ok=False)
        try:
            result = self._execute_allowed(call)
            return ToolResult(call.name, self._json_result(call.name, result, started))
        except Exception as exc:
            return ToolResult(call.name, self._json_error(call.name, str(exc), started), ok=False)

    def _execute_allowed(self, call: ToolCall) -> dict[str, Any]:
        args = call.arguments
        if call.name == "code_diver_tree":
            return TreeService(self.root, self.exclude).list_entries(
                path=self._optional_str(args.get("path")),
                max_depth=int(args.get("depth") or 3),
                limit=int(args.get("limit") or 200),
            )
        if call.name == "code_diver_symbols":
            return SymbolsService(self.root, self.exclude, self.max_file_bytes).structured(
                path=self._optional_str(args.get("path")),
                limit=int(args.get("limit") or 200),
            )
        if call.name == "code_diver_grep":
            return GrepService(self.root, self.exclude, self.max_file_bytes).structured(
                str(args.get("pattern") or ""),
                path=self._optional_str(args.get("path")),
                limit=int(args.get("limit") or 100),
                include_text=bool(args.get("includeText") or args.get("include_text") or False),
            )
        if call.name == "code_diver_rg":
            return RgService(self.root, self.exclude, self.max_file_bytes).structured(
                str(args.get("pattern") or ""),
                path=self._optional_str(args.get("path")),
                limit=int(args.get("limit") or 100),
                include_text=bool(args.get("includeText") or args.get("include_text") or False),
            )
        if call.name == "code_diver_read":
            return ReadExcerptService(self.root, self.exclude, self.max_file_bytes).structured(
                str(args.get("file") or args.get("path") or ""),
                start_line=int(args.get("startLine", args.get("start_line", 1)) or 1),
                lines=int(args.get("lines") or 80),
            )
        if call.name == "code_diver_inspect":
            return self._inspect(args)
        if call.name == "code_diver_search":
            if self.search_handler is None:
                raise ValueError("code_diver_search is not available without a search handler")
            raw = self.search_handler(str(args.get("query") or ""), int(args.get("limit") or 10))
            return self._search_payload(raw)
        raise ValueError(f"Unsupported direct tool: {call.name}")

    def _inspect(self, args: dict[str, Any]) -> dict[str, Any]:
        sections: list[dict[str, Any]] = []
        for value in args.get("trees") or []:
            value = self._object_value(value, "path")
            sections.append(
                {
                    "kind": "tree",
                    "query": {"path": value.get("path") or "."},
                    "result": TreeService(self.root, self.exclude).list_entries(
                        path=self._optional_str(value.get("path")),
                        max_depth=int(value.get("depth") or 3),
                        limit=int(value.get("limit") or 200),
                    ),
                }
            )
        for value in args.get("symbols") or []:
            value = self._object_value(value, "path")
            sections.append(
                {
                    "kind": "symbols",
                    "query": {"path": value.get("path") or "."},
                    "result": SymbolsService(self.root, self.exclude, self.max_file_bytes).structured(
                        path=self._optional_str(value.get("path")),
                        limit=int(value.get("limit") or 200),
                    ),
                }
            )
        for value in args.get("literals") or []:
            value = self._object_value(value, "pattern")
            sections.append(
                {
                    "kind": "grep",
                    "query": {"pattern": value.get("pattern"), "path": value.get("path")},
                    "result": GrepService(self.root, self.exclude, self.max_file_bytes).structured(
                        str(value.get("pattern") or ""),
                        path=self._optional_str(value.get("path")),
                        limit=int(value.get("limit") or 100),
                        include_text=bool(value.get("includeText") or value.get("include_text") or False),
                    ),
                }
            )
        for value in args.get("regexes") or []:
            value = self._object_value(value, "pattern")
            sections.append(
                {
                    "kind": "rg",
                    "query": {"pattern": value.get("pattern"), "path": value.get("path")},
                    "result": RgService(self.root, self.exclude, self.max_file_bytes).structured(
                        str(value.get("pattern") or ""),
                        path=self._optional_str(value.get("path")),
                        limit=int(value.get("limit") or 100),
                        include_text=bool(value.get("includeText") or value.get("include_text") or False),
                    ),
                }
            )
        for value in args.get("reads") or []:
            value = self._object_value(value, "file")
            sections.append(
                {
                    "kind": "read",
                    "query": {"path": value.get("file") or value.get("path")},
                    "result": ReadExcerptService(self.root, self.exclude, self.max_file_bytes).structured(
                        str(value.get("file") or value.get("path") or ""),
                        start_line=int(value.get("startLine", value.get("start_line", 1)) or 1),
                        lines=int(value.get("lines") or 80),
                    ),
                }
            )
        return {
            "sections": sections,
            "metrics": {
                "sectionCount": len(sections),
                "empty": not sections,
            },
        }

    def manifest(self) -> str:
        return ToolManifestBuilder().build(self.allowed_tools)

    def _optional_str(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _object_value(self, value: Any, key: str) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        return {key: value}

    def _search_payload(self, raw: str) -> dict[str, Any]:
        try:
            candidates = json.loads(raw)
        except json.JSONDecodeError:
            candidates = []
        if not isinstance(candidates, list):
            candidates = []
        return {
            "candidates": candidates,
            "metrics": {
                "candidateCount": len(candidates),
                "source": "vector",
            },
        }

    def _json_result(self, name: str, result: dict[str, Any], started: float) -> str:
        envelope = {
            "tool": name,
            "ok": True,
            "elapsedMs": (perf_counter() - started) * 1000,
            "result": result,
            "metrics": result.get("metrics", {}),
        }
        return self._bounded_json(envelope)

    def _json_error(self, name: str, error: str, started: float) -> str:
        return self._bounded_json(
            {
                "tool": name,
                "ok": False,
                "elapsedMs": (perf_counter() - started) * 1000,
                "error": error,
                "metrics": {},
            }
        )

    def _bounded_json(self, payload: dict[str, Any]) -> str:
        text = json.dumps(payload, ensure_ascii=False)
        if len(text) <= self.MAX_OUTPUT:
            return text
        compact = {
            "tool": payload.get("tool"),
            "ok": payload.get("ok"),
            "elapsedMs": payload.get("elapsedMs"),
            "metrics": payload.get("metrics", {}),
            "truncated": True,
            "error": "structured tool observation exceeded max output; narrow path/pattern or request fewer lines",
        }
        return json.dumps(compact, ensure_ascii=False)

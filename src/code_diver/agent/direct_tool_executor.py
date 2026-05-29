from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ..inspection import GrepService, ReadExcerptService, RgService, SymbolsService, TreeService
from .tool_call import ToolCall
from .tool_result import ToolResult


class DirectToolExecutor:
    MAX_OUTPUT = 20_000

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
        if call.name not in self.allowed_tools:
            return ToolResult(call.name, f"tool is not allowed: {call.name}", ok=False)
        try:
            content = self._execute_allowed(call)
            return ToolResult(call.name, self._truncate(content))
        except Exception as exc:
            return ToolResult(call.name, str(exc), ok=False)

    def _execute_allowed(self, call: ToolCall) -> str:
        args = call.arguments
        if call.name == "code_diver_tree":
            return TreeService(self.root, self.exclude).render(
                path=self._optional_str(args.get("path")),
                max_depth=int(args.get("depth") or 3),
                limit=int(args.get("limit") or 200),
            )
        if call.name == "code_diver_symbols":
            return SymbolsService(self.root, self.exclude, self.max_file_bytes).render(
                path=self._optional_str(args.get("path")),
                limit=int(args.get("limit") or 200),
            )
        if call.name == "code_diver_grep":
            return GrepService(self.root, self.exclude, self.max_file_bytes).render(
                str(args.get("pattern") or ""),
                path=self._optional_str(args.get("path")),
                limit=int(args.get("limit") or 100),
            )
        if call.name == "code_diver_rg":
            return RgService(self.root, self.exclude, self.max_file_bytes).search(
                str(args.get("pattern") or ""),
                path=self._optional_str(args.get("path")),
                limit=int(args.get("limit") or 100),
            )
        if call.name == "code_diver_read":
            return ReadExcerptService(self.root, self.exclude, self.max_file_bytes).render(
                str(args.get("file") or args.get("path") or ""),
                start_line=int(args.get("startLine", args.get("start_line", 1)) or 1),
                lines=int(args.get("lines") or 80),
            )
        if call.name == "code_diver_inspect":
            return self._inspect(args)
        if call.name == "code_diver_search":
            if self.search_handler is None:
                raise ValueError("code_diver_search is not available without a search handler")
            return self.search_handler(str(args.get("query") or ""), int(args.get("limit") or 10))
        raise ValueError(f"Unsupported direct tool: {call.name}")

    def _inspect(self, args: dict[str, Any]) -> str:
        parts: list[str] = []
        for value in args.get("trees") or []:
            value = self._object_value(value, "path")
            parts.append(
                self._section(
                    f"tree: {value.get('path') or '.'}",
                    TreeService(self.root, self.exclude).render(
                        path=self._optional_str(value.get("path")),
                        max_depth=int(value.get("depth") or 3),
                        limit=int(value.get("limit") or 200),
                    ),
                )
            )
        for value in args.get("symbols") or []:
            value = self._object_value(value, "path")
            parts.append(
                self._section(
                    f"symbols: {value.get('path') or '.'}",
                    SymbolsService(self.root, self.exclude, self.max_file_bytes).render(
                        path=self._optional_str(value.get("path")),
                        limit=int(value.get("limit") or 200),
                    ),
                )
            )
        for value in args.get("literals") or []:
            value = self._object_value(value, "pattern")
            parts.append(
                self._section(
                    f"grep: {value.get('pattern')}",
                    GrepService(self.root, self.exclude, self.max_file_bytes).render(
                        str(value.get("pattern") or ""),
                        path=self._optional_str(value.get("path")),
                        limit=int(value.get("limit") or 100),
                    ),
                )
            )
        for value in args.get("regexes") or []:
            value = self._object_value(value, "pattern")
            parts.append(
                self._section(
                    f"rg: {value.get('pattern')}",
                    RgService(self.root, self.exclude, self.max_file_bytes).search(
                        str(value.get("pattern") or ""),
                        path=self._optional_str(value.get("path")),
                        limit=int(value.get("limit") or 100),
                    ),
                )
            )
        for value in args.get("reads") or []:
            value = self._object_value(value, "file")
            parts.append(
                self._section(
                    f"read: {value.get('file') or value.get('path')}",
                    ReadExcerptService(self.root, self.exclude, self.max_file_bytes).render(
                        str(value.get("file") or value.get("path") or ""),
                        start_line=int(value.get("startLine", value.get("start_line", 1)) or 1),
                        lines=int(value.get("lines") or 80),
                    ),
                )
            )
        return "\n\n".join(parts) if parts else "No probes requested."

    def manifest(self) -> str:
        rows = [
            {
                "name": "code_diver_tree",
                "args": {"path": "optional relative path", "depth": 3, "limit": 200},
            },
            {
                "name": "code_diver_symbols",
                "args": {"path": "optional relative path", "limit": 200},
            },
            {
                "name": "code_diver_grep",
                "args": {"pattern": "literal text", "path": "optional relative path", "limit": 100},
            },
            {
                "name": "code_diver_rg",
                "args": {"pattern": "regex", "path": "optional relative path", "limit": 100},
            },
            {
                "name": "code_diver_read",
                "args": {"file": "relative file path", "startLine": 1, "lines": 80},
            },
            {
                "name": "code_diver_inspect",
                "args": {"trees": [], "symbols": [], "literals": [], "regexes": [], "reads": []},
            },
            {
                "name": "code_diver_search",
                "args": {"query": "free-text query", "limit": 10},
            },
        ]
        return json.dumps([row for row in rows if row["name"] in self.allowed_tools], indent=2)

    def _section(self, title: str, content: str) -> str:
        return f"## {title}\n{content}"

    def _optional_str(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _object_value(self, value: Any, key: str) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        return {key: value}

    def _truncate(self, text: str) -> str:
        if len(text) <= self.MAX_OUTPUT:
            return text
        return text[: self.MAX_OUTPUT] + "\n... truncated ..."

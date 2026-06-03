from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from ..inspection.path_guard import PathGuard
from ..inspection import FileOutlineService, GrepService, ReadExcerptService, RgService, SymbolsService, TreeService
from .candidate_scoped_search import CandidateScopedSearch
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
        h3_search_handler: Callable[[str, int, dict[str, Any]], dict[str, Any]] | None = None,
        rerank_handler: Callable[[str, list[dict[str, Any]], int, dict[str, Any]], dict[str, Any]] | None = None,
        ephemeral_search_handler: Callable[[str, list[str], int, dict[str, Any]], dict[str, Any]] | None = None,
        exclude: list[str] | None = None,
        max_file_bytes: int = 1_000_000,
        max_inspect_reads: int = 10,
        max_scoped_probe_files: int = 30,
    ):
        self.root = root
        self.guard = PathGuard(root)
        self.allowed_tools = set(allowed_tools)
        self.search_handler = search_handler
        self.h3_search_handler = h3_search_handler
        self.rerank_handler = rerank_handler
        self.ephemeral_search_handler = ephemeral_search_handler
        self.exclude = exclude or []
        self.max_file_bytes = max_file_bytes
        self.max_inspect_reads = max_inspect_reads
        self.scoped_search = CandidateScopedSearch(max_scoped_probe_files)
        self.candidate_bank: list[dict[str, Any]] = []

    def execute(self, call: ToolCall) -> ToolResult:
        started = perf_counter()
        if call.name not in self.allowed_tools:
            return ToolResult(call.name, self._json_error(call.name, "tool_not_allowed", started), ok=False)
        try:
            result = self._execute_allowed(call)
            self._remember_candidates(result)
            degraded = self._result_degraded(result)
            return ToolResult(call.name, self._json_result(call.name, result, started, degraded), ok=not degraded)
        except Exception as exc:
            return ToolResult(call.name, self._json_error(call.name, str(exc), started), ok=False)

    def _execute_allowed(self, call: ToolCall) -> dict[str, Any]:
        args = call.arguments
        if call.name == "code_diver_tree":
            return TreeService(self.root, self.exclude).list_entries(
                path=self._validated_optional_path(args.get("path")),
                max_depth=int(args.get("depth") or 3),
                limit=int(args.get("limit") or 200),
            )
        if call.name == "code_diver_symbols":
            return self._symbols(args)
        if call.name == "code_diver_outline":
            return FileOutlineService(self.root, self.exclude, self.max_file_bytes).structured(
                self._validated_required_path(args.get("file") or args.get("path")),
                import_limit=int(args.get("importLimit", args.get("import_limit", 80)) or 80),
                symbol_limit=int(args.get("symbolLimit", args.get("symbol_limit", 200)) or 200),
            )
        if call.name == "code_diver_grep":
            return self._grep(args)
        if call.name == "code_diver_rg":
            return self._rg(args)
        if call.name == "code_diver_read":
            return ReadExcerptService(self.root, self.exclude, self.max_file_bytes).structured(
                self._validated_required_path(args.get("file") or args.get("path")),
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
        if call.name == "code_diver_h3_search":
            if self.h3_search_handler is None:
                raise ValueError("code_diver_h3_search is not available without an H3 search handler")
            return self.h3_search_handler(str(args.get("query") or ""), int(args.get("limit") or 30), args)
        if call.name == "code_diver_rerank":
            if self.rerank_handler is None:
                raise ValueError("code_diver_rerank is not available without a rerank handler")
            candidates = args.get("candidates")
            if not isinstance(candidates, list) or not candidates:
                candidates = self.candidate_bank
            candidates = self._filtered_candidates(candidates, args.get("candidateIds") or args.get("candidate_ids"))
            query = str(args.get("query") or "")
            return self.rerank_handler(query, candidates, int(args.get("limit") or 10), args)
        if call.name == "code_diver_ephemeral_search":
            if self.ephemeral_search_handler is None:
                raise ValueError("code_diver_ephemeral_search is not available without an ephemeral search handler")
            query = str(args.get("query") or "")
            files = self._candidate_files(args.get("files") or args.get("paths") or args.get("candidateFiles"))
            if not files:
                files = self._candidate_files(self.candidate_bank)
            if not files:
                raise ValueError("code_diver_ephemeral_search requires candidate files")
            return self.ephemeral_search_handler(query, files, int(args.get("limit") or 10), args)
        raise ValueError(f"Unsupported direct tool: {call.name}")

    def _inspect(self, args: dict[str, Any]) -> dict[str, Any]:
        sections: list[dict[str, Any]] = []
        reads_used = 0
        for value in args.get("trees") or []:
            value = self._object_value(value, "path")
            path = self._validated_optional_path(value.get("path"))
            sections.append(
                {
                    "kind": "tree",
                    "query": {"path": path or "."},
                    "result": TreeService(self.root, self.exclude).list_entries(
                        path=path,
                        max_depth=int(value.get("depth") or 3),
                        limit=int(value.get("limit") or 200),
                    ),
                }
            )
        for value in args.get("outlines") or []:
            value = self._object_value(value, "path")
            path = self._validated_required_path(value.get("file") or value.get("path"))
            sections.append(
                {
                    "kind": "outline",
                    "query": {"path": path},
                    "result": FileOutlineService(self.root, self.exclude, self.max_file_bytes).structured(
                        path,
                        import_limit=int(value.get("importLimit", value.get("import_limit", 80)) or 80),
                        symbol_limit=int(value.get("symbolLimit", value.get("symbol_limit", 200)) or 200),
                    ),
                }
            )
        for value in args.get("symbols") or []:
            value = self._object_value(value, "path")
            path = self._validated_optional_path(value.get("path"))
            sections.append(
                {
                    "kind": "symbols",
                    "query": {"path": path or "."},
                    "result": SymbolsService(self.root, self.exclude, self.max_file_bytes).structured(
                        path=path,
                        limit=int(value.get("limit") or 200),
                        query=self._optional_str(value.get("query") or value.get("symbol") or value.get("terms")),
                    ),
                }
            )
        for value in args.get("literals") or []:
            value = self._object_value(value, "pattern")
            path = self._validated_optional_path(value.get("path"))
            sections.append(
                {
                    "kind": "grep",
                    "query": {"pattern": value.get("pattern"), "path": path},
                    "result": self._grep(value),
                }
            )
        for value in args.get("regexes") or []:
            value = self._object_value(value, "pattern")
            path = self._validated_optional_path(value.get("path"))
            sections.append(
                {
                    "kind": "rg",
                    "query": {"pattern": value.get("pattern"), "path": path},
                    "result": self._rg(value),
                }
            )
        for value in args.get("reads") or []:
            value = self._object_value(value, "file")
            if reads_used >= self.max_inspect_reads:
                sections.append(
                    {
                        "kind": "read",
                        "query": {"path": value.get("file") or value.get("path")},
                        "result": {
                            "ok": False,
                            "error": f"inspect_read_budget_exceeded: max {self.max_inspect_reads} reads per inspect call",
                        },
                    }
                )
                continue
            reads_used += 1
            path = self._validated_required_path(value.get("file") or value.get("path"))
            sections.append(
                {
                    "kind": "read",
                    "query": {"path": path},
                    "result": ReadExcerptService(self.root, self.exclude, self.max_file_bytes).structured(
                        path,
                        start_line=int(value.get("startLine", value.get("start_line", 1)) or 1),
                        lines=int(value.get("lines") or 80),
                    ),
                }
            )
        return {
            "sections": sections,
            "metrics": {
                "sectionCount": len(sections),
                "readCount": reads_used,
                "empty": not sections,
            },
        }

    def _grep(self, args: dict[str, Any]) -> dict[str, Any]:
        pattern = str(args.get("pattern") or "")
        requested_path = self._optional_str(args.get("path"))
        path = self._validated_optional_path(requested_path)
        limit = int(args.get("limit") or 100)
        include_text = bool(args.get("includeText") or args.get("include_text") or False)
        scope_paths = self._candidate_scope_paths(requested_path)
        if scope_paths:
            return self._scoped_grep(pattern, scope_paths, limit, include_text, regex=False)
        return GrepService(self.root, self.exclude, self.max_file_bytes).structured(
            pattern,
            path=path,
            limit=limit,
            include_text=include_text,
        )

    def _rg(self, args: dict[str, Any]) -> dict[str, Any]:
        pattern = str(args.get("pattern") or "")
        requested_path = self._optional_str(args.get("path"))
        path = self._validated_optional_path(requested_path)
        limit = int(args.get("limit") or 100)
        include_text = bool(args.get("includeText") or args.get("include_text") or False)
        scope_paths = self._candidate_scope_paths(requested_path)
        if scope_paths:
            return self._scoped_grep(pattern, scope_paths, limit, include_text, regex=True)
        return RgService(self.root, self.exclude, self.max_file_bytes).structured(
            pattern,
            path=path,
            limit=limit,
            include_text=include_text,
        )

    def _symbols(self, args: dict[str, Any]) -> dict[str, Any]:
        requested_path = self._optional_str(args.get("path"))
        path = self._validated_optional_path(requested_path)
        limit = int(args.get("limit") or 200)
        query = self._optional_str(args.get("query") or args.get("symbol") or args.get("terms"))
        scope_paths = self._candidate_scope_paths(requested_path)
        if scope_paths:
            return self._scoped_symbols(scope_paths, limit, query)
        if path is None and self._has_candidate_search_tool():
            raise ValueError("code_diver_symbols requires a path or candidate bank when candidate search is available")
        return SymbolsService(self.root, self.exclude, self.max_file_bytes).structured(
            path=path,
            limit=limit,
            query=query,
        )

    def _candidate_scope_paths(self, requested_path: str | None) -> list[str]:
        paths = self.scoped_search.paths(requested_path, self.candidate_bank)
        valid_paths: list[str] = []
        for path in paths:
            valid_paths.append(self._validated_required_path(path))
        return valid_paths

    def _scoped_grep(
        self,
        pattern: str,
        paths: list[str],
        limit: int,
        include_text: bool,
        *,
        regex: bool,
    ) -> dict[str, Any]:
        matches = []
        remaining = max(limit, 1)
        grep_service = GrepService(self.root, self.exclude, self.max_file_bytes)
        rg_service = RgService(self.root, self.exclude, self.max_file_bytes)
        for path in paths:
            if remaining <= 0:
                break
            if regex:
                found = rg_service.search_matches(pattern, path=path, limit=remaining)
            else:
                found = grep_service.search(pattern, path=path, limit=remaining)
            matches.extend(found)
            remaining = max(limit - len(matches), 0)
        return {
            "query": {
                "pattern": pattern,
                "path": None,
                "regex": regex,
                "includeText": include_text,
                "scopedToCandidateFiles": True,
                "candidateScopeFiles": paths,
            },
            "candidates": self._grep_candidates(matches),
            "matches": [self._grep_match_json(match, include_text) for match in matches],
            "metrics": {
                "matchCount": len(matches),
                "candidateCount": len({match.path for match in matches}),
                "limit": limit,
                "truncated": len(matches) >= limit,
                "scopedToCandidateFiles": True,
                "scopedFileCount": len(paths),
                "backend": "rg" if regex else "grep",
            },
        }

    def _scoped_symbols(self, paths: list[str], limit: int, query: str | None) -> dict[str, Any]:
        service = SymbolsService(self.root, self.exclude, self.max_file_bytes)
        symbols: list[dict[str, Any]] = []
        scanned_files = 0
        remaining = max(limit, 1)
        for path in paths:
            if remaining <= 0:
                break
            payload = service.structured(path=path, limit=remaining, query=query)
            rows = payload.get("symbols") or []
            if isinstance(rows, list):
                symbols.extend(row for row in rows if isinstance(row, dict))
            metrics = payload.get("metrics") or {}
            if isinstance(metrics, dict):
                scanned_files += int(metrics.get("scannedFiles") or 0)
            remaining = max(limit - len(symbols), 0)
        return {
            "query": {
                "path": None,
                "query": query,
                "scopedToCandidateFiles": True,
                "candidateScopeFiles": paths,
            },
            "symbols": symbols,
            "candidates": self._symbol_candidates(symbols),
            "metrics": {
                "symbolCount": len(symbols),
                "candidateCount": len({symbol.get("path") for symbol in symbols}),
                "scannedFiles": scanned_files,
                "limit": limit,
                "truncated": len(symbols) >= limit,
                "scopedToCandidateFiles": True,
                "scopedFileCount": len(paths),
            },
        }

    def _has_candidate_search_tool(self) -> bool:
        return bool({"code_diver_search", "code_diver_h3_search"} & self.allowed_tools)

    def manifest(self) -> str:
        return ToolManifestBuilder().build(self.allowed_tools)

    def _optional_str(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _validated_optional_path(self, value: Any) -> str | None:
        path = self._optional_str(value)
        self.guard.resolve(path)
        return path

    def _validated_required_path(self, value: Any) -> str:
        path = self._optional_str(value)
        if path is None:
            raise ValueError("path is required")
        self.guard.resolve(path)
        return path

    def _object_value(self, value: Any, key: str) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        return {key: value}

    def _grep_match_json(self, match: Any, include_text: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {"path": match.path, "line": match.line}
        if include_text:
            payload["text"] = match.text
        return payload

    def _grep_candidates(self, matches: list[Any]) -> list[dict[str, Any]]:
        by_path: dict[str, list[int]] = {}
        for match in matches:
            by_path.setdefault(match.path, []).append(match.line)
        candidates: list[dict[str, Any]] = []
        for path, lines in by_path.items():
            candidates.append(
                {
                    "path": path,
                    "startLine": min(lines),
                    "endLine": max(lines),
                    "matchCount": len(lines),
                    "confidence": min(0.95, 0.45 + len(lines) * 0.08),
                    "evidenceLines": lines[:20],
                }
            )
        candidates.sort(key=lambda item: (-int(item["matchCount"]), item["path"]))
        return candidates

    def _symbol_candidates(self, symbols: list[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates: dict[str, dict[str, Any]] = {}
        for symbol in symbols:
            path = str(symbol.get("path") or "")
            if not path:
                continue
            start_line = int(symbol.get("startLine") or 1)
            end_line = int(symbol.get("endLine") or start_line)
            candidate = candidates.setdefault(
                path,
                {
                    "path": path,
                    "startLine": start_line,
                    "endLine": end_line,
                    "symbolCount": 0,
                    "confidence": 0.55,
                    "symbols": [],
                },
            )
            candidate["startLine"] = min(int(candidate["startLine"]), start_line)
            candidate["endLine"] = max(int(candidate["endLine"]), end_line)
            candidate["symbolCount"] += 1
            candidate["confidence"] = min(0.95, 0.55 + int(candidate["symbolCount"]) * 0.05)
            candidate["symbols"].append(str(symbol.get("name") or ""))
        return sorted(candidates.values(), key=lambda item: (-int(item["symbolCount"]), item["path"]))

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

    def _remember_candidates(self, result: dict[str, Any]) -> None:
        for candidate in self._candidate_rows(result):
            if isinstance(candidate, dict):
                self.candidate_bank.append(candidate)
        self.candidate_bank = self._dedupe_candidates(self.candidate_bank)[-200:]

    def _candidate_rows(self, value: Any) -> list[Any]:
        if not isinstance(value, dict):
            return []
        rows: list[Any] = []
        candidates = value.get("candidates")
        if isinstance(candidates, list):
            rows.extend(candidates)
        sections = value.get("sections")
        if isinstance(sections, list):
            for section in sections:
                if not isinstance(section, dict):
                    continue
                rows.extend(self._candidate_rows(section.get("result")))
        return rows

    def _filtered_candidates(self, candidates: list[Any], candidate_ids: Any) -> list[dict[str, Any]]:
        rows = [candidate for candidate in candidates if isinstance(candidate, dict)]
        if not isinstance(candidate_ids, list) or not candidate_ids:
            return self._dedupe_candidates(rows)
        wanted = {str(value) for value in candidate_ids}
        return [
            candidate
            for candidate in self._dedupe_candidates(rows)
            if str(candidate.get("id") or candidate.get("path") or "") in wanted
        ]

    def _dedupe_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for candidate in candidates:
            key = str(candidate.get("id") or f"{candidate.get('path')}:{candidate.get('startLine')}")
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return deduped

    def _candidate_files(self, values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        paths: list[str] = []
        for value in values:
            if isinstance(value, str):
                path = value.strip()
            elif isinstance(value, dict):
                path = str(value.get("path") or value.get("file") or "").strip()
            else:
                path = ""
            if path and path not in paths:
                paths.append(path)
        return paths

    def _json_result(self, name: str, result: dict[str, Any], started: float, degraded: bool) -> str:
        metrics = result.get("metrics", {})
        envelope = {
            "tool": name,
            "ok": not degraded,
            "elapsedMs": (perf_counter() - started) * 1000,
            "result": result,
            "metrics": metrics,
        }
        if degraded:
            envelope["degraded"] = True
            envelope["error"] = str(metrics.get("error") or "tool_result_degraded")
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
        metrics = dict(payload.get("metrics", {}))
        metrics["errors"] = int(metrics.get("errors") or 0) + 1
        metrics["degraded"] = True
        metrics["error"] = "structured tool observation exceeded max output; narrow path/pattern or request fewer lines"
        compact = {
            "tool": payload.get("tool"),
            "ok": False,
            "elapsedMs": payload.get("elapsedMs"),
            "metrics": metrics,
            "degraded": True,
            "truncated": True,
            "error": metrics["error"],
        }
        return json.dumps(compact, ensure_ascii=False)

    def _result_degraded(self, result: dict[str, Any]) -> bool:
        metrics = result.get("metrics", {})
        if not isinstance(metrics, dict):
            return False
        return bool(result.get("degraded") or metrics.get("degraded") or metrics.get("errors"))

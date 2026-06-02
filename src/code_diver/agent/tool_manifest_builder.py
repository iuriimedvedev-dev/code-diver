from __future__ import annotations

import json


class ToolManifestBuilder:
    def build(self, allowed_tools: set[str]) -> str:
        return json.dumps([row for row in self._rows() if row["name"] in allowed_tools], indent=2)

    def _rows(self) -> list[dict]:
        return [
            {
                "name": "code_diver_search",
                "stage": "candidate_generation",
                "parallel_safe": True,
                "best_for": [
                    "semantic/informal queries",
                    "hybrid vector+lexical+symbol+graph candidates",
                    "first-pass top files with scores and indexKind",
                ],
                "avoid_for": ["exact-only confirmation when a concrete literal is known"],
                "returns": "ranked structured candidates with path, line range, score, and indexKind",
                "args": {"query": "free-text query", "limit": 10},
            },
            {
                "name": "code_diver_tree",
                "stage": "repo_map",
                "parallel_safe": True,
                "best_for": ["path/config/package/docker/frontend questions", "scoping search to likely directories"],
                "avoid_for": ["deep behavior questions without a path clue"],
                "returns": "structured entries: path, kind, depth, metrics",
                "args": {"path": "optional relative path", "depth": 3, "limit": 200},
            },
            {
                "name": "code_diver_symbols",
                "stage": "structure_probe",
                "parallel_safe": True,
                "best_for": ["classes", "functions", "methods", "commands", "handlers", "services", "models"],
                "avoid_for": [
                    "queries that only mention prose concepts with no structural clue",
                    "full-repo scans when code_diver_search can provide candidate paths first",
                ],
                "returns": "structured symbols and file candidates, no source text",
                "args": {
                    "path": "relative file or directory; required when code_diver_search is also available",
                    "limit": 100,
                    "query": "optional fuzzy symbol name or terms",
                },
            },
            {
                "name": "code_diver_outline",
                "stage": "structure_probe",
                "parallel_safe": True,
                "best_for": [
                    "inspecting a candidate file before reading source text",
                    "multiline signatures where raw grep may miss the definition",
                    "choosing exact line ranges for follow-up code_diver_read calls",
                ],
                "avoid_for": ["full-repo discovery", "exact literal search across many files"],
                "returns": "file imports, symbols, line ranges, and file-level candidate metadata; no source bodies",
                "args": {
                    "file": "relative file path",
                    "symbolLimit": 200,
                    "importLimit": 80,
                },
            },
            {
                "name": "code_diver_grep",
                "stage": "exact_probe",
                "parallel_safe": True,
                "best_for": ["known literal names", "config keys", "error messages", "CLI flags"],
                "avoid_for": ["broad informal queries where the anchor is unknown"],
                "returns": "structured file candidates and line numbers; text only when includeText=true",
                "args": {"pattern": "literal text", "path": "optional relative path", "limit": 100},
            },
            {
                "name": "code_diver_rg",
                "stage": "regex_probe",
                "parallel_safe": True,
                "best_for": ["small regex over concrete anchors", "handler|route|command alternatives"],
                "avoid_for": ["large vague regexes across the whole repo"],
                "returns": "structured file candidates and line numbers; text only when includeText=true",
                "args": {"pattern": "regex", "path": "optional relative path", "limit": 100},
            },
            {
                "name": "code_diver_inspect",
                "stage": "batched_probe",
                "parallel_safe": True,
                "best_for": ["one bounded mixed probe when tree/symbols/rg/read are all needed"],
                "avoid_for": ["unbounded broad discovery; keep sections small"],
                "returns": "structured sections combining tree, outlines, symbols, grep, rg, and read",
                "args": {"trees": [], "outlines": [], "symbols": [], "literals": [], "regexes": [], "reads": []},
            },
            {
                "name": "code_diver_rerank",
                "stage": "ranking",
                "parallel_safe": False,
                "best_for": [
                    "ranking candidates after code_diver_search, rg, grep, or symbols produced plausible matches",
                    "semantic/workflow ambiguity where final ordering matters",
                    "choosing the best owning file/symbol before read verification",
                ],
                "avoid_for": [
                    "first-pass discovery",
                    "same parallel batch as the search call that should produce its candidates",
                ],
                "returns": "reranked structured candidates with confidence, model usage metrics, file names, and line numbers",
                "args": {
                    "query": "original user query",
                    "limit": 10,
                    "mode": "compact|file_first|precision|base_rank_prior",
                    "candidateIds": "optional IDs from previous candidate observations; omit to rerank current candidate bank",
                    "candidates": "optional explicit structured candidate list",
                },
            },
            {
                "name": "code_diver_read",
                "stage": "verification",
                "parallel_safe": True,
                "best_for": [
                    "targeted verification of top candidates",
                    "reading one exact symbol, route, handler, setting, or match range",
                ],
                "avoid_for": [
                    "first-pass discovery",
                    "reading many files before candidate generation",
                    "whole-file reading when grep/rg can verify the anchor",
                ],
                "returns": "bounded source text lines for one known file/range; hard budget 10 calls per case",
                "args": {"file": "relative file path", "startLine": 1, "lines": "20-60 preferred, 80 max"},
            },
        ]

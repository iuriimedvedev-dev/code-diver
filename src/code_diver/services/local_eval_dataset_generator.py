from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, ClassVar

from ..domain import CodeItem
from ..settings import SchemaKey
from .codebase_scanner import CodebaseScanner


class LocalEvalDatasetGenerator:
    _SYMBOL_ROW_RE = re.compile(r"^-\s+(?P<kind>[A-Za-z ]+)\s+(?P<name>[A-Za-z_][\w$.]*):", re.MULTILINE)
    _TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")
    _STOP_WORDS: ClassVar[set[str]] = {
        "src",
        "lib",
        "app",
        "test",
        "tests",
        "main",
        "index",
        "code",
        "file",
        "files",
    }

    def __init__(self, scanner: CodebaseScanner):
        self.scanner = scanner

    def generate(self, root: Path, output: Path, case_count: int) -> list[dict[str, Any]]:
        if case_count <= 0:
            raise ValueError("Generated dataset case count must be positive.")
        grouped = self._items_by_path(self.scanner.scan(root))
        candidates = self._candidate_rows(grouped)
        rows = candidates[:case_count]
        if not rows:
            raise ValueError(f"No local evaluation cases could be generated from {root}.")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
        return rows

    def _items_by_path(self, items: list[CodeItem]) -> dict[str, list[CodeItem]]:
        grouped: dict[str, list[CodeItem]] = {}
        for item in items:
            grouped.setdefault(item.path, []).append(item)
        return dict(sorted(grouped.items()))

    def _candidate_rows(self, grouped: dict[str, list[CodeItem]]) -> list[dict[str, Any]]:
        per_file = [self._rows_for_file(path, items) for path, items in grouped.items()]
        rows: list[dict[str, Any]] = []
        seen_queries: set[str] = set()
        max_depth = max((len(file_rows) for file_rows in per_file), default=0)
        for offset in range(max_depth):
            for file_rows in per_file:
                if offset >= len(file_rows):
                    continue
                row = file_rows[offset]
                query_key = str(row[SchemaKey.QUERY.value]).lower()
                if query_key in seen_queries:
                    continue
                seen_queries.add(query_key)
                rows.append(row)
        return rows

    def _rows_for_file(self, path: str, items: list[CodeItem]) -> list[dict[str, Any]]:
        combined = "\n".join(item.content for item in sorted(items, key=lambda item: item.title))
        file_name = Path(path).name
        stem_tokens = self._readable_tokens(Path(path).stem)
        path_tokens = self._readable_tokens(" ".join(Path(path).parts[:-1]))
        rows = [
            self._row(path, "path", f"find the file named {file_name}"),
        ]
        if stem_tokens:
            rows.append(self._row(path, "file_intent", f"where is {stem_tokens} implemented?"))
        if path_tokens and path_tokens != stem_tokens:
            rows.append(self._row(path, "path_intent", f"where is {stem_tokens or file_name} in {path_tokens}?"))
        for kind, name in self._symbols(combined)[:2]:
            readable = self._readable_tokens(name)
            if not readable:
                continue
            rows.append(self._row(path, f"symbol_{kind}", f"where is {name} defined?"))
            if len(readable.split()) > 1:
                rows.append(self._row(path, f"behavior_{kind}", f"where is {readable} handled?"))
        return rows

    def _row(self, path: str, kind: str, query: str) -> dict[str, Any]:
        digest = hashlib.sha1(f"{kind}:{path}:{query}".encode()).hexdigest()[:12]
        return {
            SchemaKey.ID.value: f"local-{digest}",
            SchemaKey.QUERY.value: query,
            SchemaKey.EXPECTED.value: [path],
            SchemaKey.METADATA.value: {
                SchemaKey.SOURCE.value: "local_eval_generator",
                SchemaKey.KIND.value: kind,
            },
        }

    def _symbols(self, text: str) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        seen: set[str] = set()
        for match in self._SYMBOL_ROW_RE.finditer(text):
            name = match.group("name").strip()
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append((" ".join(match.group("kind").split()), name))
        return rows

    def _readable_tokens(self, value: str) -> str:
        spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value.replace("_", " ").replace("-", " "))
        tokens = [
            token.lower()
            for token in self._TOKEN_RE.findall(spaced)
            if len(token) > 1 and token.lower() not in self._STOP_WORDS
        ]
        return " ".join(tokens[:8])

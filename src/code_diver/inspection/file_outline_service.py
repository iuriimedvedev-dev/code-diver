from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..services.code_symbol_extractor import CodeSymbolExtractor
from .ignore_matcher import IgnoreMatcher
from .path_guard import PathGuard


class FileOutlineService:
    def __init__(self, root: Path, exclude: list[str] | None = None, max_file_bytes: int = 1_000_000):
        self.root = root.resolve()
        self.guard = PathGuard(self.root)
        self.ignore = IgnoreMatcher(self.root, exclude)
        self.extractor = CodeSymbolExtractor()
        self.max_file_bytes = max_file_bytes

    def structured(self, path: str, import_limit: int = 80, symbol_limit: int = 200) -> dict[str, Any]:
        target = self.guard.resolve(path)
        if self.ignore.ignored(target):
            raise ValueError(f"Path is ignored: {path}")
        if not target.is_file():
            raise ValueError(f"Path is not a file: {path}")
        if target.stat().st_size > self.max_file_bytes:
            raise ValueError(f"Path exceeds max file size: {path}")

        text = target.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        rel_path = target.relative_to(self.root).as_posix()
        extracted_symbols = self.extractor.extract(rel_path, text)
        symbols = [
            {
                "name": symbol.name,
                "kind": symbol.kind,
                "signature": symbol.signature,
                "startLine": symbol.start_line,
                "endLine": symbol.end_line,
            }
            for symbol in extracted_symbols[: max(symbol_limit, 1)]
        ]
        imports = self._imports(lines, import_limit)
        return {
            "query": {"path": path},
            "path": rel_path,
            "fileLines": len(lines),
            "imports": imports,
            "symbols": symbols,
            "candidates": [
                {
                    "path": rel_path,
                    "startLine": symbols[0]["startLine"] if symbols else 1,
                    "endLine": symbols[-1]["endLine"] if symbols else min(len(lines), 1),
                    "symbolCount": len(symbols),
                    "confidence": min(0.95, 0.55 + len(symbols) * 0.03),
                    "symbols": [symbol["name"] for symbol in symbols[:20]],
                }
            ],
            "metrics": {
                "symbolCount": len(symbols),
                "importCount": len(imports),
                "fileLines": len(lines),
                "symbolLimit": symbol_limit,
                "importLimit": import_limit,
                "truncatedSymbols": len(extracted_symbols) > len(symbols),
            },
        }

    def _imports(self, lines: list[str], limit: int) -> list[dict[str, Any]]:
        imports: list[dict[str, Any]] = []
        for line_number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if self._is_import(stripped):
                imports.append({"line": line_number, "text": stripped[:240]})
                if len(imports) >= max(limit, 1):
                    break
        return imports

    def _is_import(self, text: str) -> bool:
        return bool(
            text.startswith(("import ", "from ")) or re.match(r"^(?:const|let|var)\s+.+\s+=\s+require\(", text)
        )

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..services import CodeSymbolExtractor
from .ignore_matcher import IgnoreMatcher
from .path_guard import PathGuard


class SymbolsService:
    def __init__(self, root: Path, exclude: list[str] | None = None, max_file_bytes: int = 1_000_000):
        self.root = root.resolve()
        self.guard = PathGuard(self.root)
        self.ignore = IgnoreMatcher(self.root, exclude)
        self.extractor = CodeSymbolExtractor()
        self.max_file_bytes = max_file_bytes

    def render(self, path: str | None = None, limit: int = 200) -> str:
        structured = self.structured(path=path, limit=limit)
        return "\n".join(
            f"{symbol['path']}:{symbol['startLine']}: {symbol['kind']} {symbol['name']} - {symbol['signature']}"
            for symbol in structured["symbols"]
        )

    def structured(self, path: str | None = None, limit: int = 200) -> dict[str, Any]:
        rows: list[str] = []
        symbols: list[dict[str, Any]] = []
        scanned_files = 0
        for file_path in self._files(self.guard.resolve(path)):
            scanned_files += 1
            rel_path = file_path.relative_to(self.root).as_posix()
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for symbol in self.extractor.extract(rel_path, text):
                rows.append(symbol.name)
                symbols.append(
                    {
                        "path": rel_path,
                        "name": symbol.name,
                        "kind": symbol.kind,
                        "signature": symbol.signature,
                        "startLine": symbol.start_line,
                        "endLine": symbol.end_line,
                        "confidence": 0.7,
                    }
                )
                if len(symbols) >= limit:
                    return self._payload(path, symbols, scanned_files, limit, truncated=True)
        return self._payload(path, symbols, scanned_files, limit, truncated=False)

    def _files(self, start: Path):
        if start.is_file():
            if not self.ignore.ignored(start):
                yield start
            return
        for path in sorted(start.rglob("*")):
            if (
                path.is_file()
                and not self.ignore.ignored(path)
                and path.suffix.lower() in self._suffixes()
                and self._within_size_limit(path)
            ):
                yield path

    def _suffixes(self) -> set[str]:
        return {".go", ".java", ".js", ".jsx", ".kt", ".py", ".rs", ".ts", ".tsx"}

    def _within_size_limit(self, path: Path) -> bool:
        try:
            return path.stat().st_size <= self.max_file_bytes
        except OSError:
            return False

    def _payload(
        self,
        path: str | None,
        symbols: list[dict[str, Any]],
        scanned_files: int,
        limit: int,
        truncated: bool,
    ) -> dict[str, Any]:
        candidates: dict[str, dict[str, Any]] = {}
        for symbol in symbols:
            candidate = candidates.setdefault(
                symbol["path"],
                {
                    "path": symbol["path"],
                    "startLine": symbol["startLine"],
                    "endLine": symbol["endLine"],
                    "symbolCount": 0,
                    "confidence": 0.55,
                    "symbols": [],
                },
            )
            candidate["startLine"] = min(candidate["startLine"], symbol["startLine"])
            candidate["endLine"] = max(candidate["endLine"], symbol["endLine"])
            candidate["symbolCount"] += 1
            candidate["confidence"] = min(0.95, 0.55 + candidate["symbolCount"] * 0.05)
            candidate["symbols"].append(symbol["name"])
        return {
            "query": {"path": path},
            "symbols": symbols,
            "candidates": sorted(candidates.values(), key=lambda item: (-item["symbolCount"], item["path"])),
            "metrics": {
                "symbolCount": len(symbols),
                "candidateCount": len(candidates),
                "scannedFiles": scanned_files,
                "limit": limit,
                "truncated": truncated,
            },
        }

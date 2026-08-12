from __future__ import annotations

from collections import Counter
from pathlib import Path

from ..inspection import TreeService
from ..services import CodebaseScanner, CodeSymbolExtractor


class RepositoryInventory:
    def __init__(self, scanner: CodebaseScanner, tree_depth: int, tree_limit: int):
        self.scanner = scanner
        self.tree_depth = tree_depth
        self.tree_limit = tree_limit

    def render(self, root: Path) -> str:
        items = self.scanner.scan(root)
        paths = sorted({item.path for item in items})
        suffixes = Counter(Path(path).suffix or "<none>" for path in paths)
        top_dirs = Counter(path.split("/", 1)[0] for path in paths)
        return "\n\n".join(
            [
                "Repository tree:",
                TreeService(root).render(max_depth=self.tree_depth, limit=self.tree_limit),
                "Indexable file stats:",
                f"files: {len(paths)}",
                "extensions: " + ", ".join(f"{suffix}={count}" for suffix, count in suffixes.most_common(20)),
                "top_dirs: " + ", ".join(f"{directory}={count}" for directory, count in top_dirs.most_common(20)),
                "sample_paths:",
                "\n".join(paths[:200]),
                "symbol_samples:",
                self._symbol_samples(root, paths, limit=160) or "(none)",
            ]
        )

    def _symbol_samples(self, root: Path, paths: list[str], limit: int) -> str:
        extractor = CodeSymbolExtractor()
        rows: list[str] = []
        for rel_path in paths:
            path = root / rel_path
            if path.suffix.lower() not in {".go", ".java", ".js", ".jsx", ".kt", ".py", ".rs", ".ts", ".tsx"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for symbol in extractor.extract(rel_path, text):
                rows.append(f"{rel_path}:{symbol.start_line}: {symbol.kind} {symbol.name} - {symbol.signature}")
                if len(rows) >= limit:
                    return "\n".join(rows)
        return "\n".join(rows)

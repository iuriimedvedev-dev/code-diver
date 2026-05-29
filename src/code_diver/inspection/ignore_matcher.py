from __future__ import annotations

import fnmatch
from pathlib import Path


class IgnoreMatcher:
    def __init__(self, root: Path, extra_patterns: list[str] | None = None):
        self.root = root
        self.patterns = [*self._load_patterns(root), *(extra_patterns or [])]

    def ignored(self, path: Path) -> bool:
        rel_path = path.relative_to(self.root).as_posix()
        return any(self._matches(rel_path, pattern) for pattern in self.patterns)

    def _matches(self, rel_path: str, pattern: str) -> bool:
        if pattern.endswith("/"):
            directory = pattern.rstrip("/")
            return rel_path == directory or rel_path.startswith(directory + "/")
        if pattern.endswith("/**"):
            directory = pattern[:-3]
            if "/" not in directory and directory in rel_path.split("/"):
                return True
            return rel_path == directory or rel_path.startswith(directory + "/")
        return (
            fnmatch.fnmatch(rel_path, pattern)
            or fnmatch.fnmatch(f"./{rel_path}", pattern)
            or any(fnmatch.fnmatch(part, pattern) for part in rel_path.split("/"))
        )

    def _load_patterns(self, root: Path) -> list[str]:
        patterns = [".git/", ".code-diver/", ".venv/", "__pycache__/", ".pytest_cache/"]
        gitignore = root / ".gitignore"
        if gitignore.exists():
            for line in gitignore.read_text(encoding="utf-8", errors="replace").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or stripped.startswith("!"):
                    continue
                patterns.append(stripped.lstrip("/"))
        return patterns

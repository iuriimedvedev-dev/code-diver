from __future__ import annotations

from typing import Any


class CandidateScopedSearch:
    def __init__(self, max_files: int = 30):
        self.max_files = max(1, max_files)

    def paths(self, requested_path: str | None, candidate_bank: list[dict[str, Any]]) -> list[str]:
        if not self._should_scope(requested_path):
            return []
        paths: list[str] = []
        for candidate in candidate_bank:
            path = str(candidate.get("path") or candidate.get("file") or "").strip()
            if path and path not in paths:
                paths.append(path)
            if len(paths) >= self.max_files:
                break
        return paths

    def _should_scope(self, requested_path: str | None) -> bool:
        if requested_path is None:
            return True
        return requested_path.strip() in {"", ".", "./"}

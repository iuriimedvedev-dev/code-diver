from __future__ import annotations

import fnmatch
import os
from pathlib import Path


class IndexPlanSanitizer:
    def safe_include_additions(
        self,
        root: Path,
        additions: list[str],
        excludes: list[str],
        max_added_files: int,
    ) -> tuple[list[str], list[str]]:
        safe: list[str] = []
        rejected: list[str] = []
        for pattern in additions:
            if self._hidden_pattern(pattern):
                rejected.append(pattern)
                continue
            match_count = self._count_matching_files(root, pattern, excludes, max_added_files + 1)
            if match_count > max_added_files:
                rejected.append(pattern)
                continue
            safe.append(pattern)
        return safe, rejected

    def safe_exclude_additions(
        self,
        root: Path,
        additions: list[str],
        existing_excludes: list[str],
        max_excluded_files: int,
    ) -> tuple[list[str], list[str]]:
        safe: list[str] = []
        rejected: list[str] = []
        for pattern in additions:
            if self._hidden_pattern(pattern) or self._broad_exclude_pattern(pattern):
                rejected.append(pattern)
                continue
            match_count = self._count_matching_files(root, pattern, existing_excludes, max_excluded_files + 1)
            if match_count > max_excluded_files:
                rejected.append(pattern)
                continue
            safe.append(pattern)
        return safe, rejected

    def _hidden_pattern(self, pattern: str) -> bool:
        return pattern.startswith(".") or "/." in pattern

    def _broad_exclude_pattern(self, pattern: str) -> bool:
        normalized = pattern.strip()
        return (
            normalized in {"*", "**", "**/*", "./**/*"}
            or normalized.startswith("**/*.")
            or ("/" not in normalized and normalized.startswith("*."))
        )

    def _count_matching_files(self, root: Path, pattern: str, excludes: list[str], limit: int) -> int:
        count = 0
        resolved_root = root.resolve()
        for current_root, dir_names, file_names in os.walk(resolved_root):
            current_path = Path(current_root)
            dir_names[:] = [
                name
                for name in dir_names
                if not self._matches_excluded_directory((current_path / name).relative_to(resolved_root).as_posix(), excludes)
            ]
            for file_name in file_names:
                rel_path = (current_path / file_name).relative_to(resolved_root).as_posix()
                if self._matches_any(rel_path, excludes):
                    continue
                if self._matches_any(rel_path, [pattern]):
                    count += 1
                    if count >= limit:
                        return count
        return count

    def _matches_excluded_directory(self, rel_path: str, excludes: list[str]) -> bool:
        return any(self._matches_directory_pattern(rel_path, pattern) for pattern in excludes)

    def _matches_directory_pattern(self, rel_path: str, pattern: str) -> bool:
        normalized = pattern.rstrip("/")
        if normalized.endswith("/**"):
            base = normalized[:-3]
            if "/" not in base and base in rel_path.split("/"):
                return True
            return rel_path == base or rel_path.startswith(base + "/")
        return self._matches_any(rel_path, [pattern])

    def _matches_any(self, rel_path: str, patterns: list[str]) -> bool:
        return any(fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(f"./{rel_path}", pattern) for pattern in patterns)

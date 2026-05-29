from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .grep_service import GrepMatch, GrepService
from .path_guard import PathGuard


class RgService:
    def __init__(
        self,
        root: Path,
        exclude: list[str] | None = None,
        max_file_bytes: int = 1_000_000,
        timeout_seconds: float = 10.0,
    ):
        self.root = root.resolve()
        self.guard = PathGuard(self.root)
        self.exclude = exclude or []
        self.max_file_bytes = max_file_bytes
        self.timeout_seconds = timeout_seconds

    def search(self, pattern: str, path: str | None = None, limit: int = 100) -> str:
        return "\n".join(f"{match.path}:{match.line}: {match.text}" for match in self.search_matches(pattern, path, limit))

    def search_matches(self, pattern: str, path: str | None = None, limit: int = 100) -> list[GrepMatch]:
        if shutil.which("rg") is None:
            return GrepService(self.root, self.exclude, self.max_file_bytes).search(pattern, path, limit, regex=True)
        target = self.guard.resolve(path)
        command = [
            "rg",
            "--with-filename",
            "--line-number",
            "--color",
            "never",
            "--max-count",
            str(limit),
            "--max-filesize",
            str(self.max_file_bytes),
            *self._exclude_args(),
            pattern,
            str(target.relative_to(self.root) if target != self.root else "."),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=self.root,
                text=True,
                capture_output=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"rg timed out after {self.timeout_seconds}s") from exc
        if completed.returncode not in (0, 1):
            raise RuntimeError(completed.stderr.strip() or "rg failed")
        matches: list[GrepMatch] = []
        for line in completed.stdout.splitlines()[:limit]:
            parts = line.split(":", 2)
            if len(parts) != 3:
                continue
            path_text, line_number, text = parts
            matches.append(GrepMatch(path=path_text.removeprefix("./"), line=int(line_number), text=text))
        return matches

    def structured(
        self,
        pattern: str,
        path: str | None = None,
        limit: int = 100,
        include_text: bool = False,
    ) -> dict[str, Any]:
        matches = self.search_matches(pattern, path, limit)
        return {
            "query": {
                "pattern": pattern,
                "path": path,
                "regex": True,
                "includeText": include_text,
            },
            "candidates": self._candidates(matches),
            "matches": [self._match_json(match, include_text) for match in matches],
            "metrics": {
                "matchCount": len(matches),
                "candidateCount": len({match.path for match in matches}),
                "limit": limit,
                "truncated": len(matches) >= limit,
                "backend": "rg" if shutil.which("rg") is not None else "python",
            },
        }

    def _exclude_args(self) -> list[str]:
        args: list[str] = []
        for pattern in self.exclude:
            args.extend(["--glob", f"!{pattern}"])
        return args

    def _match_json(self, match: GrepMatch, include_text: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {"path": match.path, "line": match.line}
        if include_text:
            payload["text"] = match.text
        return payload

    def _candidates(self, matches: list[GrepMatch]) -> list[dict[str, Any]]:
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

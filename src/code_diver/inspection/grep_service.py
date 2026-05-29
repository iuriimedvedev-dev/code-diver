from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ignore_matcher import IgnoreMatcher
from .path_guard import PathGuard


@dataclass(slots=True)
class GrepMatch:
    path: str
    line: int
    text: str


class GrepService:
    def __init__(
        self,
        root: Path,
        exclude: list[str] | None = None,
        max_file_bytes: int = 1_000_000,
        max_files: int = 10_000,
        timeout_seconds: float = 10.0,
    ):
        self.root = root.resolve()
        self.guard = PathGuard(self.root)
        self.ignore = IgnoreMatcher(self.root, exclude)
        self.max_file_bytes = max_file_bytes
        self.max_files = max_files
        self.timeout_seconds = timeout_seconds

    def search(self, pattern: str, path: str | None = None, limit: int = 100, regex: bool = False) -> list[GrepMatch]:
        if not regex and shutil.which("rg") is not None:
            return self._rg_fixed_search(pattern, path, limit)
        compiled = re.compile(pattern) if regex else None
        matches: list[GrepMatch] = []
        for file_path in self._files(self.guard.resolve(path)):
            for line_number, line in enumerate(self._lines(file_path), start=1):
                if self._matches(line, pattern, compiled):
                    matches.append(
                        GrepMatch(
                            path=file_path.relative_to(self.root).as_posix(),
                            line=line_number,
                            text=line.rstrip("\n"),
                        )
                    )
                    if len(matches) >= limit:
                        return matches
        return matches

    def render(self, pattern: str, path: str | None = None, limit: int = 100, regex: bool = False) -> str:
        return "\n".join(
            f"{match.path}:{match.line}: {match.text}" for match in self.search(pattern, path, limit, regex)
        )

    def structured(
        self,
        pattern: str,
        path: str | None = None,
        limit: int = 100,
        regex: bool = False,
        include_text: bool = False,
    ) -> dict[str, Any]:
        matches = self.search(pattern, path, limit, regex)
        return {
            "query": {
                "pattern": pattern,
                "path": path,
                "regex": regex,
                "includeText": include_text,
            },
            "candidates": self._candidates(matches),
            "matches": [self._match_json(match, include_text) for match in matches],
            "metrics": {
                "matchCount": len(matches),
                "candidateCount": len({match.path for match in matches}),
                "limit": limit,
                "truncated": len(matches) >= limit,
                "backend": "rg" if not regex and shutil.which("rg") is not None else "python",
            },
        }

    def _files(self, start: Path):
        if start.is_file():
            if not self.ignore.ignored(start):
                yield start
            return
        file_count = 0
        for path in sorted(start.rglob("*")):
            if path.is_file() and not self.ignore.ignored(path) and self._readable(path):
                yield path
                file_count += 1
                if file_count >= self.max_files:
                    return

    def _lines(self, path: Path):
        try:
            yield from path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return

    def _matches(self, line: str, pattern: str, compiled: re.Pattern[str] | None) -> bool:
        if compiled is not None:
            return bool(compiled.search(line))
        return pattern in line

    def _rg_fixed_search(self, pattern: str, path: str | None, limit: int) -> list[GrepMatch]:
        target = self.guard.resolve(path)
        command = [
            "rg",
            "--fixed-strings",
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
            raise RuntimeError(f"grep timed out after {self.timeout_seconds}s") from exc
        if completed.returncode not in (0, 1):
            raise RuntimeError(completed.stderr.strip() or "grep failed")
        matches: list[GrepMatch] = []
        for line in completed.stdout.splitlines()[:limit]:
            parts = line.split(":", 2)
            if len(parts) != 3:
                continue
            path_text, line_number, text = parts
            matches.append(GrepMatch(path=path_text.removeprefix("./"), line=int(line_number), text=text))
        return matches

    def _exclude_args(self) -> list[str]:
        args: list[str] = []
        for pattern in self.ignore.patterns:
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

    def _readable(self, path: Path) -> bool:
        try:
            if path.stat().st_size > self.max_file_bytes:
                return False
            return b"\x00" not in path.read_bytes()[:2048]
        except OSError:
            return False

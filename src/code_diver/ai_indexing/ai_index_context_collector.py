from __future__ import annotations

from pathlib import Path

from ..config.ai_index_config import AiIndexConfig
from ..inspection import RgService, TreeService
from ..services import CodebaseScanner
from .ai_index_candidate import AiIndexCandidate
from .ai_index_context import AiIndexContext


class AiIndexContextCollector:
    def __init__(self, scanner: CodebaseScanner, config: AiIndexConfig):
        self.scanner = scanner
        self.config = config

    def collect(self, root: Path) -> AiIndexContext:
        tree = TreeService(root).render(max_depth=self.config.tree_depth, limit=self.config.tree_limit)
        discoveries = self._discover(root)
        candidates = self._candidates(root, discoveries)
        return AiIndexContext(tree=tree, discoveries=discoveries, candidates=candidates)

    def _discover(self, root: Path) -> list[str]:
        rg = RgService(root)
        lines: list[str] = []
        seen: set[str] = set()
        per_pattern_limit = max(1, self.config.discovery_limit // max(len(self.config.discovery_patterns), 1))
        for pattern in self.config.discovery_patterns:
            output = rg.search(pattern, limit=per_pattern_limit)
            for line in output.splitlines():
                if line and line not in seen:
                    seen.add(line)
                    lines.append(line)
                if len(lines) >= self.config.discovery_limit:
                    return lines
        return lines

    def _candidates(self, root: Path, discoveries: list[str]) -> list[AiIndexCandidate]:
        discovered_paths = self._paths_from_discoveries(discoveries)
        scanned_items = self.scanner.scan(root)
        selected: list[AiIndexCandidate] = []
        seen_paths: set[str] = set()
        for item in scanned_items:
            if discovered_paths and item.path not in discovered_paths:
                continue
            if item.path in seen_paths:
                continue
            seen_paths.add(item.path)
            selected.append(
                AiIndexCandidate(
                    path=item.path,
                    content=item.content,
                    start_line=item.start_line,
                    end_line=item.end_line,
                )
            )
            if len(selected) >= self.config.max_files:
                break
        if selected:
            return selected
        return [
            AiIndexCandidate(
                path=item.path,
                content=item.content,
                start_line=item.start_line,
                end_line=item.end_line,
            )
            for item in scanned_items[: self.config.max_files]
        ]

    def _paths_from_discoveries(self, discoveries: list[str]) -> set[str]:
        paths: set[str] = set()
        for line in discoveries:
            path = line.split(":", 1)[0].strip()
            if path:
                paths.add(path)
        return paths

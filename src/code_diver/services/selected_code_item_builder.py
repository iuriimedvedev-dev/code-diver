from __future__ import annotations

import hashlib
from pathlib import Path

from ..domain import CodeItem
from ..inspection.ignore_matcher import IgnoreMatcher
from ..inspection.path_guard import PathGuard
from .selected_index_item import SelectedIndexItem
from .selected_index_result import SelectedIndexResult


class SelectedCodeItemBuilder:
    def __init__(self, root: Path, max_lines: int):
        self.root = root.resolve()
        self.max_lines = max(max_lines, 1)
        self.path_guard = PathGuard(self.root)
        self.ignore_matcher = IgnoreMatcher(self.root)

    def build(self, selections: list[SelectedIndexItem]) -> SelectedIndexResult:
        items: list[CodeItem] = []
        skipped: list[str] = []
        for selection in selections:
            try:
                items.append(self._build_item(selection))
            except ValueError as exc:
                skipped.append(f"{selection.path}: {exc}")
        return SelectedIndexResult(items=self._dedupe(items), skipped=skipped)

    def _build_item(self, selection: SelectedIndexItem) -> CodeItem:
        path = self.path_guard.resolve(selection.path)
        if self.ignore_matcher.ignored(path):
            raise ValueError("path is ignored")
        if not path.is_file():
            raise ValueError("path is not a file")
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        if not lines:
            raise ValueError("file is empty")
        start_line = max(selection.start_line or 1, 1)
        requested_end = selection.end_line or min(start_line + self.max_lines - 1, len(lines))
        end_line = min(max(requested_end, start_line), len(lines), start_line + self.max_lines - 1)
        content = "\n".join(lines[start_line - 1 : end_line])
        if not content.strip():
            raise ValueError("selected range is empty")
        rel_path = path.relative_to(self.root).as_posix()
        title = selection.title or f"{rel_path}:{start_line}-{end_line}"
        digest = hashlib.sha1(f"{rel_path}:{start_line}:{end_line}:{title}".encode("utf-8")).hexdigest()[:12]
        metadata = {
            "source": "ai_selected",
            "selection_reason": selection.reason,
            "kind": selection.kind,
        }
        return CodeItem(
            id=f"{rel_path}#ai-{digest}",
            path=rel_path,
            title=title,
            content=content,
            start_line=start_line,
            end_line=end_line,
            metadata={key: value for key, value in metadata.items() if value is not None},
        )

    def _dedupe(self, items: list[CodeItem]) -> list[CodeItem]:
        seen: set[str] = set()
        deduped: list[CodeItem] = []
        for item in items:
            if item.id in seen:
                continue
            seen.add(item.id)
            deduped.append(item)
        return deduped

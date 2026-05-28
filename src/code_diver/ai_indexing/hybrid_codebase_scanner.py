from __future__ import annotations

from pathlib import Path

from ..domain import CodeItem


class HybridCodebaseScanner:
    def __init__(self, scanners: list[object]):
        self.scanners = scanners

    def scan(self, root: Path) -> list[CodeItem]:
        items: list[CodeItem] = []
        seen: set[str] = set()
        for scanner in self.scanners:
            for item in scanner.scan(root):
                if item.id in seen:
                    continue
                seen.add(item.id)
                items.append(item)
        return items

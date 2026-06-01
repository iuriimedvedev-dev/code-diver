from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from ..domain import CodeItem, CodeItemIndexKindResolver


class IndexCompositionAnalyzer:
    def __init__(self, kind_resolver: CodeItemIndexKindResolver | None = None):
        self.kind_resolver = kind_resolver or CodeItemIndexKindResolver()

    def analyze(self, items: list[CodeItem]) -> dict[str, Any]:
        items_by_kind: Counter[str] = Counter()
        paths_by_kind: dict[str, set[str]] = defaultdict(set)
        for item in items:
            kind = self.kind_resolver.resolve(item)
            items_by_kind[kind] += 1
            paths_by_kind[kind].add(item.path)
        return {
            "indexed_items": len(items),
            "unique_paths": len({item.path for item in items}),
            "items_by_kind": dict(sorted(items_by_kind.items())),
            "paths_by_kind": {kind: len(paths) for kind, paths in sorted(paths_by_kind.items())},
        }

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from ..graph import GraphEdge


class FileFanInIndex:
    """H-87: file-level in-degree -- how many *distinct* files point at each file.

    The file adjacency (`FileGraphAdjacencyIndex`) is deliberately symmetric (reverse edges at
    0.7 weight) so hop expansion works in both directions, which makes the edge direction
    unrecoverable from it. Fan-in therefore has to be collected from the raw directed edges
    while they stream past, once, next to the adjacency build.
    """

    def __init__(self, in_degree: dict[str, int]):
        self.in_degree = in_degree

    def degree(self, path: str) -> int:
        return self.in_degree.get(path, 0)

    def __len__(self) -> int:
        return len(self.in_degree)

    @classmethod
    def collector(cls, item_paths: dict[str, str]) -> FileFanInCollector:
        return FileFanInCollector(item_paths)

    def to_json(self) -> dict[str, Any]:
        return {"in_degree": dict(self.in_degree)}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> FileFanInIndex:
        return cls({str(path): int(degree) for path, degree in dict(data.get("in_degree") or {}).items()})


class FileFanInCollector:
    """Accumulates distinct source files per target file from a single pass over the edges."""

    def __init__(self, item_paths: dict[str, str]):
        self._item_paths = item_paths
        self._sources_by_target: dict[str, set[str]] = {}

    def observing(self, edges: Iterable[GraphEdge]) -> Iterator[GraphEdge]:
        for edge in edges:
            self.observe(edge)
            yield edge

    def observe(self, edge: GraphEdge) -> None:
        source_path = self._item_paths.get(edge.source)
        target_path = self._item_paths.get(edge.target)
        if source_path is None or target_path is None or source_path == target_path:
            return
        self._sources_by_target.setdefault(target_path, set()).add(source_path)

    def build(self) -> FileFanInIndex:
        return FileFanInIndex({path: len(sources) for path, sources in self._sources_by_target.items()})

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from ..domain import CodeItem, CodeItemIndexKind, CodeItemIndexKindResolver
from ..graph import CodeGraph
from .file_graph_adjacency_index import FileGraphAdjacencyIndex
from .graph_expansion_profile import GraphExpansionProfile


class FileGraphCandidateExpander:
    def __init__(
        self,
        graph: CodeGraph | None = None,
        *,
        items: Iterable[CodeItem] | None = None,
        adjacency: FileGraphAdjacencyIndex | None = None,
    ):
        self.kind_resolver = CodeItemIndexKindResolver()
        graph_items = graph.items.values() if graph is not None else items or []
        self.items_by_id = {item.id: item for item in graph_items}
        self.items_by_path = self._items_by_path(self.items_by_id.values())
        self.adjacency = adjacency or self._adjacency(graph or CodeGraph(items={}, edges=[]))

    def expand(
        self, seed_scores: dict[str, float], profile: GraphExpansionProfile
    ) -> dict[str, float]:
        if profile.depth <= 0 or not seed_scores:
            return {}
        seed_file_scores = self._seed_file_scores(seed_scores)
        if not seed_file_scores:
            return {}
        file_scores = self._expand_files(seed_file_scores, profile)
        return self._representative_item_scores(file_scores)

    def _seed_file_scores(self, seed_scores: dict[str, float]) -> dict[str, float]:
        scores: dict[str, float] = {}
        for item_id, score in seed_scores.items():
            item = self.items_by_id.get(item_id)
            if item is None:
                continue
            scores[item.path] = max(scores.get(item.path, 0.0), score)
        return scores

    def _expand_files(
        self,
        seed_file_scores: dict[str, float],
        profile: GraphExpansionProfile,
    ) -> dict[str, float]:
        return self.adjacency.expand(seed_file_scores, profile)

    def _representative_item_scores(
        self, file_scores: dict[str, float]
    ) -> dict[str, float]:
        scores: dict[str, float] = {}
        for path, score in file_scores.items():
            representatives = self._representatives(path)
            for item in representatives:
                scores[item.id] = max(scores.get(item.id, 0.0), score)
        return scores

    def _representatives(self, path: str) -> list[CodeItem]:
        items = self.items_by_path.get(path, [])
        file_items = [
            item
            for item in items
            if self.kind_resolver.resolve(item)
            in {
                CodeItemIndexKind.FILE_SUMMARY,
                CodeItemIndexKind.FILE_MANIFEST,
                CodeItemIndexKind.FILE_API_MANIFEST,
            }
        ]
        return file_items or items

    def _items_by_path(self, items: Iterable[CodeItem]) -> dict[str, list[CodeItem]]:
        by_path: dict[str, list[CodeItem]] = defaultdict(list)
        for item in items:
            by_path[item.path].append(item)
        return dict(by_path)

    def _adjacency(self, graph: CodeGraph) -> FileGraphAdjacencyIndex:
        return FileGraphAdjacencyIndex.from_graph(graph)

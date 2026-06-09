from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from ..domain import CodeItem, CodeItemIndexKind, CodeItemIndexKindResolver
from ..graph import GraphEdge
from .file_graph_adjacency_index import FileGraphAdjacencyIndex


class FileGraphCatalog:
    def __init__(
        self,
        *,
        items_by_id: dict[str, CodeItem],
        adjacency: FileGraphAdjacencyIndex,
    ):
        self.items_by_id = items_by_id
        self.adjacency = adjacency

    @classmethod
    def build(
        cls,
        items: Iterable[CodeItem],
        edges: Iterable[GraphEdge],
    ) -> "FileGraphCatalog":
        resolver = CodeItemIndexKindResolver()
        item_paths: dict[str, str] = {}
        representatives_by_path: dict[str, dict[str, CodeItem]] = defaultdict(dict)
        for item in items:
            item_paths[item.id] = item.path
            kind = resolver.resolve(item)
            if kind in {
                CodeItemIndexKind.FILE_SUMMARY,
                CodeItemIndexKind.FILE_MANIFEST,
                CodeItemIndexKind.FILE_API_MANIFEST,
                CodeItemIndexKind.DOC_SUMMARY,
                CodeItemIndexKind.DOC_MANIFEST,
                CodeItemIndexKind.DOC_CHUNK,
            }:
                representatives_by_path[item.path][kind] = item
        representatives: dict[str, CodeItem] = {}
        for by_kind in representatives_by_path.values():
            for kind in (
                CodeItemIndexKind.FILE_MANIFEST,
                CodeItemIndexKind.FILE_API_MANIFEST,
                CodeItemIndexKind.FILE_SUMMARY,
                CodeItemIndexKind.DOC_SUMMARY,
                CodeItemIndexKind.DOC_MANIFEST,
                CodeItemIndexKind.DOC_CHUNK,
            ):
                item = by_kind.get(kind)
                if item is not None:
                    representatives[item.id] = item
        return cls(
            items_by_id=representatives,
            adjacency=FileGraphAdjacencyIndex.from_item_paths_and_edges(item_paths, edges),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "items": {
                item_id: item.to_json()
                for item_id, item in self.items_by_id.items()
            },
            "adjacency": self.adjacency.to_json(),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "FileGraphCatalog":
        return cls(
            items_by_id={
                item_id: CodeItem.from_json(item)
                for item_id, item in dict(data.get("items") or {}).items()
            },
            adjacency=FileGraphAdjacencyIndex.from_json(dict(data.get("adjacency") or {})),
        )

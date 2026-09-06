from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from ..domain import CodeItem, CodeItemIndexKind, CodeItemIndexKindResolver
from ..graph import GraphEdge
from .file_fan_in_index import FileFanInIndex
from .file_graph_adjacency_index import FileGraphAdjacencyIndex


class FileGraphCatalog:
    def __init__(
        self,
        *,
        items_by_id: dict[str, CodeItem],
        adjacency: FileGraphAdjacencyIndex,
        fan_in: FileFanInIndex | None = None,
    ):
        self.items_by_id = items_by_id
        self.adjacency = adjacency
        # H-87: directed in-degree per file. None for catalogs persisted before the index
        # existed -- consumers must treat that as "fan-in unavailable", not as zero fan-in.
        self.fan_in = fan_in

    @classmethod
    def build(
        cls,
        items: Iterable[CodeItem],
        edges: Iterable[GraphEdge],
    ) -> FileGraphCatalog:
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
                CodeItemIndexKind.FILE_PURPOSE,
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
                CodeItemIndexKind.FILE_PURPOSE,
                CodeItemIndexKind.DOC_SUMMARY,
                CodeItemIndexKind.DOC_MANIFEST,
                CodeItemIndexKind.DOC_CHUNK,
            ):
                item = by_kind.get(kind)
                if item is not None:
                    representatives[item.id] = item
        fan_in_collector = FileFanInIndex.collector(item_paths)
        adjacency = FileGraphAdjacencyIndex.from_item_paths_and_edges(item_paths, fan_in_collector.observing(edges))
        return cls(
            items_by_id=representatives,
            adjacency=adjacency,
            fan_in=fan_in_collector.build(),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "items": {
                item_id: item.to_json()
                for item_id, item in self.items_by_id.items()
            },
            "adjacency": self.adjacency.to_json(),
            **({"fan_in": self.fan_in.to_json()} if self.fan_in is not None else {}),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> FileGraphCatalog:
        return cls(
            items_by_id={
                item_id: CodeItem.from_json(item)
                for item_id, item in dict(data.get("items") or {}).items()
            },
            adjacency=FileGraphAdjacencyIndex.from_json(dict(data.get("adjacency") or {})),
            fan_in=FileFanInIndex.from_json(dict(data["fan_in"])) if data.get("fan_in") is not None else None,
        )

from __future__ import annotations

from ..domain import CodeItem
from ..settings import EdgeKind
from .graph_edge import GraphEdge


class GraphContainmentBuilder:
    def build(self, by_path: dict[str, list[CodeItem]]) -> list[GraphEdge]:
        edges: list[GraphEdge] = []
        for items in by_path.values():
            symbol_items = [item for item in items if self._symbol(item)]
            edges.extend(self._chunk_contains_symbol_edges(items, symbol_items))
            edges.extend(self._symbol_contains_symbol_edges(symbol_items))
        return edges

    def _chunk_contains_symbol_edges(self, items: list[CodeItem], symbol_items: list[CodeItem]) -> list[GraphEdge]:
        edges: list[GraphEdge] = []
        containers = [item for item in items if not self._symbol(item)]
        for container in containers:
            if container.start_line is None or container.end_line is None:
                continue
            for symbol in symbol_items:
                if symbol.start_line is None or symbol.end_line is None:
                    continue
                if container.start_line <= symbol.start_line and symbol.end_line <= container.end_line:
                    edges.append(
                        GraphEdge(
                            source=container.id,
                            target=symbol.id,
                            kind=EdgeKind.CONTAINS.value,
                            weight=0.75,
                        )
                    )
        return edges

    def _symbol_contains_symbol_edges(self, symbol_items: list[CodeItem]) -> list[GraphEdge]:
        edges: list[GraphEdge] = []
        by_symbol = {self._symbol(item): item for item in symbol_items}
        for symbol, item in by_symbol.items():
            if "." not in symbol:
                continue
            parent_symbol = symbol.rsplit(".", 1)[0]
            parent = by_symbol.get(parent_symbol)
            if parent is None:
                continue
            edges.append(GraphEdge(source=parent.id, target=item.id, kind=EdgeKind.CONTAINS.value, weight=0.85))
        return edges

    def _symbol(self, item: CodeItem) -> str:
        if not isinstance(item.metadata, dict):
            return ""
        return str(item.metadata.get("symbol") or "")

from __future__ import annotations

from dataclasses import replace

from ..domain import CodeItem, CodeItemMetadata


class BreadcrumbCodeItemEnricher:
    def enrich(self, items: list[CodeItem]) -> list[CodeItem]:
        return [self.enrich_item(item) for item in items]

    def enrich_item(self, item: CodeItem) -> CodeItem:
        breadcrumb = self._breadcrumb(item)
        metadata = {**item.metadata, "breadcrumb": breadcrumb}
        return replace(item, content=f"{breadcrumb}\n{item.content}", metadata=metadata)

    def _breadcrumb(self, item: CodeItem) -> str:
        parts = [f"[file: {item.path}]"]
        symbol = str(item.metadata.get(CodeItemMetadata.SYMBOL) or "").strip()
        if symbol:
            owner, name = self._split_symbol(symbol)
            if owner:
                parts.append(f"[class: {owner}]")
            parts.append(f"[function: {name}]")
        elif item.title and item.title != item.path:
            parts.append(f"[item: {item.title}]")
        return " -> ".join(parts)

    def _split_symbol(self, symbol: str) -> tuple[str | None, str]:
        if "." not in symbol:
            return None, symbol
        owner, name = symbol.rsplit(".", 1)
        return owner or None, name

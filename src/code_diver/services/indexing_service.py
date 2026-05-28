from __future__ import annotations

from pathlib import Path

from ..domain import CodeItem
from ..plugins import PluginManager
from ..providers import EmbeddingProvider
from ..store import VectorStore
from .code_item_scanner import CodeItemScanner


class IndexingService:
    def __init__(
        self,
        scanner: CodeItemScanner,
        plugin_manager: PluginManager,
        vector_store: VectorStore,
    ):
        self.scanner = scanner
        self.plugin_manager = plugin_manager
        self.vector_store = vector_store

    def build(
        self,
        root: Path,
        provider: EmbeddingProvider,
        plugin_config: dict | None = None,
    ) -> list[CodeItem]:
        scanned_items = self.scanner.scan(root)
        plugin_items = self.plugin_manager.collect_items(root, plugin_config or {})
        items = self.plugin_manager.transform_items(self._dedupe_items([*scanned_items, *plugin_items]))
        texts = [item.to_embedding_text() for item in items]
        vectors = provider.embed_documents(texts) if texts else []
        self.vector_store.save(
            root=root,
            provider=provider.name,
            model=provider.model,
            dimensions=provider.dimensions,
            items=items,
            vectors=vectors,
        )
        return items

    def _dedupe_items(self, items: list[CodeItem]) -> list[CodeItem]:
        seen: set[str] = set()
        deduped: list[CodeItem] = []
        for item in items:
            if item.id in seen:
                continue
            seen.add(item.id)
            deduped.append(item)
        return deduped

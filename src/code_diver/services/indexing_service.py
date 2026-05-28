from __future__ import annotations

from pathlib import Path

from ..domain import CodeItem
from ..plugins import PluginManager
from ..providers import EmbeddingProvider
from ..store import IndexStore
from .codebase_scanner import CodebaseScanner


class IndexingService:
    def __init__(
        self,
        scanner: CodebaseScanner,
        plugin_manager: PluginManager,
        index_store: IndexStore,
    ):
        self.scanner = scanner
        self.plugin_manager = plugin_manager
        self.index_store = index_store

    def build(
        self,
        root: Path,
        artifact: Path,
        provider: EmbeddingProvider,
        plugin_config: dict | None = None,
    ) -> list[CodeItem]:
        scanned_items = self.scanner.scan(root)
        plugin_items = self.plugin_manager.collect_items(root, plugin_config or {})
        items = self.plugin_manager.transform_items(self._dedupe_items([*scanned_items, *plugin_items]))
        texts = [item.to_embedding_text() for item in items]
        vectors = provider.embed_documents(texts) if texts else []
        self.index_store.save(
            artifact,
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

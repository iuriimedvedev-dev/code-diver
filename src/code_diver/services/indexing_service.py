from __future__ import annotations

import sys
from pathlib import Path

from ..domain import CodeItem
from ..plugins import PluginManager
from ..providers import EmbeddingProvider
from ..store import VectorStore
from ..tracing import TraceLogger
from .code_item_scanner import CodeItemScanner
from .embedding_text_preparer import EmbeddingTextPreparer
from .index_composition_analyzer import IndexCompositionAnalyzer
from .indexing_options import IndexingOptions
from .parallel_embedding_service import ParallelEmbeddingService


class IndexingService:
    def __init__(
        self,
        scanner: CodeItemScanner,
        plugin_manager: PluginManager,
        vector_store: VectorStore,
        options: IndexingOptions | None = None,
        trace_logger: TraceLogger | None = None,
    ):
        self.scanner = scanner
        self.plugin_manager = plugin_manager
        self.vector_store = vector_store
        self.options = options or IndexingOptions()
        self.trace_logger = trace_logger or TraceLogger.disabled()

    def build(
        self,
        root: Path,
        provider: EmbeddingProvider,
        plugin_config: dict | None = None,
    ) -> list[CodeItem]:
        scanned_items = self.scanner.scan(root)
        plugin_items = self.plugin_manager.collect_items(root, plugin_config or {})
        items = self.plugin_manager.transform_items(self._dedupe_items([*scanned_items, *plugin_items]))
        composition = IndexCompositionAnalyzer().analyze(items)
        self.trace_logger.write(
            "index_items_prepared",
            {
                "root": root,
                "scanner_items": len(scanned_items),
                "plugin_items": len(plugin_items),
                **composition,
                "embedding_batch_size": self.options.embedding_batch_size,
                "embedding_workers": self.options.embedding_workers,
                "embedding_max_input_chars": self.options.embedding_max_input_chars,
            },
        )
        preparer = EmbeddingTextPreparer(self.options.embedding_max_input_chars)
        texts = [preparer.prepare(item) for item in items]
        vectors = ParallelEmbeddingService(
            provider,
            batch_size=self.options.embedding_batch_size,
            workers=self.options.embedding_workers,
            on_batch_complete=self._progress_callback(len(texts)),
        ).embed_documents(texts)
        dimensions = provider.dimensions or (len(vectors[0]) if vectors else 0)
        if not provider.dimensions and dimensions:
            provider.dimensions = dimensions
        self.vector_store.save(
            root=root,
            provider=provider.name,
            model=provider.model,
            dimensions=dimensions,
            items=items,
            vectors=vectors,
        )
        self.trace_logger.write(
            "index_vectors_saved",
            {
                "root": root,
                "provider": provider.name,
                "model": provider.model,
                "dimensions": dimensions,
                "vectors": len(vectors),
            },
        )
        return items

    def _progress_callback(self, total_items: int):
        if not self.options.progress:
            return None
        last_reported = -1

        def callback(completed_batches: int, total_batches: int) -> None:
            nonlocal last_reported
            if total_batches <= 0:
                return
            percent = int((completed_batches / total_batches) * 100)
            should_report = completed_batches == total_batches or percent >= last_reported + 5
            if not should_report:
                return
            last_reported = percent
            print(
                f"embedding batches: {completed_batches}/{total_batches} "
                f"({percent}%, items={total_items})",
                file=sys.stderr,
            )

        return callback

    def _dedupe_items(self, items: list[CodeItem]) -> list[CodeItem]:
        seen: set[str] = set()
        deduped: list[CodeItem] = []
        for item in items:
            if item.id in seen:
                continue
            seen.add(item.id)
            deduped.append(item)
        return deduped

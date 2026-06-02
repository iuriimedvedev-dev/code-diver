from __future__ import annotations

import sys
from collections.abc import Iterable
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
        dimensions = self._embed_and_save(root, provider, items, preparer)
        self.trace_logger.write(
            "index_vectors_saved",
            {
                "root": root,
                "provider": provider.name,
                "model": provider.model,
                "dimensions": dimensions,
                "vectors": len(items),
            },
        )
        return items

    def _embed_and_save(
        self,
        root: Path,
        provider: EmbeddingProvider,
        items: list[CodeItem],
        preparer: EmbeddingTextPreparer,
    ) -> int:
        replace_batches = getattr(self.vector_store, "replace_batches", None)
        if callable(replace_batches):
            return self._embed_and_replace_batches(root, provider, items, preparer, replace_batches)
        return self._embed_and_save_once(root, provider, items, preparer)

    def _embed_and_save_once(
        self,
        root: Path,
        provider: EmbeddingProvider,
        items: list[CodeItem],
        preparer: EmbeddingTextPreparer,
    ) -> int:
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
        return dimensions

    def _embed_and_replace_batches(
        self,
        root: Path,
        provider: EmbeddingProvider,
        items: list[CodeItem],
        preparer: EmbeddingTextPreparer,
        replace_batches,
    ) -> int:
        block_size = max(self.options.embedding_batch_size * self.options.embedding_workers * 8, 1)
        total_batches = max((len(items) + self.options.embedding_batch_size - 1) // self.options.embedding_batch_size, 1)
        progress = self._streaming_progress_callback(len(items), total_batches)
        dimensions = provider.dimensions or 0

        def vector_batches() -> Iterable[tuple[list[CodeItem], list[list[float]]]]:
            nonlocal dimensions
            for item_batch in self._item_batches(items, block_size):
                texts = [preparer.prepare(item) for item in item_batch]
                vectors = ParallelEmbeddingService(
                    provider,
                    batch_size=self.options.embedding_batch_size,
                    workers=self.options.embedding_workers,
                    on_batch_complete=progress,
                ).embed_documents(texts)
                if not dimensions and vectors:
                    dimensions = len(vectors[0])
                    provider.dimensions = dimensions
                yield item_batch, vectors

        replace_batches(
            root=root,
            provider=provider.name,
            model=provider.model,
            dimensions=lambda: dimensions,
            batches=vector_batches(),
        )
        return dimensions

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

    def _streaming_progress_callback(self, total_items: int, total_batches: int):
        if not self.options.progress:
            return None
        completed = 0
        last_reported = -1

        def callback(_: int, __: int) -> None:
            nonlocal completed, last_reported
            completed += 1
            percent = int((completed / total_batches) * 100)
            should_report = completed == total_batches or percent >= last_reported + 5
            if not should_report:
                return
            last_reported = percent
            print(
                f"embedding batches: {completed}/{total_batches} "
                f"({percent}%, items={total_items})",
                file=sys.stderr,
            )

        return callback

    def _item_batches(self, items: list[CodeItem], size: int):
        for offset in range(0, len(items), size):
            yield items[offset : offset + size]

    def _dedupe_items(self, items: list[CodeItem]) -> list[CodeItem]:
        seen: set[str] = set()
        deduped: list[CodeItem] = []
        for item in items:
            if item.id in seen:
                continue
            seen.add(item.id)
            deduped.append(item)
        return deduped

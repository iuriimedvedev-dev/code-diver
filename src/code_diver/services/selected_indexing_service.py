from __future__ import annotations

from pathlib import Path

from ..domain import CodeItem
from ..providers import EmbeddingProvider
from ..store import VectorStore
from ..tracing import TraceLogger
from .embedding_text_preparer import EmbeddingTextPreparer
from .indexing_options import IndexingOptions
from .parallel_embedding_service import ParallelEmbeddingService


class SelectedIndexingService:
    def __init__(
        self,
        vector_store: VectorStore,
        options: IndexingOptions | None = None,
        trace_logger: TraceLogger | None = None,
    ):
        self.vector_store = vector_store
        self.options = options or IndexingOptions()
        self.trace_logger = trace_logger or TraceLogger.disabled()

    def build(self, root: Path, provider: EmbeddingProvider, items: list[CodeItem]) -> list[CodeItem]:
        self.trace_logger.write(
            "selected_index_items_prepared",
            {
                "root": root,
                "indexed_items": len(items),
                "unique_paths": len({item.path for item in items}),
                "embedding_batch_size": self.options.embedding_batch_size,
                "embedding_workers": self.options.embedding_workers,
            },
        )
        preparer = EmbeddingTextPreparer(self.options.embedding_max_input_chars)
        texts = [preparer.prepare(item) for item in items]
        vectors = ParallelEmbeddingService(
            provider,
            batch_size=self.options.embedding_batch_size,
            workers=self.options.embedding_workers,
        ).embed_documents(texts)
        dimensions = provider.dimensions or (len(vectors[0]) if vectors else 0)
        if not provider.dimensions and dimensions:
            provider.dimensions = dimensions
        persist = getattr(self.vector_store, "append", self.vector_store.save)
        persist(
            root=root,
            provider=provider.name,
            model=provider.model,
            dimensions=dimensions,
            items=items,
            vectors=vectors,
        )
        self.trace_logger.write(
            "selected_index_vectors_saved",
            {
                "root": root,
                "provider": provider.name,
                "model": provider.model,
                "dimensions": dimensions,
                "vectors": len(vectors),
            },
        )
        return items

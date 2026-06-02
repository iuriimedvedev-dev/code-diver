from __future__ import annotations

from pathlib import Path
from time import perf_counter

from ..providers import EmbeddingProvider
from ..store import InMemoryVectorStore
from .breadcrumb_code_item_enricher import BreadcrumbCodeItemEnricher
from .candidate_file_scanner import CandidateFileScanner
from .embedding_text_preparer import EmbeddingTextPreparer
from .ephemeral_deep_index_result import EphemeralDeepIndexResult
from .ephemeral_deep_search_result import EphemeralDeepSearchResult
from .indexing_options import IndexingOptions
from .parallel_embedding_service import ParallelEmbeddingService


class EphemeralDeepIndexService:
    def __init__(
        self,
        scanner: CandidateFileScanner,
        options: IndexingOptions | None = None,
        enricher: BreadcrumbCodeItemEnricher | None = None,
    ):
        self.scanner = scanner
        self.options = options or IndexingOptions(progress=False)
        self.enricher = enricher or BreadcrumbCodeItemEnricher()

    def build(self, root: Path, files: list[str], provider: EmbeddingProvider) -> EphemeralDeepIndexResult:
        started = perf_counter()
        items = self.enricher.enrich(self.scanner.scan_files(root, files))
        texts = [EmbeddingTextPreparer(self.options.embedding_max_input_chars).prepare(item) for item in items]
        vectors = ParallelEmbeddingService(
            provider,
            batch_size=self.options.embedding_batch_size,
            workers=self.options.embedding_workers,
        ).embed_documents(texts)
        dimensions = provider.dimensions or (len(vectors[0]) if vectors else 0)
        if not provider.dimensions and dimensions:
            provider.dimensions = dimensions
        vector_store = InMemoryVectorStore()
        vector_store.save(
            root=root,
            provider=provider.name,
            model=provider.model,
            dimensions=dimensions,
            items=items,
            vectors=vectors,
        )
        return EphemeralDeepIndexResult(
            vector_store=vector_store,
            items=items,
            build_ms=(perf_counter() - started) * 1000,
            temporary_vectors=len(items),
            cache_hits=0,
            cache_misses=len(items),
        )

    def search(
        self,
        index: EphemeralDeepIndexResult,
        provider: EmbeddingProvider,
        query: str,
        limit: int,
    ) -> EphemeralDeepSearchResult:
        started = perf_counter()
        query_vector = provider.embed_query(query)
        results = index.vector_store.search(query_vector, limit)
        return EphemeralDeepSearchResult(results=results, query_ms=(perf_counter() - started) * 1000)

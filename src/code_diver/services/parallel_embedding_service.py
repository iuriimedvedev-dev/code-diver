from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..providers import EmbeddingProvider


class ParallelEmbeddingService:
    def __init__(
        self,
        provider: EmbeddingProvider,
        batch_size: int,
        workers: int,
        on_batch_complete: Callable[[int, int], None] | None = None,
    ):
        self.provider = provider
        self.batch_size = max(batch_size, 1)
        self.workers = max(workers, 1)
        self.on_batch_complete = on_batch_complete

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        batches = list(self._batches(texts))
        if self.workers == 1:
            vectors: list[list[float]] = []
            for completed, (_, batch) in enumerate(batches, start=1):
                batch_vectors = self.provider.embed_documents(batch)
                if len(batch_vectors) != len(batch):
                    raise RuntimeError(
                        f"Embedding provider returned {len(batch_vectors)} vectors for {len(batch)} inputs."
                    )
                vectors.extend(batch_vectors)
                self._notify(completed, len(batches))
            return vectors

        vectors: list[list[float] | None] = [None] * len(texts)
        completed = 0
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(self.provider.embed_documents, batch): (offset, len(batch))
                for offset, batch in batches
            }
            for future in as_completed(futures):
                offset, expected = futures[future]
                batch_vectors = future.result()
                if len(batch_vectors) != expected:
                    raise RuntimeError(
                        f"Embedding provider returned {len(batch_vectors)} vectors for {expected} inputs."
                    )
                vectors[offset : offset + expected] = batch_vectors
                completed += 1
                self._notify(completed, len(batches))
        missing = [index for index, vector in enumerate(vectors) if vector is None]
        if missing:
            raise RuntimeError(f"Embedding provider did not return vectors for {len(missing)} inputs.")
        return [vector for vector in vectors if vector is not None]

    def _batches(self, texts: list[str]) -> list[tuple[int, list[str]]]:
        return [(offset, texts[offset : offset + self.batch_size]) for offset in range(0, len(texts), self.batch_size)]

    def _notify(self, completed: int, total: int) -> None:
        if self.on_batch_complete:
            self.on_batch_complete(completed, total)

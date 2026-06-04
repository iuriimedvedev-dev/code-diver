from __future__ import annotations

import threading
import time

import pytest

from code_diver.providers import EmbeddingProvider
from code_diver.services.embedding_text_preparer import EmbeddingTextPreparer
from code_diver.services.parallel_embedding_service import ParallelEmbeddingService


pytestmark = pytest.mark.unit


class RecordingEmbeddingProvider(EmbeddingProvider):
    def __init__(self) -> None:
        self.name = "recording"
        self.model = "recording"
        self.dimensions = 1
        self.thread_ids: set[int] = set()
        self.calls: list[list[str]] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.thread_ids.add(threading.get_ident())
        self.calls.append(list(texts))
        time.sleep(0.02)
        return [[float(text)] for text in texts]

    def embed_query(self, query: str) -> list[float]:
        return [float(query)]


def test_parallel_embedding_service_preserves_vector_order() -> None:
    provider = RecordingEmbeddingProvider()

    vectors = ParallelEmbeddingService(provider, batch_size=2, workers=4).embed_documents(
        ["0", "1", "2", "3", "4", "5", "6", "7"]
    )

    assert vectors == [[0.0], [1.0], [2.0], [3.0], [4.0], [5.0], [6.0], [7.0]]
    assert len(provider.thread_ids) > 1


def test_single_worker_embedding_service_still_batches_and_reports_progress() -> None:
    provider = RecordingEmbeddingProvider()
    progress: list[tuple[int, int]] = []

    vectors = ParallelEmbeddingService(
        provider,
        batch_size=2,
        workers=1,
        on_batch_complete=lambda completed, total: progress.append((completed, total)),
    ).embed_documents(["0", "1", "2", "3", "4"])

    assert vectors == [[0.0], [1.0], [2.0], [3.0], [4.0]]
    assert provider.calls == [["0", "1"], ["2", "3"], ["4"]]
    assert progress == [(1, 3), (2, 3), (3, 3)]


def test_embedding_text_preparer_limits_input_length() -> None:
    class Item:
        def to_embedding_text(self) -> str:
            return "abcdef"

    assert EmbeddingTextPreparer(max_input_chars=3).prepare(Item()) == "abc"

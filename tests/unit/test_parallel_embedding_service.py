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

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.thread_ids.add(threading.get_ident())
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


def test_embedding_text_preparer_limits_input_length() -> None:
    class Item:
        def to_embedding_text(self) -> str:
            return "abcdef"

    assert EmbeddingTextPreparer(max_input_chars=3).prepare(Item()) == "abc"

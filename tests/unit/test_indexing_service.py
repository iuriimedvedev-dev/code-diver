from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.domain import CodeItem
from code_diver.services.indexing_service import IndexingService


pytestmark = pytest.mark.unit


class SingleItemScanner:
    def scan(self, root: Path) -> list[CodeItem]:
        return [CodeItem("app.py#1", "app.py", "app", "def app(): pass")]


class MixedItemScanner:
    def scan(self, root: Path) -> list[CodeItem]:
        return [
            CodeItem("app.py#1", "app.py", "line chunk", "def app(): pass", metadata={"source": "scanner"}),
            CodeItem("app.py#symbol", "app.py", "symbol", "app", metadata={"index_kind": "symbol"}),
            CodeItem("README.md#summary", "README.md", "summary", "docs", metadata={"index_kind": "file_summary"}),
        ]


class NoPlugins:
    def collect_items(self, root: Path, config: dict) -> list[CodeItem]:
        return []

    def transform_items(self, items: list[CodeItem]) -> list[CodeItem]:
        return items


class UnknownDimensionProvider:
    name = "openai_compatible"
    model = "local-embed"
    dimensions = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3]]

    def embed_query(self, query: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class RecordingStore:
    def __init__(self):
        self.saved_dimensions: int | None = None

    def save(self, **kwargs) -> None:
        self.saved_dimensions = kwargs["dimensions"]


class RecordingTrace:
    def __init__(self):
        self.records: list[tuple[str, dict]] = []

    def write(self, event: str, payload: dict) -> None:
        self.records.append((event, payload))


def test_indexing_service_infers_dimensions_from_vectors(tmp_path: Path) -> None:
    store = RecordingStore()
    provider = UnknownDimensionProvider()

    IndexingService(SingleItemScanner(), NoPlugins(), store).build(tmp_path, provider)

    assert store.saved_dimensions == 3
    assert provider.dimensions == 3


def test_indexing_service_traces_index_composition(tmp_path: Path) -> None:
    trace = RecordingTrace()

    IndexingService(MixedItemScanner(), NoPlugins(), RecordingStore(), trace_logger=trace).build(
        tmp_path, UnknownDimensionProvider()
    )

    prepared = trace.records[0][1]
    assert prepared["indexed_items"] == 3
    assert prepared["unique_paths"] == 2
    assert prepared["items_by_kind"] == {"chunk": 1, "file_summary": 1, "symbol": 1}
    assert prepared["paths_by_kind"] == {"chunk": 1, "file_summary": 1, "symbol": 1}

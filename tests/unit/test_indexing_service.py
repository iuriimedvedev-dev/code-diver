from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.domain import CodeItem
from code_diver.services.indexing_service import IndexingService


pytestmark = pytest.mark.unit


class SingleItemScanner:
    def scan(self, root: Path) -> list[CodeItem]:
        return [CodeItem("app.py#1", "app.py", "app", "def app(): pass")]


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


def test_indexing_service_infers_dimensions_from_vectors(tmp_path: Path) -> None:
    store = RecordingStore()
    provider = UnknownDimensionProvider()

    IndexingService(SingleItemScanner(), NoPlugins(), store).build(tmp_path, provider)

    assert store.saved_dimensions == 3
    assert provider.dimensions == 3

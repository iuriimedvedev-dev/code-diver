from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.config.app_config import AppConfig
from code_diver.config.indexing_config import IndexingConfig
from code_diver.config.ai_index_config import AiIndexConfig
from code_diver.orchestration import OrchestratedCodebaseScanner, OrchestratedRetrievalStrategy
from code_diver.services import CodebaseScanner


pytestmark = pytest.mark.unit


class FakeGenerationProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, response: str):
        self.response = response
        self.prompts: list[str] = []

    def generate_json(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class FakeVectorStore:
    def metadata(self):
        return {"provider": "hash", "model": "hash-token-v1", "dimensions": 32}


class FakeBaseStrategy:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, limit: int):
        self.queries.append(query)
        return []


def test_orchestrated_scanner_does_not_send_source_contents_to_generation(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("SECRET_SOURCE_SENTINEL = 'do not send'\n", encoding="utf-8")
    provider = FakeGenerationProvider('{"include":["*.py"],"exclude":[],"chunk_lines":50}')

    scanner = OrchestratedCodebaseScanner(
        CodebaseScanner(include=["*.py"]),
        provider,
        AppConfig(root=tmp_path, indexing=IndexingConfig(mode="orchestrated", ai=AiIndexConfig(tree_limit=20))),
    )

    items = scanner.scan(tmp_path)

    assert items
    assert "SECRET_SOURCE_SENTINEL" not in provider.prompts[0]


def test_orchestrated_retrieval_plans_queries_without_index_contents() -> None:
    provider = FakeGenerationProvider('{"queries":["auth config","login settings"]}')
    base = FakeBaseStrategy()

    OrchestratedRetrievalStrategy(base, FakeVectorStore(), provider).search("auth", 5)

    assert "auth" in provider.prompts[0]
    assert "dimensions" in provider.prompts[0]
    assert base.queries == ["auth config", "login settings"]

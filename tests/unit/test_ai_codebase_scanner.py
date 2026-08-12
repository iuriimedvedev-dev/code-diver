from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.ai_indexing import AiCodebaseScanner
from code_diver.config.ai_index_config import AiIndexConfig
from code_diver.services import CodebaseScanner

pytestmark = pytest.mark.unit


class FakeGenerationProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.prompt = ""

    def generate_json(self, prompt: str, *, schema: dict | None = None) -> str:
        self.prompt = prompt
        return """
{
  "items": [
    {
      "path": "orders.py",
      "title": "Order repository",
      "summary": "Stores and loads orders through OrderRepository.",
      "kind": "module",
      "start_line": 1,
      "end_line": 4,
      "keywords": ["OrderRepository", "orders"]
    }
  ]
}
""".strip()


class BrokenGenerationProvider(FakeGenerationProvider):
    def generate_json(self, prompt: str, *, schema: dict | None = None) -> str:
        self.prompt = prompt
        raise RuntimeError("model unavailable")


def test_ai_codebase_scanner_builds_generic_semantic_items(tmp_path: Path) -> None:
    source = tmp_path / "orders.py"
    source.write_text(
        """
class OrderRepository:
    def save(self, order):
        return order
""".strip(),
        encoding="utf-8",
    )
    provider = FakeGenerationProvider()

    items = AiCodebaseScanner(
        CodebaseScanner(include=["*.py"], chunk_lines=40),
        provider,
        AiIndexConfig(max_files=5, max_items=10, max_context_chars=10000),
    ).scan(tmp_path)

    assert items[0].id.startswith("ai:orders.py#")
    assert items[0].path == "orders.py"
    assert items[0].metadata["source"] == "ai_index"
    assert "tree(path" in provider.prompt
    assert "rg(pattern" in provider.prompt
    assert "OrderRepository" in provider.prompt


def test_ai_codebase_scanner_falls_back_to_base_scan_on_generation_error(tmp_path: Path) -> None:
    source = tmp_path / "orders.py"
    source.write_text("class OrderRepository:\n    pass\n", encoding="utf-8")
    provider = BrokenGenerationProvider()
    scanner = AiCodebaseScanner(
        CodebaseScanner(include=["*.py"], chunk_lines=40),
        provider,
        AiIndexConfig(max_files=5, max_items=10, max_context_chars=10000),
    )

    items = scanner.scan(tmp_path)

    assert [item.path for item in items] == ["orders.py"]
    assert scanner.last_error is not None
    assert "RuntimeError" in scanner.last_error

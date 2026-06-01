from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_diver.config.app_config import AppConfig
from code_diver.config.indexing_config import IndexingConfig
from code_diver.config.ai_index_config import AiIndexConfig
from code_diver.config.scanner_config import ScannerConfig
from code_diver.config.trace_config import TraceConfig
from code_diver.orchestration import OrchestratedCodebaseScanner, OrchestratedRetrievalStrategy
from code_diver.services import CodebaseScanner
from code_diver.tracing import TraceLogger


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


def test_orchestrated_scanner_traces_ai_index_plan_without_source_contents(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("SECRET_SOURCE_SENTINEL = 'do not send'\n", encoding="utf-8")
    trace_path = tmp_path / "trace.jsonl"
    provider = FakeGenerationProvider(
        '{"include":["*.py"],"exclude":["build/**"],"chunk_lines":50,"symbol_chunks":true}'
    )

    scanner = OrchestratedCodebaseScanner(
        CodebaseScanner(include=["*.py"]),
        provider,
        AppConfig(
            root=tmp_path,
            indexing=IndexingConfig(mode="orchestrated", ai=AiIndexConfig(tree_limit=20)),
            trace=TraceConfig(enabled=True, artifact=trace_path, include_prompts=True),
        ),
        TraceLogger(TraceConfig(enabled=True, artifact=trace_path, include_prompts=True)),
    )

    scanner.scan(tmp_path)

    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    events = [record["event"] for record in records]
    assert "index_plan_prompt" in events
    assert "index_plan_response" in events
    assert "index_plan_selected" in events
    assert "index_scanner_config_selected" in events
    selected = next(record for record in records if record["event"] == "index_scanner_config_selected")
    assert selected["payload"]["symbol_chunks"] is True
    assert selected["payload"]["include"] == ["*.py"]
    assert "SECRET_SOURCE_SENTINEL" not in trace_path.read_text(encoding="utf-8")


def test_orchestrated_scanner_rejects_broad_ai_include_additions(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    nested = tmp_path / "evals" / "nested"
    nested.mkdir(parents=True)
    for index in range(210):
        (nested / f"case_{index}.yaml").write_text("task: demo\n", encoding="utf-8")
    trace_path = tmp_path / "trace.jsonl"
    provider = FakeGenerationProvider('{"include":["evals/**/*.yaml"],"exclude":[],"chunk_lines":50}')

    scanner = OrchestratedCodebaseScanner(
        CodebaseScanner(include=["src/*.py", "src/**/*.py"]),
        provider,
        AppConfig(
            root=tmp_path,
            indexing=IndexingConfig(mode="orchestrated", ai=AiIndexConfig(tree_limit=20)),
            scanner=ScannerConfig(include=["src/*.py", "src/**/*.py"]),
            trace=TraceConfig(enabled=True, artifact=trace_path, include_prompts=False),
        ),
        TraceLogger(TraceConfig(enabled=True, artifact=trace_path, include_prompts=False)),
    )

    items = scanner.scan(tmp_path)

    assert [item.path for item in items] == ["src/main.py"]
    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert any(record["event"] == "index_plan_rejected_include" for record in records)


def test_orchestrated_scanner_rejects_broad_ai_excludes(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    trace_path = tmp_path / "trace.jsonl"
    provider = FakeGenerationProvider('{"include":["*.py"],"exclude":["*.py"],"chunk_lines":50}')

    scanner = OrchestratedCodebaseScanner(
        CodebaseScanner(include=["src/*.py"]),
        provider,
        AppConfig(
            root=tmp_path,
            indexing=IndexingConfig(mode="orchestrated", ai=AiIndexConfig(tree_limit=20)),
            scanner=ScannerConfig(include=["src/*.py"]),
            trace=TraceConfig(enabled=True, artifact=trace_path, include_prompts=False),
        ),
        TraceLogger(TraceConfig(enabled=True, artifact=trace_path, include_prompts=False)),
    )

    items = scanner.scan(tmp_path)

    assert [item.path for item in items] == ["src/main.py"]
    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert any(record["event"] == "index_plan_rejected_exclude" for record in records)


def test_orchestrated_retrieval_plans_queries_without_index_contents() -> None:
    provider = FakeGenerationProvider('{"queries":["auth config","login settings"]}')
    base = FakeBaseStrategy()

    OrchestratedRetrievalStrategy(base, FakeVectorStore(), provider).search("auth", 5)

    assert "auth" in provider.prompts[0]
    assert "dimensions" in provider.prompts[0]
    assert base.queries == ["auth config", "login settings"]

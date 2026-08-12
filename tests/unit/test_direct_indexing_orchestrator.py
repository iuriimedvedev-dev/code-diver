from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from code_diver.agent import DirectIndexingOrchestrator
from code_diver.generation import GenerationResult
from code_diver.services import IndexingOptions

pytestmark = pytest.mark.unit


class FakeGenerationProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, responses: list[str]):
        self.responses = responses
        self.prompts: list[str] = []

    def generate_json_result(self, prompt: str, *, schema: dict | None = None) -> GenerationResult:
        self.prompts.append(prompt)
        return GenerationResult(
            text=self.responses.pop(0),
            model=self.model,
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        )

    def generate_json(self, prompt: str, *, schema: dict | None = None) -> str:
        return self.generate_json_result(prompt).text


class FakeEmbeddingProvider:
    name = "fake-embedding"
    model = "fake-embedding-model"
    dimensions = 3

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]

    def embed_query(self, query: str) -> list[float]:
        return [1.0, 0.0, 0.0]


class FakeVectorStore:
    def __init__(self) -> None:
        self.saved: dict[str, Any] | None = None

    def exists(self) -> bool:
        return self.saved is not None

    def save(self, **kwargs: Any) -> None:
        self.saved = kwargs

    def metadata(self) -> dict[str, Any]:
        return {"provider": "fake-embedding", "model": "fake-embedding-model", "dimensions": 3}

    def search(self, query_vector: list[float], limit: int) -> list[Any]:
        return []


def test_direct_indexing_orchestrator_uses_tools_and_persists_selected_ranges(tmp_path: Path) -> None:
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text(
        "class AuthService:\n    def login(self, user):\n        return user",
        encoding="utf-8",
    )
    log_path = tmp_path / "logs" / "agent.jsonl"
    generation = FakeGenerationProvider(
        [
            json.dumps(
                {
                    "reason": "inspect auth file",
                    "tool_calls": [
                        {"name": "code_diver_read", "arguments": {"file": "src/app.py", "startLine": 1, "lines": 20}}
                    ],
                }
            ),
            json.dumps(
                {
                    "reason": "persist auth service",
                    "index_items": [
                        {
                            "path": "src/app.py",
                            "startLine": 1,
                            "endLine": 3,
                            "title": "Auth service login",
                            "reason": "login handling lives here",
                            "kind": "class",
                        }
                    ],
                    "final": "indexed auth service",
                }
            ),
        ]
    )
    store = FakeVectorStore()

    result = DirectIndexingOrchestrator(
        root=tmp_path,
        generation_provider=generation,
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=store,
        allowed_tools=["code_diver_read", "code_diver_index_selected"],
        max_lines=50,
        indexing_options=IndexingOptions(progress=False),
        log_path=log_path,
    ).run("read_only", [SimpleNamespace(query="where is authorization?")])

    assert result.exit_code == 0
    assert result.indexed_items == 1
    assert result.model_calls == 2
    assert result.tool_calls == 1
    assert result.total_tokens == 30
    assert store.saved is not None
    assert store.saved["items"][0].path == "src/app.py"
    assert "where is authorization?" in generation.prompts[0]

    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    events = [record["event"] for record in records]
    assert "tool_call" in events
    assert "tool_result" in events
    assert "index_saved" in events


def test_direct_indexing_orchestrator_requires_tool_evidence_before_saving(tmp_path: Path) -> None:
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("class AuthService:\n    pass\n", encoding="utf-8")
    log_path = tmp_path / "logs" / "agent.jsonl"
    generation = FakeGenerationProvider(
        [
            json.dumps(
                {
                    "reason": "premature index",
                    "index_items": [
                        {
                            "path": "src/app.py",
                            "startLine": 1,
                            "endLine": 2,
                            "title": "Auth service",
                            "reason": "guess",
                            "kind": "class",
                        }
                    ],
                }
            ),
            json.dumps(
                {
                    "reason": "gather evidence",
                    "tool_calls": [
                        {"name": "code_diver_read", "arguments": {"file": "src/app.py", "startLine": 1, "lines": 5}}
                    ],
                }
            ),
            json.dumps(
                {
                    "reason": "persist grounded range",
                    "index_items": [
                        {
                            "path": "src/app.py",
                            "startLine": 1,
                            "endLine": 2,
                            "title": "Auth service",
                            "reason": "read evidence",
                            "kind": "class",
                        }
                    ],
                }
            ),
        ]
    )
    store = FakeVectorStore()

    result = DirectIndexingOrchestrator(
        root=tmp_path,
        generation_provider=generation,
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=store,
        allowed_tools=["code_diver_read", "code_diver_index_selected"],
        max_lines=50,
        indexing_options=IndexingOptions(progress=False),
        log_path=log_path,
    ).run("ai_selected_index", [SimpleNamespace(query="where is auth?")])

    assert result.exit_code == 0
    assert result.indexed_items == 1
    assert result.model_calls == 3
    events = [json.loads(line)["event"] for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert "indexing_evidence_required" in events

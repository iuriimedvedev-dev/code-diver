from __future__ import annotations

from types import SimpleNamespace

import pytest

from code_diver.providers.gemini_embedding_provider import GeminiEmbeddingProvider


pytestmark = pytest.mark.unit


class FakePart:
    def __init__(self, text: str):
        self.text = text

    @classmethod
    def from_text(cls, *, text: str):
        return cls(text)


class FakeContent:
    def __init__(self, *, parts):
        self.parts = parts


class FakeEmbedContentConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeModels:
    def __init__(self, calls: list[dict]):
        self.calls = calls

    def embed_content(self, **kwargs):
        self.calls.append(kwargs)
        contents = kwargs["contents"]
        count = len(contents) if isinstance(contents, list) else 1
        return SimpleNamespace(embeddings=[[float(index)] for index in range(count)])


def test_gemini_embedding_2_uses_instruction_content_without_task_type() -> None:
    calls: list[dict] = []
    provider = _provider("gemini-embedding-2", calls)

    vectors = provider.embed_documents(["class User: pass", "def save(): pass"])

    assert vectors == [[0.0], [1.0]]
    assert all(isinstance(content, FakeContent) for content in calls[0]["contents"])
    assert calls[0]["contents"][0].parts[0].text.startswith("Task: retrieve relevant codebase context.")
    assert calls[0]["config"].kwargs == {"output_dimensionality": 768}


def test_gemini_embedding_001_keeps_task_type_batching() -> None:
    calls: list[dict] = []
    provider = _provider("gemini-embedding-001", calls)

    vectors = provider.embed_documents(["a", "b"])

    assert vectors == [[0.0], [1.0]]
    assert calls[0]["contents"] == ["a", "b"]
    assert calls[0]["config"].kwargs == {
        "output_dimensionality": 768,
        "task_type": "RETRIEVAL_DOCUMENT",
    }


def _provider(model: str, calls: list[dict]) -> GeminiEmbeddingProvider:
    provider = GeminiEmbeddingProvider.__new__(GeminiEmbeddingProvider)
    provider.model = model
    provider.dimensions = 768
    provider.batch_size = 32
    provider.retry_attempts = 1
    provider.retry_delay_seconds = 0
    provider.client = SimpleNamespace(models=FakeModels(calls))
    provider.types = SimpleNamespace(
        Content=FakeContent,
        Part=FakePart,
        EmbedContentConfig=FakeEmbedContentConfig,
    )
    return provider

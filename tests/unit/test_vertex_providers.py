from __future__ import annotations

from types import SimpleNamespace

import pytest

from code_diver.generation.vertex_generation_provider import VertexGenerationProvider
from code_diver.generation.transient_generation_retry import TransientGenerationRetry
from code_diver.providers.vertex_embedding_provider import VertexEmbeddingProvider


pytestmark = pytest.mark.unit


class FakeGenerateContentConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeThinkingConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeEmbedContentConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakePart:
    def __init__(self, text: str):
        self.text = text

    @classmethod
    def from_text(cls, *, text: str):
        return cls(text)


class FakeContent:
    def __init__(self, *, parts):
        self.parts = parts


class FakeModels:
    def __init__(self):
        self.generate_calls: list[dict] = []
        self.embed_calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.generate_calls.append(kwargs)
        return SimpleNamespace(text='{"ok": true}')

    def embed_content(self, **kwargs):
        self.embed_calls.append(kwargs)
        contents = kwargs["contents"]
        count = len(contents) if isinstance(contents, list) else 1
        return SimpleNamespace(embeddings=[[float(index)] for index in range(count)])


def test_vertex_generation_provider_reuses_json_generation_contract() -> None:
    models = FakeModels()
    provider = VertexGenerationProvider.__new__(VertexGenerationProvider)
    provider.name = "vertex"
    provider.model = "gemini-3.5-flash"
    provider.fallback_models = []
    provider.temperature = 0
    provider.thinking_budget = 128
    provider.timeout_ms = 20_000
    provider.retry = TransientGenerationRetry(attempts=1, sleep=lambda _: None)
    provider.client = SimpleNamespace(models=models)
    provider.types = SimpleNamespace(
        GenerateContentConfig=FakeGenerateContentConfig,
        ThinkingConfig=FakeThinkingConfig,
    )

    assert provider.generate_json("return json") == '{"ok": true}'
    assert models.generate_calls[0]["model"] == "gemini-3.5-flash"
    assert models.generate_calls[0]["config"].kwargs["response_mime_type"] == "application/json"


def test_vertex_embedding_provider_reuses_embedding_2_contract() -> None:
    models = FakeModels()
    provider = VertexEmbeddingProvider.__new__(VertexEmbeddingProvider)
    provider.name = "vertex"
    provider.model = "gemini-embedding-2"
    provider.dimensions = 768
    provider.batch_size = 32
    provider.retry_attempts = 1
    provider.retry_delay_seconds = 0
    provider.client = SimpleNamespace(models=models)
    provider.types = SimpleNamespace(
        Content=FakeContent,
        Part=FakePart,
        EmbedContentConfig=FakeEmbedContentConfig,
    )

    assert provider.embed_documents(["a", "b"]) == [[0.0], [1.0]]
    assert len(models.embed_calls) == 1
    assert models.embed_calls[0]["config"].kwargs == {"output_dimensionality": 768}
    assert models.embed_calls[0]["contents"][0].parts[0].text.startswith("Task: retrieve relevant codebase context.")

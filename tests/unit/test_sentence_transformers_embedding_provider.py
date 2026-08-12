from __future__ import annotations

import sys
import types

import pytest

from code_diver.providers import create_embedding_provider
from code_diver.providers.sentence_transformers_embedding_provider import SentenceTransformersEmbeddingProvider

pytestmark = pytest.mark.unit


class _Encoded:
    def __init__(self, rows: list[list[float]]):
        self.rows = rows

    def tolist(self) -> list[list[float]]:
        return self.rows


class _FakeSentenceTransformer:
    calls: list[dict] = []

    def __init__(self, model: str):
        self.model = model

    def encode(self, texts: list[str], **kwargs):
        self.calls.append({"model": self.model, "texts": texts, "kwargs": kwargs})
        return _Encoded([[float(index), float(len(text))] for index, text in enumerate(texts)])


def test_sentence_transformers_provider_embeds_with_prefixes_and_bounds(monkeypatch) -> None:
    _FakeSentenceTransformer.calls = []
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=_FakeSentenceTransformer),
    )
    provider = SentenceTransformersEmbeddingProvider(
        "local/embedder",
        batch_size=2,
        document_prefix="doc: ",
        query_prefix="query: ",
        max_input_chars=10,
    )

    assert provider.embed_documents(["abcdef", "ghijkl"]) == [[0.0, 10.0], [1.0, 10.0]]
    assert provider.embed_query("abcdef") == [0.0, 10.0]
    assert provider.dimensions == 2
    assert _FakeSentenceTransformer.calls[0]["texts"] == ["doc: abcde", "doc: ghijk"]
    assert _FakeSentenceTransformer.calls[1]["texts"] == ["query: abc"]
    assert _FakeSentenceTransformer.calls[0]["kwargs"]["normalize_embeddings"] is True


def test_sentence_transformers_provider_rejects_dimension_mismatch(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=_FakeSentenceTransformer),
    )
    provider = SentenceTransformersEmbeddingProvider("local/embedder", dimensions=3)

    with pytest.raises(RuntimeError, match="dimension mismatch"):
        provider.embed_query("query")


def test_provider_factory_creates_sentence_transformers_provider(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=_FakeSentenceTransformer),
    )
    provider = create_embedding_provider(
        "sentence_transformers",
        model="local/embedder",
        dimensions=None,
        batch_size=4,
    )

    assert isinstance(provider, SentenceTransformersEmbeddingProvider)
    assert provider.name == "sentence_transformers"
    assert provider.model == "local/embedder"

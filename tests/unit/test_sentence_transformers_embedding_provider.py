from __future__ import annotations

import sys
import types

import pytest

from code_diver.providers import create_embedding_provider
from code_diver.providers.sentence_transformers_embedding_provider import SentenceTransformersEmbeddingProvider
from code_diver.services.embedding_text_preparer import truncate_embedding_text

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


class _CharacterTokenizer:
    def encode(self, text: str, add_special_tokens: bool = False) -> list[str]:
        return list(text)

    def decode(self, tokens: list[str], skip_special_tokens: bool = True) -> str:
        return "".join(tokens)


def test_embedding_text_truncation_handles_punctuation_and_generics_at_token_boundaries() -> None:
    tokenizer = _CharacterTokenizer()
    assert truncate_embedding_text("Map<String,List<int>>!!!", 17, tokenizer) == "Map<String,List<i"
    assert truncate_embedding_text("abcdef", 20, tokenizer) == "abcdef"


def test_sentence_transformers_retries_only_overflowing_item(monkeypatch) -> None:
    class _RetryModel(_FakeSentenceTransformer):
        def encode(self, texts: list[str], **kwargs):
            self.calls.append({"model": self.model, "texts": texts, "kwargs": kwargs})
            if len(texts) > 1:
                raise RuntimeError("input too long for context length")
            return _Encoded([[1.0, float(len(texts[0]))]])

    _RetryModel.calls = []
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=_RetryModel),
    )
    provider = SentenceTransformersEmbeddingProvider("local/embedder", batch_size=2, max_input_chars=None)

    assert provider.embed_documents(["short", "long" * 20]) == [[1.0, 5.0], [1.0, 40.0]]
    assert _RetryModel.calls[0]["texts"] == ["short", "long" * 20]
    assert _RetryModel.calls[1]["texts"] == ["short"]
    assert _RetryModel.calls[2]["texts"] == ["long" * 20]

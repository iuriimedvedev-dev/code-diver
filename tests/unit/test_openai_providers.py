from __future__ import annotations

import json

import pytest

from code_diver.generation.openai_generation_provider import OpenAIGenerationProvider
from code_diver.generation.openai_compatible_generation_provider import OpenAICompatibleGenerationProvider
from code_diver.providers.openai_compatible_embedding_provider import OpenAICompatibleEmbeddingProvider
from code_diver.providers.openai_embedding_provider import OpenAIEmbeddingProvider


pytestmark = pytest.mark.unit


def test_openai_embedding_provider_posts_embedding_payload(monkeypatch) -> None:
    provider = OpenAIEmbeddingProvider(api_key="key", dimensions=3, batch_size=2)
    calls: list[dict] = []

    def fake_post(payload):
        calls.append(payload)
        return {
            "data": [
                {"index": 0, "embedding": [1, 2, 3]},
                {"index": 1, "embedding": [4, 5, 6]},
            ]
        }

    monkeypatch.setattr(provider, "_post", fake_post)

    assert provider.embed_documents(["a", "b"]) == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    assert calls[0]["model"] == "text-embedding-3-large"
    assert calls[0]["dimensions"] == 3


def test_openai_generation_provider_requests_json_output(monkeypatch) -> None:
    provider = OpenAIGenerationProvider(api_key="key")
    calls: list[dict] = []

    def fake_post(payload):
        calls.append(payload)
        return {"output_text": json.dumps({"items": []})}

    monkeypatch.setattr(provider, "_post", fake_post)

    assert provider.generate_json("build index") == '{"items": []}'
    assert calls[0]["model"] == "gpt-5.1"
    assert calls[0]["text"]["format"]["type"] == "json_object"


def test_openai_compatible_generation_provider_uses_chat_completions(monkeypatch) -> None:
    provider = OpenAICompatibleGenerationProvider(model="local-model", api_key="local")
    calls: list[dict] = []

    def fake_post(payload):
        calls.append(payload)
        return {"choices": [{"message": {"content": '{"queries":["x"]}'}}]}

    monkeypatch.setattr(provider, "_post", fake_post)

    assert provider.generate_json("plan") == '{"queries":["x"]}'
    assert calls[0]["messages"][0]["role"] == "system"
    assert calls[0]["response_format"]["type"] == "json_object"


def test_openai_compatible_embedding_provider_allows_local_api_key(monkeypatch) -> None:
    provider = OpenAICompatibleEmbeddingProvider(model="embed", dimensions=None, api_key=None)

    def fake_post(payload):
        return {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}

    monkeypatch.setattr(provider, "_post", fake_post)

    assert provider.embed_query("query") == [0.1, 0.2]
    assert provider.name == "openai_compatible"

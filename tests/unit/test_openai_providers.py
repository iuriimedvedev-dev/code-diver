from __future__ import annotations

import json

import pytest

from code_diver.generation.openai_generation_provider import OpenAIGenerationProvider
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
